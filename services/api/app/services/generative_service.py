from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.ai.generative import (
    GeneratedImage,
    GenerativeImageInput,
    GenerativeProvider,
    GenerativeProviderError,
    GenerativeProviderJob,
    GenerativeRequest,
    GenerativeRequestSpec,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.core.identity import OwnerScope
from app.imaging.loader import load_image
from app.imaging.output import encode_image, to_uint8
from app.models.generative import (
    GeneratedAssetRecord,
    GenerativeCapabilitiesResponse,
    GenerativeErrorInfo,
    GenerativePlan,
    GenerativeResultRecord,
    GenerativeResultStatus,
    GenerativeResultView,
    GenerativeTaskCreated,
    GenerativeTaskListResponse,
    GenerativeTaskRecord,
    GenerativeTaskRequest,
    GenerativeTaskStage,
    GenerativeTaskStatus,
    GenerativeTaskStatusResponse,
    GenerativeTaskType,
)
from app.models.sessions import CreateRevisionRequest, SessionState
from app.repositories.generative_repo import (
    DuplicateGeneratedAssetError,
    DuplicateGenerativeTaskError,
    RetryNotAllowedError,
    SqliteGenerativeRepository,
)
from app.repositories.session_repo import RevisionCreation
from app.services.asset_resolver import ImageAssetResolver, ResolvedImage
from app.services.generated_asset_store import GeneratedAssetStore
from app.services.session_service import SessionService

logger = logging.getLogger("frame_ai.generative")

_RESULT_URL_PREFIX = "/api/v1/generative/results"
_MASK_DIRNAME = "masks"
_MASK_WARNING = "protected_region_restored"
_MOCK_WARNING = "mock_output"
_BLANK_STD_THRESHOLD = 0.5


class _TaskCancelled(Exception):
    pass


def composite_protected_region(
    input_pixels: NDArray[np.uint8],
    result_pixels: NDArray[np.uint8],
    mask: NDArray[np.uint8],
) -> NDArray[np.uint8]:
    """Blend only where the mask is set; outside stays byte-identical input."""
    if input_pixels.shape != result_pixels.shape or mask.shape != input_pixels.shape[:2]:
        raise ValueError("input, result and mask geometry must match")
    alpha = mask.astype(np.float32) / np.float32(255.0)
    blended = (
        input_pixels.astype(np.float32) * (np.float32(1.0) - alpha[..., None])
        + result_pixels.astype(np.float32) * alpha[..., None]
    )
    output = np.clip(np.rint(blended), 0.0, 255.0).astype(np.uint8)
    outside = alpha == 0
    output[outside] = input_pixels[outside]
    return np.ascontiguousarray(output)


class GenerativeTaskService:
    def __init__(
        self,
        settings: Settings,
        sessions: SessionService,
        provider: GenerativeProvider,
        repository: SqliteGenerativeRepository,
        store: GeneratedAssetStore,
        assets: ImageAssetResolver,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.provider = provider
        self.repository = repository
        self.store = store
        self.assets = assets
        self._executor = executor or ThreadPoolExecutor(
            max_workers=settings.generative_max_concurrency,
            thread_name_prefix="frame-generative",
        )
        self._closed = False

    # ----------------------------------------------------------------- public

    def capabilities(self) -> GenerativeCapabilitiesResponse:
        capabilities = self.provider.capabilities()
        return GenerativeCapabilitiesResponse(
            provider=self.provider.name,
            model=self.provider.model,
            is_mock=self.provider.is_mock,
            supported_task_types=list(capabilities.supported_task_types),
            supports_mask=capabilities.supports_mask,
            supports_multiple_outputs=capabilities.supports_multiple_outputs,
            max_output_pixels=capabilities.max_output_pixels,
            max_long_edge=capabilities.max_long_edge,
            allowed_output_formats=list(capabilities.allowed_output_formats),
            declared_retention=capabilities.declared_retention,
            notes=list(capabilities.notes),
        )

    def create(
        self,
        request: GenerativeTaskRequest,
        *,
        owner: OwnerScope,
        idempotency_key: str | None,
    ) -> tuple[GenerativeTaskCreated, bool]:
        session = self.sessions.get(str(request.session_id))
        image_id = str(session.image_id)
        capabilities = self.provider.capabilities()
        base_generated_asset_id = (
            None
            if session.revision.base_generated_asset_id is None
            else str(session.revision.base_generated_asset_id)
        )
        mask_id = None if request.mask_id is None else str(request.mask_id)
        if mask_id is not None:
            self._validate_mask(mask_id, image_id, base_generated_asset_id)

        base = self.assets.resolve(image_id, base_generated_asset_id)
        try:
            self.provider.validate_spec(
                GenerativeRequestSpec(
                    task_type=request.task_type,
                    instruction=request.instruction.strip(),
                    has_mask=mask_id is not None,
                    candidates=request.params.candidates,
                    input_width=base.width,
                    input_height=base.height,
                )
            )
        except GenerativeProviderError as exc:
            status_code = 413 if exc.code == "generative_input_too_large" else 422
            raise AppError(status_code, exc.code, exc.message, exc.details) from exc

        if not self.provider.is_mock and not request.consent:
            raise AppError(
                422,
                "generative_consent_required",
                "Confirm that the image may be sent to the selected provider.",
            )

        plan = GenerativePlan(
            task_type=request.task_type,
            instruction=request.instruction.strip(),
            target="mask" if mask_id is not None else "full-image",
            mask_id=request.mask_id,
            preserve=["pixels outside the editable region"],
            candidates=request.params.candidates,
        )
        params_payload = request.params.model_dump(mode="json")
        dedupe_key = self._dedupe_key(
            owner.owner_id,
            str(session.session_id),
            str(session.image_id),
            str(session.active_revision_id),
            base_generated_asset_id,
            request.task_type,
            plan.instruction,
            params_payload,
            mask_id,
        )

        if idempotency_key:
            existing = self.repository.find_by_idempotency(owner.owner_id, idempotency_key)
            if existing is not None:
                if existing.dedupe_key != dedupe_key:
                    raise AppError(
                        409,
                        "idempotency_key_reuse",
                        "The Idempotency-Key was already used with a different task.",
                        {"taskId": existing.id},
                    )
                return self._created(existing, deduplicated=True), True

        existing = self.repository.find_by_dedupe(dedupe_key)
        if existing is not None:
            return self._created(self._expire(existing), deduplicated=True), True

        if self.repository.count_active(owner.owner_id) >= self.settings.generative_queue_max:
            raise AppError(
                503,
                "server_busy",
                "The generation queue is full. Try again once earlier tasks finish.",
                {"queueMax": self.settings.generative_queue_max},
                headers={"Retry-After": "5"},
            )

        now = datetime.now(UTC)
        task = GenerativeTaskRecord(
            id=str(uuid4()),
            owner_id=owner.owner_id,
            image_id=image_id,
            session_id=str(session.session_id),
            base_revision_id=str(session.active_revision_id),
            base_generated_asset_id=base_generated_asset_id,
            task_type=request.task_type,
            instruction=plan.instruction,
            plan_json=plan.model_dump_json(),
            params_json=json.dumps(
                params_payload,
                sort_keys=True,
                separators=(",", ":"),
            ),
            mask_id=mask_id,
            provider=self.provider.name,
            model=self.provider.model,
            prompt_version=self.provider.prompt_version,
            is_mock=self.provider.is_mock,
            status=GenerativeTaskStatus.QUEUED,
            stage=GenerativeTaskStage.QUEUED,
            attempts=0,
            max_attempts=self.settings.generative_max_attempts,
            consent_at=now if request.consent else None,
            provider_retention=capabilities.declared_retention,
            dedupe_key=dedupe_key,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self.settings.generative_task_ttl_seconds),
        )
        try:
            self.repository.create_task(task)
        except DuplicateGenerativeTaskError:
            existing = self.repository.find_by_dedupe(dedupe_key)
            if existing is None and idempotency_key:
                existing = self.repository.find_by_idempotency(
                    owner.owner_id,
                    idempotency_key,
                )
                if existing is not None and existing.dedupe_key != dedupe_key:
                    raise AppError(
                        409,
                        "idempotency_key_reuse",
                        "The Idempotency-Key was already used with a different task.",
                        {"taskId": existing.id},
                    ) from None
            if existing is None:
                raise
            return self._created(existing, deduplicated=True), True

        self._submit(task.id)
        logger.info(
            "generative_task_queued task_id=%s session_id=%s type=%s provider=%s is_mock=%s",
            task.id,
            task.session_id,
            task.task_type.value,
            task.provider,
            task.is_mock,
        )
        return self._created(task, deduplicated=False), False

    def status(self, task_id: str, *, owner: OwnerScope) -> GenerativeTaskStatusResponse:
        task = self._require_task(task_id, owner)
        return self._status_response(self._expire(task))

    def list_tasks(
        self,
        *,
        owner: OwnerScope,
        limit: int,
        offset: int,
        status: GenerativeTaskStatus | None,
    ) -> GenerativeTaskListResponse:
        tasks = self.repository.list_tasks(
            owner.owner_id,
            limit=limit,
            offset=offset,
            status=status,
        )
        return GenerativeTaskListResponse(
            items=[self._status_response(self._expire(task)) for task in tasks]
        )

    def cancel(self, task_id: str, *, owner: OwnerScope) -> GenerativeTaskStatusResponse:
        self._require_task(task_id, owner)
        task = self.repository.cancel(task_id)
        if task is None:
            raise AppError(404, "generative_task_not_found", "The task was not found.")
        return self._status_response(self._expire(task))

    def retry(self, task_id: str, *, owner: OwnerScope) -> GenerativeTaskStatusResponse:
        task = self._require_task(task_id, owner)
        stale_results = self.repository.list_results(task.id)
        try:
            task = self.repository.reset_for_retry(task.id)
        except KeyError as exc:
            raise AppError(404, "generative_task_not_found", "The task was not found.") from exc
        except RetryNotAllowedError as exc:
            raise AppError(409, "generative_retry_not_allowed", str(exc)) from exc
        for result in stale_results:
            self.store.discard(result.storage_key)
        self._submit(task.id)
        logger.info("generative_task_retried task_id=%s attempt=%s", task.id, task.attempts + 1)
        return self._status_response(task)

    def accept_result(self, result_id: str, *, owner: OwnerScope) -> SessionState:
        result = self.repository.get_result_for_owner(result_id, owner.owner_id)
        if result is None:
            raise AppError(404, "generative_result_not_found", "The result was not found.")
        task = self.repository.get_task(result.task_id)
        if task is None:
            raise AppError(404, "generative_task_not_found", "The task was not found.")
        if result.status is GenerativeResultStatus.ACCEPTED:
            return self.sessions.get(task.session_id)
        if result.status is not GenerativeResultStatus.CANDIDATE:
            raise AppError(
                409,
                "generative_result_not_candidate",
                "Only a pending result can be accepted.",
                {"status": result.status.value},
            )
        if task.status is not GenerativeTaskStatus.SUCCEEDED:
            raise AppError(409, "generative_task_not_ready", "The task has not succeeded yet.")

        session = self.sessions.get(task.session_id)
        if task.base_revision_id is not None and (
            task.base_revision_id.lower() != str(session.active_revision_id).lower()
        ):
            raise AppError(
                409,
                "generative_base_changed",
                "The photo has newer edits. Generate again from the current version.",
                {"baseRevisionId": task.base_revision_id},
            )

        asset = self._ensure_generated_asset(result, task)
        idempotency_key = f"generative-accept:{result.id}"
        existing_revision = self.sessions.idempotent_revision(task.session_id, idempotency_key)
        if existing_revision is not None:
            self.repository.mark_result_accepted(result.id, existing_revision.id)
            return self.sessions.get(task.session_id)

        state, _ = self.sessions.add_revision(
            task.session_id,
            CreateRevisionRequest(
                recipe=session.revision.recipe,
                parent_revision_id=session.active_revision_id,
                source="ai",
            ),
            idempotency_key=idempotency_key,
            creation=RevisionCreation(
                generative_task_id=task.id,
                base_generated_asset_id=asset.id,
            ),
        )
        self.repository.mark_result_accepted(result.id, str(state.active_revision_id))
        logger.info(
            "generative_result_accepted result_id=%s task_id=%s revision_id=%s",
            result.id,
            task.id,
            state.active_revision_id,
        )
        return state

    def reject_result(self, result_id: str, *, owner: OwnerScope) -> GenerativeResultView:
        result = self.repository.get_result_for_owner(result_id, owner.owner_id)
        if result is None:
            raise AppError(404, "generative_result_not_found", "The result was not found.")
        if result.status is GenerativeResultStatus.REJECTED:
            return self._result_view(result)
        if result.status is not GenerativeResultStatus.CANDIDATE:
            raise AppError(
                409,
                "generative_result_not_candidate",
                "Only a pending result can be rejected.",
                {"status": result.status.value},
            )
        self.repository.mark_result_rejected(result.id)
        updated = self.repository.get_result(result.id)
        return self._result_view(updated or result)

    def result_image(self, result_id: str, *, owner: OwnerScope) -> tuple[Path, str]:
        result = self.repository.get_result_for_owner(result_id, owner.owner_id)
        if result is None:
            raise AppError(404, "generative_result_not_found", "The result was not found.")
        return self.store.resolve(result.storage_key), result.mime_type

    def recover(self) -> int:
        self.store.cleanup_temp()
        queued = self.repository.recover_startup()
        self.cleanup_expired_results()
        for task_id in queued:
            self._submit(task_id)
        logger.info("generative_recovered pending=%s", len(queued))
        return len(queued)

    def cleanup_expired_results(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(seconds=self.settings.generative_result_ttl_seconds)
        purgeable = self.repository.list_purgeable_results(cutoff)
        for _result_id, storage_key in purgeable:
            self.store.discard(storage_key)
        self.repository.delete_results([result_id for result_id, _ in purgeable])
        if purgeable:
            logger.info("generative_results_purged count=%s", len(purgeable))
        return len(purgeable)

    def shutdown(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    # ---------------------------------------------------------------- worker

    def _submit(self, task_id: str) -> None:
        if self._closed:
            return
        try:
            self._executor.submit(self._run, task_id)
        except RuntimeError:
            logger.warning("generative_submit_rejected task_id=%s", task_id)

    def _run(self, task_id: str) -> None:
        task = self.repository.claim(task_id)
        if task is None:
            return
        started = time.perf_counter()
        try:
            self._execute(task)
        except _TaskCancelled:
            current = self.repository.get_task(task.id)
            if current is not None and current.error_code == "expired":
                self._mark_terminal(task.id, "expired")
                logger.info("generative_task_expired task_id=%s", task.id)
            else:
                self._mark_terminal(task.id, "cancelled")
                logger.info("generative_task_cancelled task_id=%s", task.id)
        except AppError as exc:
            self._fail(task.id, exc.code, exc.message)
            logger.warning("generative_task_failed task_id=%s code=%s", task.id, exc.code)
        except GenerativeProviderError as exc:
            self._fail(task.id, exc.code, exc.message)
            logger.warning("generative_task_failed task_id=%s code=%s", task.id, exc.code)
        except Exception:
            logger.exception("generative_worker_crashed task_id=%s", task.id)
            self._fail(
                task.id,
                "generative_internal_error",
                "The generation failed unexpectedly.",
            )
        else:
            logger.info(
                "generative_task_completed task_id=%s duration_ms=%.1f",
                task.id,
                (time.perf_counter() - started) * 1000.0,
            )

    def _fail(self, task_id: str, code: str, message: str) -> None:
        try:
            self.repository.fail(task_id, code, message)
        except Exception:
            logger.exception("generative_fail_persist_failed task_id=%s", task_id)

    def _mark_terminal(self, task_id: str, outcome: str) -> None:
        try:
            if outcome == "expired":
                self.repository.mark_expired(task_id)
            else:
                self.repository.mark_cancelled(task_id)
        except Exception:
            logger.exception("generative_terminal_persist_failed task_id=%s", task_id)

    def _execute(self, task: GenerativeTaskRecord) -> None:
        capabilities = self.provider.capabilities()
        base = self.assets.resolve(task.image_id, task.base_generated_asset_id)
        self.repository.set_stage(task.id, GenerativeTaskStage.PREPARING_INPUT.value)
        input_bytes, input_pixels, width, height = self._prepare_input(
            base,
            capabilities.max_output_pixels,
        )
        mask_bytes = self._load_mask(task, width, height)
        self._raise_if_cancelled(task.id)

        self.repository.set_stage(task.id, GenerativeTaskStage.SUBMITTING.value)
        request = GenerativeRequest(
            task_id=task.id,
            task_type=task.task_type,
            instruction=task.instruction,
            image=GenerativeImageInput(
                data=input_bytes,
                mime_type="image/png",
                width=width,
                height=height,
                mask=mask_bytes,
                mask_mime_type="image/png" if mask_bytes is not None else None,
            ),
            params=json.loads(task.params_json),
            prompt_version=task.prompt_version,
        )
        self.provider.validate_request(request)
        job = self.provider.submit(request)
        self.repository.set_provider_job_id(task.id, job.provider_job_id)
        self.repository.set_stage(task.id, GenerativeTaskStage.GENERATING.value)
        job = self._wait_for_job(task, job)

        self.repository.set_stage(task.id, GenerativeTaskStage.VALIDATING.value)
        generated = self.provider.fetch(job)
        data, warnings = self._validate_output(
            task,
            generated,
            input_pixels=input_pixels,
            width=width,
            height=height,
            mask_bytes=mask_bytes,
        )
        self._raise_if_cancelled(task.id)

        self.repository.set_stage(task.id, GenerativeTaskStage.SAVING.value)
        result_id = str(uuid4())
        storage_key = self.store.save_candidate(result_id, data)
        if self.repository.is_cancel_requested(task.id):
            self.store.discard(storage_key)
            raise _TaskCancelled
        now = datetime.now(UTC)
        result = GenerativeResultRecord(
            id=result_id,
            task_id=task.id,
            result_index=0,
            storage_key=storage_key,
            sha256=hashlib.sha256(data).hexdigest(),
            width=width,
            height=height,
            bytes=len(data),
            mime_type="image/png",
            status=GenerativeResultStatus.CANDIDATE,
            validation_json=json.dumps(
                {
                    "warnings": warnings,
                    "isMock": task.is_mock,
                    "format": "PNG",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            created_at=now,
        )
        if not self.repository.complete_with_result(task.id, result):
            self.store.discard(storage_key)
            self._raise_if_cancelled(task.id)

    def _wait_for_job(
        self,
        task: GenerativeTaskRecord,
        job: GenerativeProviderJob,
    ) -> GenerativeProviderJob:
        deadline = time.monotonic() + self.settings.generative_task_timeout_seconds
        while job.status in ("queued", "processing"):
            if self.repository.is_cancel_requested(task.id):
                self._safe_cancel(job)
                raise _TaskCancelled
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._safe_cancel(job)
                raise AppError(
                    504,
                    "generative_timeout",
                    "The generation did not finish in time.",
                )
            time.sleep(min(0.2, remaining))
            job = self.provider.poll(job)
        if job.status == "failed":
            raise GenerativeProviderError(
                job.error_code or "generative_provider_failed",
                job.error_message or "The provider did not return a result.",
            )
        return job

    def _safe_cancel(self, job: GenerativeProviderJob) -> None:
        try:
            self.provider.cancel(job)
        except Exception:
            logger.warning("generative_provider_cancel_failed job_id=%s", job.provider_job_id)

    def _prepare_input(
        self,
        base: ResolvedImage,
        provider_max_pixels: int,
    ) -> tuple[bytes, NDArray[np.uint8], int, int]:
        limit = min(self.settings.generative_max_input_pixels, provider_max_pixels)
        try:
            image = load_image(base.path, max_pixels=limit, preserve_alpha=False)
        except AppError as exc:
            raise AppError(
                413,
                "generative_input_too_large",
                "The image is larger than the generative pipeline currently accepts.",
                {"maxPixels": limit, "reason": exc.code},
            ) from exc
        pixels = to_uint8(image.rgb)
        data = encode_image(pixels, image_format="png")
        if len(data) > self.settings.generative_max_output_bytes:
            raise AppError(
                413,
                "generative_input_too_large",
                "The prepared input exceeds the configured generative size limit.",
                {"bytes": len(data)},
            )
        return data, pixels, image.width, image.height

    def _validate_output(
        self,
        task: GenerativeTaskRecord,
        generated: GeneratedImage,
        *,
        input_pixels: NDArray[np.uint8],
        width: int,
        height: int,
        mask_bytes: bytes | None,
    ) -> tuple[bytes, list[str]]:
        if not generated.data:
            raise AppError(502, "generative_invalid_output", "The provider returned no image.")
        if len(generated.data) > self.settings.generative_max_output_bytes:
            raise AppError(
                413,
                "generative_output_too_large",
                "The provider returned an image larger than the configured limit.",
                {"bytes": len(generated.data)},
            )
        limit = min(
            self.settings.generative_max_output_pixels,
            self.provider.capabilities().max_output_pixels,
        )
        try:
            loaded = load_image(generated.data, max_pixels=limit, preserve_alpha=False)
        except AppError as exc:
            raise AppError(
                502,
                "generative_invalid_output",
                "The provider returned an unreadable image.",
                {"reason": exc.code},
            ) from exc
        if (loaded.width, loaded.height) != (width, height):
            raise AppError(
                502,
                "generative_invalid_output_size",
                "The provider returned an image with unexpected dimensions.",
                {"expected": [width, height], "actual": [loaded.width, loaded.height]},
            )
        pixels = to_uint8(loaded.rgb)
        if float(np.std(pixels.astype(np.float32))) < _BLANK_STD_THRESHOLD:
            raise AppError(
                502,
                "generative_blank_output",
                "The provider returned an image without visible variation.",
            )
        warnings: list[str] = []
        if task.is_mock:
            warnings.append(_MOCK_WARNING)
        if mask_bytes is not None:
            mask = self._decode_mask(mask_bytes, width, height)
            pixels = composite_protected_region(input_pixels, pixels, mask)
            warnings.append(_MASK_WARNING)
        if np.array_equal(pixels, input_pixels):
            raise AppError(
                502,
                "generative_no_visible_change",
                "The provider returned an image identical to the input.",
            )
        data = encode_image(pixels, image_format="png")
        if len(data) > self.settings.generative_max_output_bytes:
            raise AppError(
                413,
                "generative_output_too_large",
                "The normalized result exceeds the configured size limit.",
                {"bytes": len(data)},
            )
        return data, warnings

    def _validate_mask(
        self,
        mask_id: str,
        image_id: str,
        base_generated_asset_id: str | None,
    ) -> None:
        mask = self.repository.get_mask(mask_id)
        if mask is None:
            raise AppError(404, "generative_mask_not_found", "The mask was not found.")
        if mask.image_id.lower() != image_id.lower():
            raise AppError(409, "generative_mask_mismatch", "The mask belongs to another image.")
        mask_base = mask.base_generated_asset_id
        if (mask_base or "").lower() != (base_generated_asset_id or "").lower():
            raise AppError(
                409,
                "generative_mask_mismatch",
                "The mask was drawn for a different image version.",
            )

    def _load_mask(
        self,
        task: GenerativeTaskRecord,
        width: int,
        height: int,
    ) -> bytes | None:
        if task.mask_id is None:
            return None
        mask = self.repository.get_mask(task.mask_id)
        if mask is None:
            raise AppError(409, "generative_mask_missing", "The mask is no longer available.")
        if (mask.width, mask.height) != (width, height):
            raise AppError(
                409,
                "generative_mask_size_mismatch",
                "The mask does not match the image dimensions.",
            )
        root = (self.settings.data_dir / _MASK_DIRNAME).resolve()
        path = (self.settings.data_dir / mask.storage_key).resolve()
        if root != path.parent and root not in path.parents:
            raise AppError(500, "generative_mask_unavailable", "The mask path is invalid.")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise AppError(
                409,
                "generative_mask_missing",
                "The mask file is no longer available.",
            ) from exc

    def _decode_mask(self, data: bytes, width: int, height: int) -> NDArray[np.uint8]:
        try:
            with Image.open(BytesIO(data)) as opened:
                mask = opened.convert("L")
                if mask.size != (width, height):
                    mask = mask.resize((width, height), Image.Resampling.NEAREST)
                return np.asarray(mask, dtype=np.uint8)
        except (OSError, ValueError, SyntaxError) as exc:
            raise AppError(
                409,
                "generative_mask_invalid",
                "The mask could not be read.",
            ) from exc

    def _raise_if_cancelled(self, task_id: str) -> None:
        if self.repository.is_cancel_requested(task_id):
            raise _TaskCancelled

    def _ensure_generated_asset(
        self,
        result: GenerativeResultRecord,
        task: GenerativeTaskRecord,
    ) -> GeneratedAssetRecord:
        existing = self.repository.get_generated_asset_by_result(result.id)
        if existing is not None:
            return existing
        data = self.store.read(result.storage_key)
        if hashlib.sha256(data).hexdigest() != result.sha256:
            raise AppError(
                409,
                "generative_result_corrupted",
                "The stored result no longer matches its recorded hash.",
            )
        asset_id = str(uuid4())
        storage_key = self.store.save_generated(asset_id, data)
        asset = GeneratedAssetRecord(
            id=asset_id,
            image_id=task.image_id,
            task_id=task.id,
            result_id=result.id,
            storage_key=storage_key,
            sha256=result.sha256,
            width=result.width,
            height=result.height,
            bytes=result.bytes,
            mime_type=result.mime_type,
            created_at=datetime.now(UTC),
        )
        try:
            self.repository.create_generated_asset(asset)
        except DuplicateGeneratedAssetError:
            self.store.discard(storage_key)
            existing = self.repository.get_generated_asset_by_result(result.id)
            if existing is None:
                raise
            return existing
        return asset

    def _require_task(self, task_id: str, owner: OwnerScope) -> GenerativeTaskRecord:
        task = self.repository.get_task_for_owner(task_id, owner.owner_id)
        if task is None:
            raise AppError(404, "generative_task_not_found", "The task was not found.")
        return task

    def _expire(self, task: GenerativeTaskRecord) -> GenerativeTaskRecord:
        expired = self.repository.expire_if_needed(task.id, now=datetime.now(UTC))
        return expired or task

    def _created(self, task: GenerativeTaskRecord, *, deduplicated: bool) -> GenerativeTaskCreated:
        return GenerativeTaskCreated(
            task_id=UUID(task.id),
            status=task.status,
            stage=task.stage,
            deduplicated=deduplicated,
            is_mock=task.is_mock,
            provider=task.provider,
            model=task.model,
            expires_at=task.expires_at,
        )

    def _status_response(self, task: GenerativeTaskRecord) -> GenerativeTaskStatusResponse:
        results = self.repository.list_results(task.id)
        return GenerativeTaskStatusResponse(
            task_id=UUID(task.id),
            task_type=task.task_type,
            status=task.status,
            stage=task.stage,
            instruction=task.instruction,
            is_mock=task.is_mock,
            provider=task.provider,
            model=task.model,
            error=(
                None
                if task.error_code is None
                else GenerativeErrorInfo(
                    code=task.error_code,
                    message=task.error_message or "The task did not succeed.",
                )
            ),
            results=[self._result_view(result) for result in results],
            attempts=task.attempts,
            max_attempts=task.max_attempts,
            cancel_requested=task.cancel_requested,
            base_revision_id=(
                None if task.base_revision_id is None else UUID(task.base_revision_id)
            ),
            base_generated_asset_id=(
                None if task.base_generated_asset_id is None else UUID(task.base_generated_asset_id)
            ),
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            expires_at=task.expires_at,
        )

    @staticmethod
    def _result_view(result: GenerativeResultRecord) -> GenerativeResultView:
        warnings: list[str] = []
        try:
            payload: Any = json.loads(result.validation_json)
            if isinstance(payload, dict) and isinstance(payload.get("warnings"), list):
                warnings = [str(item) for item in payload["warnings"]]
        except (ValueError, TypeError):
            warnings = []
        return GenerativeResultView(
            result_id=UUID(result.id),
            result_index=result.result_index,
            status=result.status,
            width=result.width,
            height=result.height,
            image_url=f"{_RESULT_URL_PREFIX}/{result.id}/image",
            warnings=warnings,
            created_at=result.created_at,
            decided_at=result.decided_at,
        )

    @staticmethod
    def _dedupe_key(
        owner_id: str,
        session_id: str,
        image_id: str,
        base_revision_id: str,
        base_generated_asset_id: str | None,
        task_type: GenerativeTaskType,
        instruction: str,
        params: dict[str, Any],
        mask_id: str | None,
    ) -> str:
        payload = json.dumps(
            {
                "owner": owner_id,
                "session": session_id,
                "image": image_id,
                "baseRevision": base_revision_id,
                "baseAsset": base_generated_asset_id,
                "taskType": task_type.value,
                "instruction": instruction,
                "params": params,
                "mask": mask_id,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["GenerativeTaskService", "composite_protected_region"]
