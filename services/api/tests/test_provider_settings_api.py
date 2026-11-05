from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.errors import ProviderConfigurationError
from app.ai.transport import HttpResponse
from app.core.config import Settings
from app.main import create_app
from app.services.provider_settings_service import SETTINGS_FILENAME

PREFIX = "/api/v1/settings/providers"

_OPENAI_VISION = {
    "provider": "openai",
    "model": "vision-model",
    "baseUrl": "https://vision.example.test/v1/",
    "apiKey": "vision-secret-key",
}
_OPENAI_DECISION = {
    "provider": "openai",
    "model": "decision-model",
    "baseUrl": "https://decision.example.test/v1",
    "apiKey": "decision-secret-key",
}


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
        "vision_api_key": "",
        "decision_api_key": "",
        "vision_model": "",
        "decision_model": "",
        "vision_api_base_url": "",
        "decision_api_base_url": "",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _saved_path(settings: Settings) -> Path:
    return settings.data_dir / SETTINGS_FILENAME


def _write_saved(settings: Settings, payload: dict[str, Any]) -> Path:
    path = _saved_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_get_reports_mock_defaults_without_exposing_keys(client: TestClient):
    response = client.get(PREFIX)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "vision": {
            "provider": "mock",
            "model": "mock-vision",
            "baseUrl": "",
            "hasApiKey": False,
            "apiKeySource": "none",
        },
        "decision": {
            "provider": "mock",
            "model": "mock-decision",
            "baseUrl": "",
            "hasApiKey": False,
            "apiKeySource": "none",
        },
        "isMock": True,
        "hasSavedOverrides": False,
    }


def test_saving_openai_settings_masks_and_persists_keys(
    client: TestClient,
    settings: Settings,
):
    task_service = client.app.state.analysis_task_service
    orchestrator_before = task_service.orchestrator

    response = client.post(
        PREFIX,
        json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vision"] == {
        "provider": "openai",
        "model": "vision-model",
        "baseUrl": "https://vision.example.test/v1",
        "hasApiKey": True,
        "apiKeySource": "saved",
    }
    assert body["decision"]["provider"] == "openai"
    assert body["isMock"] is False
    assert body["hasSavedOverrides"] is True
    assert "vision-secret-key" not in response.text
    assert "decision-secret-key" not in response.text

    saved = json.loads(_saved_path(settings).read_text(encoding="utf-8"))
    assert saved["vision"]["api_key"] == "vision-secret-key"
    assert saved["decision"]["api_key"] == "decision-secret-key"

    settings_service = client.app.state.provider_settings_service
    assert task_service.orchestrator is not orchestrator_before
    assert task_service.providers is settings_service.bundle

    reread = client.get(PREFIX).json()
    assert reread["hasSavedOverrides"] is True
    assert reread["vision"]["hasApiKey"] is True
    assert "secret-key" not in json.dumps(reread)


def test_saved_settings_are_loaded_on_startup(settings: Settings):
    _write_saved(
        settings,
        {
            "version": 1,
            "vision": {
                "provider": "openai",
                "model": "vision-model",
                "base_url": "https://vision.example.test/v1",
                "api_key": "vision-secret-key",
            },
            "decision": None,
        },
    )

    with TestClient(create_app(settings)) as client:
        body = client.get(PREFIX).json()

    assert body["vision"]["provider"] == "openai"
    assert body["vision"]["model"] == "vision-model"
    assert body["vision"]["hasApiKey"] is True
    assert body["vision"]["apiKeySource"] == "saved"
    assert body["decision"]["provider"] == "mock"
    assert body["isMock"] is True


