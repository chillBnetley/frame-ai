from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.ai.base import DecisionRequest
from app.ai.contracts import (
    AnalysisOptions,
    DecisionResult,
    ExposureQuality,
    IssueSelection,
    IssueType,
    NoiseLevel,
    Severity,
    SharpnessQuality,
    TechnicalQualityResult,
)
from app.ai.errors import ProviderError
from app.ai.factory import ProviderBundle, build_provider_bundle
from app.ai.providers.mock import MockDecisionProvider, MockVisionProvider
from app.ai.providers.openai_compatible import (
    OpenAICompatibleDecisionProvider,
    OpenAICompatibleVisionProvider,
)
from app.analysis.diagnosis import CandidateSet
from app.core.config import Settings
from app.core.errors import AppError
from app.models.analysis_task import (
    AnalysisTaskRecord,
    TaskStage,
    TaskStatus,
)
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.repositories.image_registry import ImageAssetRecord
from app.services.analysis_task_service import AnalysisTaskService
from app.services.image_service import ImageService
from tests.ai_support import (
    decision_payload,
    issue_candidate,
    json_response,
    vision_payload,
)
from tests.conftest import make_image


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "data_dir": tmp_path / "data",
        "max_upload_bytes": 1024 * 1024,
        "max_image_pixels": 1_000_000,
        "allowed_origins": "http://testserver",
        "allowed_hosts": "testserver",
        "log_level": "WARNING",
        "vision_provider": "mock",
        "decision_provider": "mock",
        "mock_scenario": "portrait",
        "analysis_max_concurrency": 1,
        "analysis_max_attempts": 2,
    }
    values.update(overrides)
    return Settings(**values)


def _register_image(images: ImageService) -> ImageAssetRecord:
    image_id = str(uuid4())
    data = make_image("PNG", (96, 64), (120, 80, 40))
    storage_key = images.store.save(image_id, ".png", data)
    record = ImageAssetRecord(
        id=image_id,
        original_name="photo.png",
        storage_key=storage_key,
        mime_type="image/png",
        width=96,
        height=64,
        exif_orientation=1,
        bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_at=datetime.now(UTC),
    )
    images.registry.add(record)
    return record


