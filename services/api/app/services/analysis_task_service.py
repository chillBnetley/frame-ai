from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.ai.contracts import AnalysisOptions
from app.ai.errors import ProviderBudgetExceeded, ProviderUsageUnavailable
from app.ai.factory import ProviderBundle
from app.analysis.diagnosis import DIAGNOSIS_VERSION, build_candidates
from app.analysis.features import FEATURE_SET_VERSION
from app.analysis.orchestrator import AnalysisOrchestrator, CandidateBuilder
from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.analyzer import ANALYZER_VERSION
from app.models.analysis_report import REPORT_SCHEMA_VERSION, AnalysisReport
from app.models.analysis_task import (
    AnalysisErrorInfo,
    AnalysisResultRecord,
    AnalysisTaskCreated,
    AnalysisTaskRecord,
    AnalysisTaskStatusResponse,
    TaskStage,
    TaskStatus,
)
from app.models.provider_settings import SecretKind
from app.repositories.analysis_repo import (
    DuplicateAnalysisTaskError,
    SqliteAnalysisRepository,
)
from app.repositories.provider_usage_repo import ProviderUsageRepository
from app.services.image_service import ImageService

logger = logging.getLogger("frame_ai.analysis")

ANALYSIS_NOT_FOUND = "The requested analysis was not found."
ANALYSIS_NOT_READY = "The analysis has not completed yet."
ANALYSIS_IN_PROGRESS = "The analysis is still running and cannot be deleted."
ANALYSIS_UNAVAILABLE = "The analysis result is not available."


@dataclass(frozen=True, slots=True)
class CreateOutcome:
    task: AnalysisTaskRecord
    deduplicated: bool

    def response(self) -> AnalysisTaskCreated:
        return AnalysisTaskCreated(
            analysis_id=UUID(self.task.id),
            status=self.task.status,
            stage=self.task.stage,
            deduplicated=self.deduplicated,
        )