def test_api_key_is_preserved_when_omitted_and_removed_with_clear(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(
        PREFIX,
        json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION},
    )
    assert saved.status_code == 200, saved.text

    updated = client.post(PREFIX, json={"decision": {"model": "decision-v2"}})
    assert updated.status_code == 200, updated.text
    assert updated.json()["decision"]["model"] == "decision-v2"
    assert updated.json()["decision"]["hasApiKey"] is True
    assert updated.json()["vision"]["hasApiKey"] is True

    stored = json.loads(_saved_path(settings).read_text(encoding="utf-8"))
    assert stored["vision"]["api_key"] == "vision-secret-key"
    assert stored["decision"]["api_key"] == "decision-secret-key"

    cleared = client.post(
        PREFIX,
        json={"vision": {"provider": "mock", "clearApiKey": True}},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["vision"]["provider"] == "mock"
    assert cleared.json()["vision"]["hasApiKey"] is False
    assert cleared.json()["vision"]["apiKeySource"] == "none"
    assert cleared.json()["decision"]["hasApiKey"] is True
    assert cleared.json()["isMock"] is True


def test_invalid_settings_return_422_and_keep_previous_config(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(
        PREFIX,
        json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION},
    )
    assert saved.status_code == 200, saved.text
    before = _saved_path(settings).read_text(encoding="utf-8")

    invalid_url = client.post(
        PREFIX,
        json={"vision": {"baseUrl": "ftp://files.example.test"}},
    )
    assert invalid_url.status_code == 422, invalid_url.text
    error = invalid_url.json()["error"]
    assert error["code"] == "invalid_provider_settings"
    fields = error["details"]["fields"]
    assert [entry["field"] for entry in fields] == ["vision.baseUrl"]
    assert fields[0]["rule"] == "invalid_url"
    assert _saved_path(settings).read_text(encoding="utf-8") == before

    missing_key = client.post(PREFIX, json={"decision": {"clearApiKey": True}})
    assert missing_key.status_code == 422, missing_key.text
    missing = missing_key.json()["error"]["details"]["fields"]
    assert [entry["field"] for entry in missing] == ["decision.apiKey"]
    assert missing[0]["rule"] == "missing"
    assert _saved_path(settings).read_text(encoding="utf-8") == before

    current = client.get(PREFIX).json()
    assert current["decision"]["hasApiKey"] is True
    assert current["vision"]["baseUrl"] == "https://vision.example.test/v1"


def test_conflicting_key_actions_are_rejected(client: TestClient):
    response = client.post(
        PREFIX,
        json={
            "vision": {
                "provider": "openai",
                "model": "vision-model",
                "baseUrl": "https://vision.example.test/v1",
                "apiKey": "new-key",
                "clearApiKey": True,
            }
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_reset_removes_saved_overrides(client: TestClient, settings: Settings):
    saved = client.post(
        PREFIX,
        json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION},
    )
    assert saved.status_code == 200, saved.text
    assert _saved_path(settings).exists()

    response = client.post(f"{PREFIX}/reset")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hasSavedOverrides"] is False
    assert body["isMock"] is True
    assert body["vision"]["provider"] == "mock"
    assert body["vision"]["hasApiKey"] is False
    assert not _saved_path(settings).exists()
    assert client.get(PREFIX).json()["hasSavedOverrides"] is False


def test_test_endpoint_reports_mock_providers_without_network(client: TestClient):
    response = client.post(f"{PREFIX}/test", json={})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "vision": {
            "ok": True,
            "provider": "mock",
            "model": "mock-vision",
            "latencyMs": 0,
            "code": None,
            "message": None,
        },
        "decision": {
            "ok": True,
            "provider": "mock",
            "model": "mock-decision",
            "latencyMs": 0,
            "code": None,
            "message": None,
        },
    }


def test_test_endpoint_sends_text_only_requests_and_reports_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[dict[str, Any]] = []

    def fake_post(
        self: Any,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        calls.append(
            {
                "url": url,
                "body": json.loads(body),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        payload = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(
        "app.ai.transport.UrllibJsonTransport.post",
        fake_post,
    )

    response = client.post(
        f"{PREFIX}/test",
        json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vision"]["ok"] is True
    assert body["decision"]["ok"] is True
    assert body["vision"]["provider"] == "openai"
    assert body["vision"]["model"] == "vision-model"
    assert body["vision"]["latencyMs"] >= 0

    assert len(calls) == 2
    for call in calls:
        assert call["url"].endswith("/chat/completions")
        assert call["headers"]["Authorization"].startswith("Bearer ")
        assert call["body"]["response_format"] == {"type": "json_object"}
        assert call["timeout"] <= 20.0
        serialized = json.dumps(call["body"])
        assert "base64" not in serialized
        assert "data:image" not in serialized


def test_test_endpoint_reports_provider_failures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_post(
        self: Any,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        return HttpResponse(
            status=401,
            body=b'{"error": {"message": "invalid credentials"}}',
        )

    monkeypatch.setattr(
        "app.ai.transport.UrllibJsonTransport.post",
        fake_post,
    )

    response = client.post(
        f"{PREFIX}/test",
        json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vision"]["ok"] is False
    assert body["decision"]["ok"] is False
    assert "auth" in body["vision"]["code"]
    assert body["vision"]["message"]
    assert "secret-key" not in response.text


def test_test_endpoint_does_not_persist_candidate_settings(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_post(
        self: Any,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        payload = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(
        "app.ai.transport.UrllibJsonTransport.post",
        fake_post,
    )

    response = client.post(f"{PREFIX}/test", json={"vision": _OPENAI_VISION})
    assert response.status_code == 200, response.text
    assert not _saved_path(settings).exists()
    assert client.get(PREFIX).json()["vision"]["provider"] == "mock"


def test_corrupt_saved_settings_fail_startup_clearly(settings: Settings):
    path = _saved_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ProviderConfigurationError):
        with TestClient(create_app(settings)):
            pass


def test_incomplete_saved_openai_settings_fail_startup(settings: Settings):
    _write_saved(
        settings,
        {
            "version": 1,
            "vision": {
                "provider": "openai",
                "model": "vision-model",
                "base_url": "https://vision.example.test/v1",
            },
        },
    )

    with pytest.raises(ProviderConfigurationError):
        with TestClient(create_app(settings)):
            pass