def _wait(service: AnalysisTaskService, task_id: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    status = service.status(task_id)
    while time.monotonic() < deadline:
        status = service.status(task_id)
        if status.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            return status
        time.sleep(0.05)
    raise AssertionError(f"analysis timed out with status={status.status}")


def test_mock_provider_runs_the_full_chain_and_persists_a_report(tmp_path: Path):
    settings = _settings(tmp_path)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    service = AnalysisTaskService(
        settings,
        images,
        build_provider_bundle(settings),
        repository,
    )
    try:
        outcome = service.create(image.id, AnalysisOptions())
        assert outcome.deduplicated is False
        assert outcome.task.status is TaskStatus.PENDING

        status = _wait(service, outcome.task.id)
        assert status.status is TaskStatus.COMPLETED
        assert status.result_available is True
        assert status.is_mock is True
        assert status.error is None
        report = status.result
        assert report is not None
        assert report.engine.is_mock is True
        assert report.scene.primary == "portrait"
        assert len(report.subjects) == len(report.regions) == 1
        assert report.subjects[0].region_id == report.regions[0].id
        assert report.regions[0].mask is None
        assert len(report.measurements.luminance.histogram32) == 32
        assert report.issues
        assert len(report.recommendations) == len(report.issues)
        assert report.limitations

        duplicate = service.create(image.id, AnalysisOptions())
        assert duplicate.deduplicated is True
        assert duplicate.task.id == outcome.task.id

        forced = service.create(image.id, AnalysisOptions(), force=True)
        assert forced.deduplicated is False
        assert forced.task.id != outcome.task.id

        raw = repository.get_result(outcome.task.id)
        assert raw is not None
        assert raw.schema_version == "stage3/1"
        assert raw.is_mock is True

        service.delete(outcome.task.id)
        assert repository.get(outcome.task.id) is None
        assert repository.get_result(outcome.task.id) is None
        assert images.get_original(image.id)[0].id == image.id
        try:
            service.status(outcome.task.id)
        except AppError as exc:
            assert exc.status_code == 404
            assert exc.code == "analysis_not_found"
        else:
            raise AssertionError("deleted analysis must not be readable")
    finally:
        service.shutdown()


class _FailingVision:
    name = "fake"
    model = "fake-vision"
    is_mock = True

    def analyze(self, request: object) -> object:
        raise ProviderError(
            "vision_provider_timeout",
            "The vision provider timed out.",
            retryable=True,
        )


def test_failed_task_is_reused_and_requeued_on_retry(tmp_path: Path):
    settings = _settings(tmp_path)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    providers = ProviderBundle(
        vision=_FailingVision(),  # type: ignore[arg-type]
        decision=MockDecisionProvider(),
        mock_reasons=("vision_provider=mock",),
    )
    service = AnalysisTaskService(settings, images, providers, repository)
    try:
        first = service.create(image.id, AnalysisOptions())
        failed = _wait(service, first.task.id)
        assert failed.status is TaskStatus.FAILED
        assert failed.result_available is False
        assert failed.error is not None
        assert failed.error.code == "vision_provider_timeout"
        assert repository.get_result(first.task.id) is None

        retry = service.create(image.id, AnalysisOptions())
        assert retry.deduplicated is True
        assert retry.task.id == first.task.id
        failed_again = _wait(service, first.task.id)
        assert failed_again.status is TaskStatus.FAILED
        assert failed_again.error.code == "vision_provider_timeout"  # type: ignore[union-attr]
        stored = repository.get(first.task.id)
        assert stored is not None
        assert stored.attempts == 1
    finally:
        service.shutdown()


class _UnvettedDecision:
    name = "fake"
    model = "fake-decision"
    is_mock = True

    def diagnose(self, request: DecisionRequest) -> DecisionResult:
        del request
        return DecisionResult(
            technical_quality=TechnicalQualityResult(
                exposure=ExposureQuality.UNKNOWN,
                sharpness=SharpnessQuality.UNKNOWN,
                noise=NoiseLevel.UNKNOWN,
                confidence=0.0,
            ),
            issues=(
                IssueSelection(
                    candidate_id="not-a-candidate",
                    severity=Severity.LOW,
                    confidence=0.1,
                    evidence="无依据的问题。",
                ),
            ),
            recommendations=(),
            limitations=(),
        )


def test_decision_output_outside_the_candidate_set_is_rejected(tmp_path: Path):
    settings = _settings(tmp_path)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    providers = ProviderBundle(
        vision=MockVisionProvider("portrait"),
        decision=_UnvettedDecision(),  # type: ignore[arg-type]
        mock_reasons=("decision_provider=mock",),
    )
    service = AnalysisTaskService(settings, images, providers, repository)
    try:
        outcome = service.create(image.id, AnalysisOptions())
        status = _wait(service, outcome.task.id)
        assert status.status is TaskStatus.FAILED
        assert status.error is not None
        assert status.error.code == "analysis_invalid_output"
        assert repository.get_result(outcome.task.id) is None
    finally:
        service.shutdown()


def test_time_budget_stops_a_stalled_analysis(tmp_path: Path):
    settings = _settings(tmp_path, analysis_timeout_seconds=0.0001)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    service = AnalysisTaskService(settings, images, build_provider_bundle(settings), repository)
    try:
        outcome = service.create(image.id, AnalysisOptions())
        status = _wait(service, outcome.task.id)
        assert status.status is TaskStatus.FAILED
        assert status.error is not None
        assert status.error.code == "analysis_timeout"
        assert repository.get_result(outcome.task.id) is None
    finally:
        service.shutdown()


def test_full_queue_rejects_a_new_analysis(tmp_path: Path):
    settings = _settings(tmp_path, analysis_queue_max=1)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    now = datetime.now(UTC)
    repository.create(
        AnalysisTaskRecord(
            id=str(uuid4()),
            image_id=image.id,
            image_sha256=image.sha256,
            options=AnalysisOptions(),
            config_key="config-key",
            dedupe_key=uuid4().hex,
            status=TaskStatus.PENDING,
            stage=TaskStage.QUEUED,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
    )
    service = AnalysisTaskService(settings, images, build_provider_bundle(settings), repository)
    try:
        with pytest.raises(AppError) as excinfo:
            service.create(_register_image(images).id, AnalysisOptions())

        assert excinfo.value.status_code == 503
        assert excinfo.value.code == "server_busy"
        assert excinfo.value.details == {"queued": 1, "queueMax": 1}
        assert excinfo.value.headers == {"Retry-After": "5"}
        assert repository.count_queued() == 1
    finally:
        service.shutdown()


def test_constraint_failure_on_task_insert_becomes_storage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _settings(tmp_path)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    service = AnalysisTaskService(settings, images, build_provider_bundle(settings), repository)
    # An unregistered image id breaks the foreign key, which is not a duplicate.
    ghost = image.model_copy(update={"id": str(uuid4()), "sha256": "b" * 64})
    monkeypatch.setattr(service.images, "get_original", lambda _: (ghost, Path("ghost.png")))
    try:
        with pytest.raises(AppError) as excinfo:
            service.create(ghost.id, AnalysisOptions())

        assert excinfo.value.status_code == 500
        assert excinfo.value.code == "storage_error"
    finally:
        service.shutdown()


def test_is_mock_reports_the_run_that_produced_the_report(tmp_path: Path):
    settings = _settings(tmp_path)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    service = AnalysisTaskService(settings, images, build_provider_bundle(settings), repository)
    try:
        outcome = service.create(image.id, AnalysisOptions())
        assert _wait(service, outcome.task.id).is_mock is True

        # Editing settings swaps the live bundle; the stored report keeps its origin.
        service.update_providers(
            ProviderBundle(
                vision=MockVisionProvider("portrait"),
                decision=MockDecisionProvider(),
                mock_reasons=(),
            )
        )
        status = service.status(outcome.task.id)
        assert status.is_mock is True
        assert status.result is not None
    finally:
        service.shutdown()


def test_losing_the_retry_claim_does_not_queue_a_second_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _settings(tmp_path)
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)
    repository = SqliteAnalysisRepository(settings.database_path)
    providers = ProviderBundle(
        vision=_FailingVision(),  # type: ignore[arg-type]
        decision=MockDecisionProvider(),
        mock_reasons=("vision_provider=mock",),
    )
    service = AnalysisTaskService(settings, images, providers, repository)
    try:
        first = service.create(image.id, AnalysisOptions())
        assert _wait(service, first.task.id).status is TaskStatus.FAILED

        submitted: list[str] = []
        monkeypatch.setattr(service, "_submit", submitted.append)
        monkeypatch.setattr(service.repository, "reset_for_retry", lambda _: None)

        outcome = service.create(image.id, AnalysisOptions())
        assert outcome.deduplicated is True
        assert outcome.task.id == first.task.id
        assert submitted == []
    finally:
        service.shutdown()


class _StubClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        *,
        timeout: float,
        max_retries: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout": timeout,
                "max_retries": max_retries,
            }
        )
        return self.responses.pop(0)