class AnalysisTaskService:
    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        providers: ProviderBundle,
        repository: SqliteAnalysisRepository,
        *,
        candidate_builder: CandidateBuilder = build_candidates,
        usage: ProviderUsageRepository | None = None,
    ) -> None:
        self.settings = settings
        self.images = images
        self.providers = providers
        self.repository = repository
        self._candidate_builder = candidate_builder
        self.usage = usage or ProviderUsageRepository(
            settings.database_path,
            request_limit=settings.provider_daily_request_limit,
            token_limit=settings.provider_daily_token_limit,
        )
        self._lock = threading.RLock()
        self.orchestrator = self._build_orchestrator(providers)
        self._executor = ThreadPoolExecutor(
            max_workers=settings.analysis_max_concurrency,
            thread_name_prefix="frame-analysis",
        )
        self._closed = False

    def _build_orchestrator(self, providers: ProviderBundle) -> AnalysisOrchestrator:
        return AnalysisOrchestrator(
            self.settings,
            self.images,
            providers,
            self.repository,
            candidate_builder=self._candidate_builder,
        )

    def update_providers(self, providers: ProviderBundle) -> None:
        with self._lock:
            self.providers = providers
            self.orchestrator = self._build_orchestrator(providers)

    def create(
        self,
        image_id: str,
        options: AnalysisOptions,
        *,
        force: bool = False,
    ) -> CreateOutcome:
        image, _ = self.images.get_original(image_id)
        with self._lock:
            providers = self.providers
        config_key = self._config_key(options, providers)
        base_key = hashlib.sha256(f"{image.id}\n{image.sha256}\n{config_key}".encode()).hexdigest()

        if not force:
            existing = self.repository.find_by_dedupe(base_key)
            if existing is not None:
                if existing.status is not TaskStatus.FAILED:
                    return CreateOutcome(task=existing, deduplicated=True)
                # Check before re-arming: reset_for_retry would otherwise leave the
                # task pending/queued with nothing submitted when the budget rejects.
                self._precheck_budget(providers)
                retried = self.repository.reset_for_retry(existing.id)
                if retried is None:
                    # Another caller already re-armed this task; do not queue a second run.
                    return CreateOutcome(
                        task=self.repository.get(existing.id) or existing,
                        deduplicated=True,
                    )
                self._submit(retried.id)
                return CreateOutcome(task=retried, deduplicated=True)

        self._precheck_budget(providers)
        queued = self.repository.count_queued()
        if queued >= self.settings.analysis_queue_max:
            raise AppError(
                503,
                "server_busy",
                "The analysis queue is full. Try again once earlier runs finish.",
                details={"queued": queued, "queueMax": self.settings.analysis_queue_max},
                headers={"Retry-After": "5"},
            )

        now = datetime.now(UTC)
        task = AnalysisTaskRecord(
            id=str(uuid4()),
            image_id=image.id,
            image_sha256=image.sha256,
            options=options,
            config_key=config_key,
            dedupe_key=self._dedupe_key(base_key, force),
            status=TaskStatus.PENDING,
            stage=TaskStage.QUEUED,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        try:
            self.repository.create(task)
        except DuplicateAnalysisTaskError:
            existing = self.repository.find_by_dedupe(base_key)
            if existing is None:
                raise
            return CreateOutcome(task=existing, deduplicated=True)
        except sqlite3.IntegrityError as exc:
            # A non-unique constraint (foreign key, check) is a real storage fault.
            # Reporting it as a duplicate would hide the cause behind a 500.
            logger.error(
                "analysis_task_store_failed image_id=%s error_type=%s",
                image.id,
                type(exc).__name__,
            )
            raise AppError(
                500,
                "storage_error",
                "The service could not save the analysis task.",
            ) from exc

        self._submit(task.id)
        logger.info(
            "analysis_queued analysis_id=%s image_id=%s force=%s is_mock=%s",
            task.id,
            task.image_id,
            force,
            providers.is_mock,
        )
        return CreateOutcome(task=task, deduplicated=False)

    def _precheck_budget(self, providers: ProviderBundle) -> None:
        """Refuse to queue work the daily budget already makes impossible.

        This is read-only: the atomic reservation still happens per real HTTP
        attempt inside the transport, which also covers workers that start after
        recovery. Mock providers never call out, so they are not checked.
        """

        now = datetime.now(UTC)
        kinds: list[SecretKind] = []
        if not providers.vision.is_mock:
            kinds.append("vision")
        if not providers.decision.is_mock:
            kinds.append("decision")
        try:
            for kind in kinds:
                self.usage.check_available(kind, now)
        except ProviderBudgetExceeded as exc:
            raise AppError(429, exc.code, exc.message, details=exc.details) from None
        except ProviderUsageUnavailable as exc:
            raise AppError(
                503,
                "provider_usage_unavailable",
                exc.message,
            ) from None

    def status(self, task_id: str) -> AnalysisTaskStatusResponse:
        task = self._require(task_id)
        stored = (
            self.repository.get_result(task.id) if task.status is TaskStatus.COMPLETED else None
        )
        report = self._report_from(stored) if stored is not None else None
        error: AnalysisErrorInfo | None = None
        if task.status is TaskStatus.FAILED and task.error_code:
            error = AnalysisErrorInfo(
                code=task.error_code,
                message=task.error_message or "The analysis failed.",
            )
        return AnalysisTaskStatusResponse(
            analysis_id=UUID(task.id),
            status=task.status,
            stage=task.stage,
            # The persisted row records which providers actually produced this
            # report; the live bundle changes when settings are edited.
            is_mock=stored.is_mock if stored is not None else self.providers.is_mock,
            result_available=report is not None,
            error=error,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            result=report,
        )

    def result(self, task_id: str) -> AnalysisReport:
        task = self._require(task_id)
        if task.status is not TaskStatus.COMPLETED:
            raise AppError(409, "analysis_not_ready", ANALYSIS_NOT_READY)
        report = self._load_report(task.id)
        if report is None:
            raise AppError(500, "analysis_failed", ANALYSIS_UNAVAILABLE)
        return report

    def latest_completed(self, image_id: str) -> AnalysisReport | None:
        stored = self.repository.latest_completed_for_image(image_id)
        if stored is None:
            return None
        report = self._report_from(stored)
        if report is None or str(report.image.id).lower() != image_id.lower():
            return None
        return report

    def delete(self, task_id: str) -> None:
        outcome = self.repository.delete_if_not_processing(task_id)
        if outcome == "missing":
            raise AppError(404, "analysis_not_found", ANALYSIS_NOT_FOUND)
        if outcome == "processing":
            raise AppError(409, "analysis_in_progress", ANALYSIS_IN_PROGRESS)
        logger.info("analysis_deleted analysis_id=%s", task_id)

    def recover(self) -> int:
        pending = self.repository.recover_startup(self.settings.analysis_max_attempts)
        for task_id in pending:
            self._submit(task_id)
        logger.info("analysis_recovered pending=%s", len(pending))
        return len(pending)

    def shutdown(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _require(self, task_id: str) -> AnalysisTaskRecord:
        task = self.repository.get(task_id)
        if task is None:
            raise AppError(404, "analysis_not_found", ANALYSIS_NOT_FOUND)
        return task

    def _load_report(self, task_id: str) -> AnalysisReport | None:
        stored = self.repository.get_result(task_id)
        if stored is None:
            return None
        return self._report_from(stored)

    @staticmethod
    def _report_from(stored: AnalysisResultRecord) -> AnalysisReport | None:
        try:
            return AnalysisReport.model_validate_json(stored.report_json)
        except ValidationError:
            logger.error("analysis_stored_report_invalid analysis_id=%s", stored.task_id)
            return None

    def _submit(self, task_id: str) -> None:
        if self._closed:
            return
        with self._lock:
            orchestrator = self.orchestrator
        try:
            self._executor.submit(self._run, task_id, orchestrator)
        except RuntimeError:
            logger.warning("analysis_submit_rejected analysis_id=%s", task_id)

    def _run(self, task_id: str, orchestrator: AnalysisOrchestrator) -> None:
        try:
            orchestrator.run(task_id)
        except Exception as exc:
            logger.error(
                "analysis_worker_crashed analysis_id=%s error_type=%s",
                task_id,
                type(exc).__name__,
            )

    def _config_key(self, options: AnalysisOptions, providers: ProviderBundle) -> str:
        payload = {
            "visionProvider": "mock" if providers.vision.is_mock else "openai",
            "visionModel": providers.vision.model,
            "visionPromptVersion": getattr(providers.vision, "prompt_version", "mock/1"),
            "decisionProvider": "mock" if providers.decision.is_mock else "openai",
            "decisionModel": providers.decision.model,
            "decisionPromptVersion": getattr(providers.decision, "prompt_version", "mock/1"),
            "analyzerVersion": ANALYZER_VERSION,
            "featureSetVersion": FEATURE_SET_VERSION,
            "diagnosisVersion": DIAGNOSIS_VERSION,
            "reportSchemaVersion": REPORT_SCHEMA_VERSION,
            "analysisMaxEdge": self.settings.analysis_max_edge,
            "options": options.model_dump(mode="json", by_alias=True),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _dedupe_key(base_key: str, force: bool) -> str:
        if not force:
            return base_key
        return hashlib.sha256(f"{base_key}:{uuid4().hex}".encode()).hexdigest()


__all__ = [
    "ANALYSIS_NOT_FOUND",
    "ANALYSIS_NOT_READY",
    "AnalysisTaskService",
    "CreateOutcome",
]
