from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.contracts import AnalysisOptions
from app.ai.errors import ProviderBudgetExceeded, ProviderUsageUnavailable
from app.ai.factory import ProviderBundle
from app.ai.transport import HttpResponse, PinnedHttpTransport
from app.api.deps import get_app_settings
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from app.models.provider_settings import ProviderSettingsUpdate
from app.photographer.service import _map_provider_error
from app.repositories.db import connect, initialize_database
from app.repositories.provider_usage_repo import ProviderUsageRepository
from app.services.provider_settings_service import ProviderSettingsService
from tests.conftest import make_image, upload

PREFIX = "/api/v1/settings/providers"


def _openai_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "data_dir": tmp_path / "data",
        "max_upload_bytes": 1024 * 1024,
        "max_image_pixels": 1_000_000,
        "allowed_origins": "http://testserver",
        "allowed_hosts": "testserver",
        "log_level": "WARNING",
        "vision_provider": "openai",
        "vision_api_key": "sk-test-vision",
        "vision_model": "vision-test",
        "vision_api_base_url": "https://example.test/v1",
        "decision_provider": "mock",
        "analysis_max_concurrency": 1,
    }
    values.update(overrides)
    return Settings(**values)


def test_usage_endpoint_zero_fills_every_kind(client: TestClient):
    response = client.get(f"{PREFIX}/usage")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requestLimit"] == 0
    assert body["tokenLimit"] == 0
    assert body["resetAt"].endswith("T00:00:00Z")
    assert body["date"] == datetime.now(UTC).date().isoformat()
    assert [entry["provider"] for entry in body["entries"]] == [
        "vision",
        "decision",
        "planner",
    ]
    for entry in body["entries"]:
        assert entry["requests"] == 0
        assert entry["tokensEstimated"] == 0
        assert entry["tokensReported"] == 0
        assert entry["updatedAt"] is None


def test_usage_endpoint_reflects_counted_attempts(client: TestClient, settings: Settings):
    repository = ProviderUsageRepository(settings.database_path)
    reservation = repository.precheck_and_reserve("decision", datetime.now(UTC))
    repository.add_tokens("decision", reservation.date, reported=12, estimated=3)

    body = client.get(f"{PREFIX}/usage").json()

    decision = next(entry for entry in body["entries"] if entry["provider"] == "decision")
    assert decision["requests"] == 1
    assert decision["tokensReported"] == 12
    assert decision["tokensEstimated"] == 3
    assert decision["updatedAt"]


def test_usage_endpoint_fails_closed_when_the_ledger_is_unreadable(
    client: TestClient,
    tmp_path: Path,
):
    broken = Settings(data_dir=tmp_path / "broken")
    (broken.data_dir / "frame.db").mkdir(parents=True)
    client.app.dependency_overrides[get_app_settings] = lambda: broken
    try:
        response = client.get(f"{PREFIX}/usage")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_usage_unavailable"


def test_enqueue_returns_429_when_todays_request_budget_is_spent(tmp_path: Path):
    settings = _openai_settings(tmp_path, provider_daily_request_limit=1)
    with TestClient(create_app(settings)) as client:
        repository = ProviderUsageRepository(
            settings.database_path,
            request_limit=1,
        )
        repository.precheck_and_reserve("vision", datetime.now(UTC))
        image = upload(client, make_image("PNG", (64, 48), (120, 80, 40)))
        assert image.status_code == 201

        response = client.post("/api/v1/analysis", json={"imageId": image.json()["imageId"]})

        assert response.status_code == 429, response.text
        error = response.json()["error"]
        assert error["code"] == "provider_budget_exceeded"
        assert error["message"] == "The daily model usage limit has been reached."
        assert set(error["details"]) == {"limit", "used", "remaining", "resetAt"}
        assert error["details"]["limit"] == 1
        assert error["details"]["used"] == 1
        assert error["details"]["remaining"] == 0
        assert error["details"]["resetAt"].endswith("T00:00:00Z")
        assert client.app.state.analysis_task_service.repository.count_queued() == 0
        [row] = repository.snapshot(datetime.now(UTC).date().isoformat())
        assert row.requests == 1


def test_enqueue_precheck_maps_a_broken_ledger_to_503(client: TestClient):
    class BrokenUsage:
        def check_available(self, provider: str, now: datetime) -> None:
            raise ProviderUsageUnavailable(
                "provider_usage_unavailable",
                "The provider usage ledger is unavailable.",
            )

    class NonMock:
        is_mock = False

    bundle = ProviderBundle(
        vision=NonMock(),  # type: ignore[arg-type]
        decision=NonMock(),  # type: ignore[arg-type]
        mock_reasons=(),
    )
    service = client.app.state.analysis_task_service
    original = service.usage
    service.usage = BrokenUsage()  # type: ignore[assignment]
    try:
        with pytest.raises(AppError) as error:
            service._precheck_budget(bundle)
    finally:
        service.usage = original

    assert error.value.status_code == 503
    assert error.value.code == "provider_usage_unavailable"


