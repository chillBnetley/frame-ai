from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.ai.generative import (
    GeneratedImage,
    GenerativeCapabilities,
    GenerativeProviderJob,
    GenerativeRequest,
)
from app.ai.generative import (
    validate_spec as validate_capability_spec,
)
from app.ai.providers.generative_mock import MockGenerativeProvider
from app.core.config import Settings
from app.core.errors import AppError
from app.core.identity import OwnerScope
from app.imaging.loader import load_image
from app.imaging.output import to_uint8
from app.imaging.pipeline import render as render_image
from app.models.generative import (
    GenerativeBaseMode,
    GenerativeMaskKind,
    GenerativeMaskRecord,
    GenerativeMaskSource,
    GenerativeTaskRecord,
    GenerativeTaskRequest,
    GenerativeTaskStage,
    GenerativeTaskStatus,
    GenerativeTaskType,
)
from app.models.recipe import EditRecipe, recipe_hash
from app.services.generative_service import GenerativeTaskService
from tests.conftest import make_image, upload

OWNER = OwnerScope("local")
TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


def _new_session(client: TestClient) -> dict[str, object]:
    response = upload(client, make_image())
    assert response.status_code == 201, response.text
    image_id = str(response.json()["imageId"])
    created = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert created.status_code == 201, created.text
    session = created.json()
    session["imageId"] = image_id
    mask = client.post(
        "/api/v1/generative/masks",
        json={
            "sessionId": session["sessionId"],
            "kind": "rect",
            "definition": {
                "region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            },
        },
    )
    assert mask.status_code == 201, mask.text
    session["maskId"] = mask.json()["maskId"]
    return session


def _make_service(
    client: TestClient,
    settings: Settings,
    provider,
    *,
    max_workers: int = 1,
) -> GenerativeTaskService:
    base = client.app.state.generative_service
    return GenerativeTaskService(
        settings,
        base.sessions,
        provider,
        base.repository,
        base.store,
        base.assets,
        executor=ThreadPoolExecutor(max_workers=max_workers),
    )


def _create(
    service: GenerativeTaskService,
    session: dict[str, object],
    *,
    instruction: str = "service test",
    mask_id: UUID | None = None,
    base_mode: GenerativeBaseMode = GenerativeBaseMode.BASE,
) -> str:
    created, _ = service.create(
        GenerativeTaskRequest(
            session_id=UUID(str(session["sessionId"])),
            task_type=GenerativeTaskType.LOCAL_EDIT,
            instruction=instruction,
            mask_id=mask_id or UUID(str(session["maskId"])),
            base_mode=base_mode,
        ),
        owner=OWNER,
        idempotency_key=None,
    )
    return str(created.task_id)


def _commit_recipe(
    client: TestClient,
    session: dict[str, object],
    recipe: dict[str, object],
) -> EditRecipe:
    response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/revisions",
        json={"recipe": recipe, "parentRevisionId": session["activeRevisionId"]},
    )
    assert response.status_code == 201, response.text
    state = client.get(f"/api/v1/sessions/{session['sessionId']}")
    assert state.status_code == 200, state.text
    return EditRecipe.model_validate(state.json()["revision"]["recipe"])


def _flattened_pixels(settings: Settings, image_id: str, recipe: EditRecipe) -> np.ndarray:
    path = settings.data_dir / _original_key(settings, image_id)
    image = load_image(path, preserve_alpha=False)
    rendered = render_image(
        image,
        recipe.adjustments,
        image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        curve=recipe.curve,
        hsl=recipe.hsl,
        color_grading=recipe.color_grading,
        masks=recipe.masks,
        local_adjustments=recipe.local_adjustments,
        quality="export",
    )
    rgb = np.asarray(rendered.rgb)
    return rgb if rgb.dtype == np.uint8 else to_uint8(rgb)