def test_openai_compatible_adapters_run_the_task_chain_against_a_stub(tmp_path: Path):
    settings = _settings(
        tmp_path,
        vision_provider="openai",
        decision_provider="openai",
        vision_model="vision-test-model",
        decision_model="decision-test-model",
    )
    images = ImageService(settings)
    images.ensure_ready()
    image = _register_image(images)

    decision = decision_payload(
        issues=[
            {
                "candidateId": "c1",
                "severity": "medium",
                "confidence": 0.6,
                "evidence": "暗部裁切 1.0%，低于阈值。",
                "regionIds": ["region_001"],
            }
        ],
        recommendations=[
            {
                "category": "exposure",
                "priority": "medium",
                "description": "提高曝光并检查主体暗部细节。",
                "targetRegions": ["region_001"],
            }
        ],
    )
    client = _StubClient(
        [
            json_response(vision_payload()),
            json_response(decision),
        ]
    )
    vision_provider = OpenAICompatibleVisionProvider(
        client,  # type: ignore[arg-type]
        base_url="https://example.test/v1",
        api_key="sk-test-secret-value",
        model="vision-test-model",
        timeout=5.0,
        max_retries=0,
        repair_attempts=0,
    )
    decision_provider = OpenAICompatibleDecisionProvider(
        client,  # type: ignore[arg-type]
        base_url="https://example.test/v1",
        api_key="sk-test-secret-value",
        model="decision-test-model",
        timeout=5.0,
        max_retries=0,
        repair_attempts=0,
    )
    providers = ProviderBundle(
        vision=vision_provider,
        decision=decision_provider,
        mock_reasons=(),
    )
    repository = SqliteAnalysisRepository(settings.database_path)
    service = AnalysisTaskService(
        settings,
        images,
        providers,
        repository,
        candidate_builder=lambda context: CandidateSet(
            candidates=(issue_candidate(id="c1", region_ids=("region_001",)),),
        ),
    )
    try:
        outcome = service.create(image.id, AnalysisOptions())
        status = _wait(service, outcome.task.id)
        assert status.status is TaskStatus.COMPLETED
        assert status.is_mock is False
        report = status.result
        assert report is not None
        assert report.engine.is_mock is False
        assert report.engine.vision_model == "vision-test-model"
        assert report.engine.decision_model == "decision-test-model"
        assert report.issues[0].type is IssueType.UNDEREXPOSURE
        assert report.recommendations[0].target_regions == ("region_001",)

        assert len(client.calls) == 2
        assert client.calls[0]["payload"]["model"] == "vision-test-model"
        assert client.calls[1]["payload"]["model"] == "decision-test-model"
        assert client.calls[0]["url"] == "https://example.test/v1/chat/completions"

        stored = repository.get_result(outcome.task.id)
        assert stored is not None
        assert "sk-test-secret-value" not in stored.report_json
        assert "base64" not in stored.report_json
        assert "data:image" not in stored.report_json
    finally:
        service.shutdown()