def test_settings_connection_check_counts_requests_and_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _openai_settings(
        tmp_path,
        vision_api_base_url="http://127.0.0.1:1/v1",
        provider_url_policy="allow-local",
        provider_allow_insecure_http=True,
    )
    initialize_database(settings.database_path)

    def fake_send(self, endpoint, pinned, method, body, headers, timeout):  # noqa: ANN001
        return HttpResponse(
            status=200,
            body=(
                b'{"choices":[{"message":{"content":"{\\"ok\\": true}"}}],'
                b'"usage":{"total_tokens":6}}'
            ),
        )

    monkeypatch.setattr(PinnedHttpTransport, "_send", fake_send)
    service = ProviderSettingsService(settings)

    result = service.test(ProviderSettingsUpdate())

    assert result.vision.ok is True
    [row] = ProviderUsageRepository(settings.database_path).snapshot(
        datetime.now(UTC).date().isoformat()
    )
    assert row.provider == "vision"
    assert row.requests == 1
    assert row.tokens_reported == 6


def test_budget_rejection_keeps_a_failed_retry_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _openai_settings(tmp_path, provider_daily_request_limit=1)
    with TestClient(create_app(settings)) as client:
        service = client.app.state.analysis_task_service
        repository = ProviderUsageRepository(settings.database_path, request_limit=1)
        image = upload(client, make_image("PNG", (64, 48), (120, 80, 40)))
        assert image.status_code == 201
        image_id = image.json()["imageId"]
        image_record, _ = service.images.get_original(image_id)
        with service._lock:
            providers = service.providers
        options = AnalysisOptions()
        config_key = service._config_key(options, providers)
        base_key = hashlib.sha256(
            f"{image_record.id}\n{image_record.sha256}\n{config_key}".encode()
        ).hexdigest()
        now = datetime.now(UTC)
        task = AnalysisTaskRecord(
            id=str(uuid4()),
            image_id=image_record.id,
            image_sha256=image_record.sha256,
            options=options,
            config_key=config_key,
            dedupe_key=service._dedupe_key(base_key, False),
            status=TaskStatus.FAILED,
            stage=TaskStage.FAILED,
            attempts=1,
            error_code="provider_unavailable",
            error_message="The model provider could not be reached.",
            created_at=now,
            updated_at=now,
        )
        service.repository.create(task)
        submissions: list[str] = []
        monkeypatch.setattr(service, "_submit", submissions.append)
        repository.precheck_and_reserve("vision", now)

        rejected = client.post("/api/v1/analysis", json={"imageId": image_id})

        assert rejected.status_code == 429, rejected.text
        assert rejected.json()["error"]["code"] == "provider_budget_exceeded"
        stored = service.repository.get(task.id)
        assert stored is not None
        assert stored.status is TaskStatus.FAILED
        assert stored.stage is TaskStage.FAILED
        assert stored.attempts == 1
        assert stored.error_code == "provider_unavailable"
        assert service.repository.count_queued() == 0
        assert submissions == []

        connection = connect(settings.database_path)
        try:
            connection.execute("DELETE FROM provider_usage")
        finally:
            connection.close()

        retried = client.post("/api/v1/analysis", json={"imageId": image_id})

        assert retried.status_code == 200, retried.text
        assert retried.json()["analysisId"] == task.id
        assert retried.json()["deduplicated"] is True
        assert submissions == [task.id]
        stored = service.repository.get(task.id)
        assert stored is not None
        assert stored.status is TaskStatus.PENDING
        assert stored.stage is TaskStage.QUEUED
        assert stored.attempts == 0
        assert service.repository.count_queued() == 1


def test_photographer_maps_budget_to_429_with_details():
    error = ProviderBudgetExceeded(
        "provider_budget_exceeded",
        "budget",
        retryable=False,
        details={
            "limit": 5,
            "used": 5,
            "remaining": 0,
            "resetAt": "2026-11-09T00:00:00Z",
        },
    )

    mapped = _map_provider_error(error)

    assert mapped.status_code == 429
    assert mapped.code == "photographer_budget_exceeded"
    assert mapped.details == {
        "retryable": False,
        "limit": 5,
        "used": 5,
        "remaining": 0,
        "resetAt": "2026-11-09T00:00:00Z",
    }


def test_photographer_maps_usage_unavailable_to_503():
    mapped = _map_provider_error(
        ProviderUsageUnavailable("provider_usage_unavailable", "ledger", retryable=False)
    )

    assert mapped.status_code == 503
    assert mapped.code == "photographer_usage_unavailable"
    assert mapped.details == {"retryable": False}