def _wait(service: GenerativeTaskService, task_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.status(task_id, owner=OWNER)
        if status.status.value in TERMINAL:
            return status
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish")


class _ProviderBase:
    name = "fake"
    model = "fake-1"
    is_mock = True
    prompt_version = "fake/1"

    def capabilities(self) -> GenerativeCapabilities:
        return GenerativeCapabilities(
            supported_task_types=(GenerativeTaskType.LOCAL_EDIT,),
            supports_mask=True,
            supports_multiple_outputs=False,
            supports_async=True,
            supports_cancel=True,
            max_output_pixels=1_000_000,
            max_long_edge=4096,
            allowed_output_formats=("png",),
            declared_retention="local test provider",
        )

    def cancel(self, job: GenerativeProviderJob) -> None:
        return None

    def validate_spec(self, spec) -> None:
        validate_capability_spec(self.capabilities(), spec)

    def validate_request(self, request) -> None:
        return None

    def check_connection(self, *, timeout: float | None = None) -> int:
        return 0


class FailingProvider(_ProviderBase):
    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        return GenerativeProviderJob(
            provider_job_id="fail",
            status="failed",
            error_code="provider_error",
            error_message="The provider rejected the request.",
        )

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        return job

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        raise AssertionError("fetch must not run for a failed job")


class FlakyProvider(_ProviderBase):
    def __init__(self) -> None:
        self._mock = MockGenerativeProvider()
        self.fail_next = True
        self._lock = threading.Lock()

    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        with self._lock:
            fail = self.fail_next
            self.fail_next = False
        if fail:
            return GenerativeProviderJob(
                provider_job_id="fail",
                status="failed",
                error_code="provider_error",
                error_message="The first attempt fails.",
            )
        return self._mock.submit(request)

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        return job

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        return self._mock.fetch(job)


class SlowProvider(_ProviderBase):
    def __init__(self) -> None:
        self._mock = MockGenerativeProvider()
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = False
        self._requests: dict[str, GenerativeRequest] = {}

    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        job_id = f"slow-{request.task_id}"
        self._requests[job_id] = request
        self.started.set()
        return GenerativeProviderJob(provider_job_id=job_id, status="processing")

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        assert job.provider_job_id is not None
        self.release.wait(10)
        request = self._requests.pop(job.provider_job_id)
        return self._mock.submit(request)

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        return self._mock.fetch(job)

    def cancel(self, job: GenerativeProviderJob) -> None:
        self.cancelled = True
        self.release.set()


class BadSizeProvider(_ProviderBase):
    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        data = make_image(size=(10, 12))
        return GenerativeProviderJob(
            provider_job_id="bad-size",
            status="succeeded",
            result=GeneratedImage(data=data, mime_type="image/png", width=10, height=12),
        )

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        return job

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        assert job.result is not None
        return job.result


class BlankProvider(_ProviderBase):
    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        width = request.image.width
        height = request.image.height
        buffer = BytesIO()
        Image.new("RGB", (width, height), (20, 20, 20)).save(buffer, format="PNG")
        return GenerativeProviderJob(
            provider_job_id="blank",
            status="succeeded",
            result=GeneratedImage(
                data=buffer.getvalue(),
                mime_type="image/png",
                width=width,
                height=height,
            ),
        )

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        return job

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        assert job.result is not None
        return job.result


class IdentityProvider(_ProviderBase):
    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        return GenerativeProviderJob(
            provider_job_id="identity",
            status="succeeded",
            result=GeneratedImage(
                data=request.image.data,
                mime_type="image/png",
                width=request.image.width,
                height=request.image.height,
            ),
        )

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        return job

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        assert job.result is not None
        return job.result


class TinyLimitProvider(_ProviderBase):
    def capabilities(self) -> GenerativeCapabilities:
        return replace(super().capabilities(), max_output_pixels=100)


def test_provider_failure_marks_the_task_failed(client: TestClient, settings: Settings):
    service = _make_service(client, settings, FailingProvider())
    try:
        task_id = _create(service, _new_session(client))
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.FAILED
        assert status.error is not None
        assert status.error.code == "provider_error"
        assert service.retry(task_id, owner=OWNER)  # a failed task is retryable
        second = _wait(service, task_id)
        assert second.status is GenerativeTaskStatus.FAILED
    finally:
        service.shutdown()


def test_failed_task_can_be_retried_successfully(client: TestClient, settings: Settings):
    provider = FlakyProvider()
    service = _make_service(client, settings, provider)
    try:
        task_id = _create(service, _new_session(client))
        failed = _wait(service, task_id)
        assert failed.status is GenerativeTaskStatus.FAILED
        assert failed.attempts == 1

        retried = service.retry(task_id, owner=OWNER)
        assert retried.status is GenerativeTaskStatus.QUEUED
        succeeded = _wait(service, task_id)
        assert succeeded.status is GenerativeTaskStatus.SUCCEEDED
        assert succeeded.attempts == 2
        assert len(succeeded.results) == 1
        with pytest.raises(AppError) as excinfo:
            service.retry(task_id, owner=OWNER)
        assert excinfo.value.code == "generative_retry_not_allowed"
    finally:
        service.shutdown()


def test_queued_task_can_be_cancelled_while_another_runs(
    client: TestClient,
    settings: Settings,
):
    provider = SlowProvider()
    service = _make_service(client, settings, provider)
    session = _new_session(client)
    try:
        first = _create(service, session, instruction="first")
        assert provider.started.wait(5)
        second = _create(service, session, instruction="second")

        cancelled = service.cancel(second, owner=OWNER)
        assert cancelled.status is GenerativeTaskStatus.CANCELLED

        provider.release.set()
        finished = _wait(service, first)
        assert finished.status is GenerativeTaskStatus.SUCCEEDED
    finally:
        provider.release.set()
        service.shutdown()


def test_invalid_output_size_fails_the_task(client: TestClient, settings: Settings):
    service = _make_service(client, settings, BadSizeProvider())
    try:
        task_id = _create(service, _new_session(client))
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.FAILED
        assert status.error is not None
        assert status.error.code == "generative_invalid_output_size"
    finally:
        service.shutdown()


def test_blank_output_fails_the_task(client: TestClient, settings: Settings):
    service = _make_service(client, settings, BlankProvider())
    try:
        task_id = _create(service, _new_session(client))
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.FAILED
        assert status.error is not None
        assert status.error.code == "generative_blank_output"
    finally:
        service.shutdown()


def test_unchanged_output_fails_the_task(client: TestClient, settings: Settings):
    service = _make_service(client, settings, IdentityProvider())
    try:
        task_id = _create(service, _new_session(client))
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.FAILED
        assert status.error is not None
        assert status.error.code == "generative_no_visible_change"
    finally:
        service.shutdown()


def test_oversized_input_is_rejected_before_queueing(
    client: TestClient,
    settings: Settings,
):
    service = _make_service(client, settings, TinyLimitProvider())
    try:
        with pytest.raises(AppError) as excinfo:
            _create(service, _new_session(client))
        assert excinfo.value.status_code == 413
        assert excinfo.value.code == "generative_input_too_large"
    finally:
        service.shutdown()


def test_mask_protects_pixels_outside_the_region(client: TestClient, settings: Settings):
    session = _new_session(client)
    image_id = str(session["imageId"])
    mask_id = str(uuid4())
    mask_array = np.zeros((48, 64), dtype=np.uint8)
    mask_array[:, 32:] = 255
    mask_path = settings.data_dir / "masks" / f"{mask_id}.png"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask_array, mode="L").save(mask_path, format="PNG")
    base = client.app.state.generative_service
    base.repository.create_mask(
        GenerativeMaskRecord(
            id=mask_id,
            owner_id="local",
            image_id=image_id,
            kind=GenerativeMaskKind.BRUSH,
            source=GenerativeMaskSource.USER,
            width=64,
            height=48,
            storage_key=f"masks/{mask_id}.png",
            sha256=hashlib.sha256(mask_array.tobytes()).hexdigest(),
            strokes_json="[]",
            created_at=datetime.now(UTC),
        )
    )

    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        task_id = _create(service, session, mask_id=UUID(mask_id))
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.SUCCEEDED
        result = status.results[0]
        assert "protected_region_restored" in result.warnings

        result_row = base.repository.get_result(str(result.result_id))
        assert result_row is not None
        result_pixels = np.asarray(
            Image.open(settings.data_dir / result_row.storage_key).convert("RGB")
        )
        source_pixels = np.asarray(
            Image.open(settings.data_dir / _original_key(settings, image_id)).convert("RGB")
        )
        assert np.array_equal(result_pixels[:, :32], source_pixels[:, :32])
    finally:
        service.shutdown()


def test_recovery_marks_processing_tasks_and_requeues_queued_ones(
    client: TestClient,
    settings: Settings,
):
    session = _new_session(client)
    image_id = str(session["imageId"])
    base = client.app.state.generative_service
    now = datetime.now(UTC)

    def record(task_id: str, status: GenerativeTaskStatus, stage: GenerativeTaskStage):
        return GenerativeTaskRecord(
            id=task_id,
            owner_id="local",
            image_id=image_id,
            session_id=str(session["sessionId"]),
            base_revision_id=str(session["activeRevisionId"]),
            task_type=GenerativeTaskType.LOCAL_EDIT,
            instruction="recover",
            mask_id=str(session["maskId"]),
            plan_json="{}",
            params_json='{"candidates":1}',
            provider="fake",
            model="fake-1",
            prompt_version="fake/1",
            is_mock=True,
            status=status,
            stage=stage,
            attempts=1,
            max_attempts=2,
            dedupe_key=uuid4().hex,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=1),
        )

    interrupted = str(uuid4())
    queued = str(uuid4())
    base.repository.create_task(
        record(interrupted, GenerativeTaskStatus.PROCESSING, GenerativeTaskStage.GENERATING)
    )
    base.repository.create_task(
        record(queued, GenerativeTaskStatus.QUEUED, GenerativeTaskStage.QUEUED)
    )

    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        recovered = service.recover()
        assert recovered == 1
        failed = service.status(interrupted, owner=OWNER)
        assert failed.status is GenerativeTaskStatus.FAILED
        assert failed.error is not None
        assert failed.error.code == "service_restarted"
        succeeded = _wait(service, queued)
        assert succeeded.status is GenerativeTaskStatus.SUCCEEDED
    finally:
        service.shutdown()


def test_queued_task_expires_on_status_read(client: TestClient, settings: Settings):
    session = _new_session(client)
    base = client.app.state.generative_service
    now = datetime.now(UTC)
    task_id = str(uuid4())
    base.repository.create_task(
        GenerativeTaskRecord(
            id=task_id,
            owner_id="local",
            image_id=str(session["imageId"]),
            session_id=str(session["sessionId"]),
            base_revision_id=str(session["activeRevisionId"]),
            task_type=GenerativeTaskType.LOCAL_EDIT,
            instruction="expire",
            plan_json="{}",
            params_json='{"candidates":1}',
            provider="fake",
            model="fake-1",
            prompt_version="fake/1",
            is_mock=True,
            status=GenerativeTaskStatus.QUEUED,
            stage=GenerativeTaskStage.QUEUED,
            dedupe_key=uuid4().hex,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    )
    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        status = service.status(task_id, owner=OWNER)
        assert status.status is GenerativeTaskStatus.EXPIRED
        assert status.error is not None
        assert status.error.code == "expired"
    finally:
        service.shutdown()


def test_expired_candidate_results_are_purged(client: TestClient, settings: Settings):
    session = _new_session(client)
    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        task_id = _create(service, session)
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.SUCCEEDED
        result = status.results[0]
        row = service.repository.get_result(str(result.result_id))
        assert row is not None
        path = settings.data_dir / row.storage_key
        assert path.is_file()

        from app.repositories.db import connect

        connection = connect(settings.database_path)
        try:
            connection.execute(
                "UPDATE generative_result SET created_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
                (str(result.result_id),),
            )
        finally:
            connection.close()

        purged = service.cleanup_expired_results()
        assert purged == 1
        assert not path.exists()
        assert service.repository.get_result(str(result.result_id)) is None
    finally:
        service.shutdown()


def test_delete_refuses_while_a_generative_task_is_active(
    client: TestClient,
    settings: Settings,
):
    session = _new_session(client)
    base = client.app.state.generative_service
    now = datetime.now(UTC)
    base.repository.create_task(
        GenerativeTaskRecord(
            id=str(uuid4()),
            owner_id="local",
            image_id=str(session["imageId"]),
            session_id=str(session["sessionId"]),
            base_revision_id=str(session["activeRevisionId"]),
            task_type=GenerativeTaskType.LOCAL_EDIT,
            instruction="busy",
            plan_json="{}",
            params_json='{"candidates":1}',
            provider="fake",
            model="fake-1",
            prompt_version="fake/1",
            is_mock=True,
            status=GenerativeTaskStatus.QUEUED,
            stage=GenerativeTaskStage.QUEUED,
            dedupe_key=uuid4().hex,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )

    image_delete = client.delete(f"/api/v1/images/{session['imageId']}")
    assert image_delete.status_code == 409
    assert image_delete.json()["error"]["code"] == "resource_busy"
    assert "generative" in image_delete.json()["error"]["details"]["reasons"]

    session_delete = client.delete(f"/api/v1/sessions/{session['sessionId']}")
    assert session_delete.status_code == 409
    assert session_delete.json()["error"]["code"] == "resource_busy"


def _original_key(settings: Settings, image_id: str) -> str:
    from app.repositories.db import connect

    connection = connect(settings.database_path)
    try:
        row = connection.execute(
            "SELECT storage_key FROM image_asset WHERE id = ?",
            (image_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row["storage_key"])


def _protected_comparison(
    settings: Settings,
    base: GenerativeTaskService,
    session: dict[str, object],
    status,
) -> tuple[np.ndarray, np.ndarray]:
    mask_record = base.repository.get_mask(str(session["maskId"]))
    assert mask_record is not None
    mask = np.asarray(Image.open(settings.data_dir / mask_record.storage_key).convert("L"))
    result_row = base.repository.get_result(str(status.results[0].result_id))
    assert result_row is not None
    result_pixels = np.asarray(
        Image.open(settings.data_dir / result_row.storage_key).convert("RGB")
    )
    protected = mask == 0
    return result_pixels[protected], protected


def test_graded_base_protects_the_flattened_pixels_not_the_original(
    client: TestClient, settings: Settings
):
    session = _new_session(client)
    image_id = str(session["imageId"])
    recipe = _commit_recipe(client, session, {"adjustments": {"exposureEv": 1.0}})
    original_path = settings.data_dir / _original_key(settings, image_id)
    original_bytes = original_path.read_bytes()
    original_pixels = np.asarray(Image.open(original_path).convert("RGB"))
    flattened = _flattened_pixels(settings, image_id, recipe)
    assert not np.array_equal(flattened, original_pixels)

    base = client.app.state.generative_service
    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        task_id = _create(service, session, base_mode=GenerativeBaseMode.GRADED)
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.SUCCEEDED
        assert status.base_mode is GenerativeBaseMode.GRADED
        assert status.input_sha256 is not None

        task = base.repository.get_task(task_id)
        assert task is not None
        assert task.base_mode is GenerativeBaseMode.GRADED
        assert task.input_recipe_hash == recipe_hash(recipe)
        assert task.input_sha256 == status.input_sha256

        result_pixels, protected = _protected_comparison(settings, base, session, status)
        assert np.array_equal(result_pixels, flattened[protected])
        assert not np.array_equal(result_pixels, original_pixels[protected])
        assert original_path.read_bytes() == original_bytes
    finally:
        service.shutdown()


def test_base_mode_default_keeps_the_ungraded_asset_as_the_guarantee(
    client: TestClient, settings: Settings
):
    session = _new_session(client)
    image_id = str(session["imageId"])
    recipe = _commit_recipe(client, session, {"adjustments": {"exposureEv": 1.0}})
    original_pixels = np.asarray(
        Image.open(settings.data_dir / _original_key(settings, image_id)).convert("RGB")
    )
    flattened = _flattened_pixels(settings, image_id, recipe)

    base = client.app.state.generative_service
    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        task_id = _create(service, session)
        status = _wait(service, task_id)
        assert status.status is GenerativeTaskStatus.SUCCEEDED
        assert status.base_mode is GenerativeBaseMode.BASE
        assert status.input_sha256 is not None

        task = base.repository.get_task(task_id)
        assert task is not None
        assert task.input_recipe_hash is None

        result_pixels, protected = _protected_comparison(settings, base, session, status)
        assert np.array_equal(result_pixels, original_pixels[protected])
        assert not np.array_equal(result_pixels, flattened[protected])
    finally:
        service.shutdown()


@pytest.mark.parametrize(
    "recipe",
    [
        {"adjustments": {"exposureEv": 0.5, "crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}}},
        {"adjustments": {"exposureEv": 0.5, "rotationDeg": 5.0}},
    ],
)
def test_graded_base_rejects_a_recipe_that_moves_pixels(
    client: TestClient, settings: Settings, recipe: dict[str, object]
):
    session = _new_session(client)
    _commit_recipe(client, session, recipe)
    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        with pytest.raises(AppError) as excinfo:
            _create(service, session, base_mode=GenerativeBaseMode.GRADED)
        assert excinfo.value.status_code == 422
        assert excinfo.value.code == "generative_base_geometry_unsupported"
    finally:
        service.shutdown()


def test_base_mode_is_part_of_the_dedupe_key(client: TestClient, settings: Settings):
    session = _new_session(client)
    _commit_recipe(client, session, {"adjustments": {"exposureEv": 1.0}})
    service = _make_service(client, settings, MockGenerativeProvider())
    try:
        request = GenerativeTaskRequest(
            session_id=UUID(str(session["sessionId"])),
            task_type=GenerativeTaskType.LOCAL_EDIT,
            instruction="service test",
            mask_id=UUID(str(session["maskId"])),
        )
        first, first_deduped = service.create(request, owner=OWNER, idempotency_key=None)
        again, again_deduped = service.create(request, owner=OWNER, idempotency_key=None)
        graded, graded_deduped = service.create(
            request.model_copy(update={"base_mode": GenerativeBaseMode.GRADED}),
            owner=OWNER,
            idempotency_key=None,
        )
        assert not first_deduped
        assert again_deduped
        assert again.task_id == first.task_id
        assert not graded_deduped
        assert graded.task_id != first.task_id
    finally:
        service.shutdown()
