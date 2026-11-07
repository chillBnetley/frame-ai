from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.errors import ProviderConfigurationError
from app.ai.providers.mock import MockPlannerProvider
from app.ai.providers.openai_compatible import OpenAICompatiblePlannerProvider
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
_OPENAI_PLANNER = {
    "provider": "openai",
    "model": "planner-model",
    "baseUrl": "https://planner.example.test/v1",
    "apiKey": "planner-secret-key",
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
        "planner": {
            "provider": "mock",
            "model": "mock-planner",
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
    assert body["planner"] == {
        "provider": "openai",
        "model": "decision-model",
        "baseUrl": "https://decision.example.test/v1",
        "hasApiKey": True,
        "apiKeySource": "saved",
    }
    assert body["isMock"] is False
    assert body["hasSavedOverrides"] is True
    assert "vision-secret-key" not in response.text
    assert "decision-secret-key" not in response.text

    saved = json.loads(_saved_path(settings).read_text(encoding="utf-8"))
    assert saved["vision"]["api_key"] == "vision-secret-key"
    assert saved["decision"]["api_key"] == "decision-secret-key"
    assert "planner" not in saved

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
    assert body["planner"]["provider"] == "mock"
    assert body["planner"]["model"] == "mock-planner"
    assert body["isMock"] is True


def test_saved_settings_without_a_planner_group_follow_decision(
    settings: Settings,
):
    _write_saved(
        settings,
        {
            "version": 1,
            "vision": None,
            "decision": {
                "provider": "openai",
                "model": "decision-model",
                "base_url": "https://decision.example.test/v1",
                "api_key": "decision-secret-key",
            },
        },
    )

    with TestClient(create_app(settings)) as client:
        body = client.get(PREFIX).json()

    assert body["planner"] == {
        "provider": "openai",
        "model": "decision-model",
        "baseUrl": "https://decision.example.test/v1",
        "hasApiKey": True,
        "apiKeySource": "saved",
    }
    assert body["hasSavedOverrides"] is True


def test_planner_model_override_keeps_the_other_decision_fields(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(PREFIX, json={"decision": _OPENAI_DECISION})
    assert saved.status_code == 200, saved.text

    response = client.post(PREFIX, json={"planner": {"model": "planner-model"}})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["planner"] == {
        "provider": "openai",
        "model": "planner-model",
        "baseUrl": "https://decision.example.test/v1",
        "hasApiKey": True,
        "apiKeySource": "saved",
    }
    stored = json.loads(_saved_path(settings).read_text(encoding="utf-8"))
    assert stored["planner"] == {"model": "planner-model"}

    planner = client.app.state.photographer_service.planner
    assert isinstance(planner, OpenAICompatiblePlannerProvider)
    assert planner.model == "planner-model"


def test_explicit_planner_mock_is_not_replaced_by_the_decision_provider(
    client: TestClient,
):
    response = client.post(
        PREFIX,
        json={"decision": _OPENAI_DECISION, "planner": {"provider": "mock"}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["provider"] == "openai"
    assert body["planner"] == {
        "provider": "mock",
        "model": "mock-planner",
        "baseUrl": "https://decision.example.test/v1",
        "hasApiKey": True,
        "apiKeySource": "saved",
    }
    planner = client.app.state.photographer_service.planner
    assert isinstance(planner, MockPlannerProvider)


def test_empty_planner_strings_fall_back_to_the_saved_decision_fields(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(PREFIX, json={"decision": _OPENAI_DECISION})
    assert saved.status_code == 200, saved.text

    response = client.post(
        PREFIX,
        json={"planner": {"model": "", "baseUrl": ""}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["planner"]["model"] == "decision-model"
    assert body["planner"]["baseUrl"] == "https://decision.example.test/v1"
    stored = json.loads(_saved_path(settings).read_text(encoding="utf-8"))
    assert stored["planner"] == {"model": "", "base_url": ""}


def test_reset_removes_the_planner_group(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(
        PREFIX,
        json={"decision": _OPENAI_DECISION, "planner": _OPENAI_PLANNER},
    )
    assert saved.status_code == 200, saved.text

    response = client.post(f"{PREFIX}/reset")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["planner"] == {
        "provider": "mock",
        "model": "mock-planner",
        "baseUrl": "",
        "hasApiKey": False,
        "apiKeySource": "none",
    }
    assert body["hasSavedOverrides"] is False
    assert not _saved_path(settings).exists()
    assert isinstance(client.app.state.photographer_service.planner, MockPlannerProvider)


def test_incomplete_planner_openai_settings_report_planner_fields(client: TestClient):
    response = client.post(
        PREFIX,
        json={
            "planner": {
                "provider": "openai",
                "model": "planner-model",
                "baseUrl": "https://planner.example.test/v1",
            }
        },
    )

    assert response.status_code == 422, response.text
    fields = response.json()["error"]["details"]["fields"]
    assert [entry["field"] for entry in fields] == ["planner.apiKey"]
    assert fields[0]["rule"] == "missing"


def test_test_endpoint_checks_an_independent_planner_provider(
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
        calls.append({"url": url, "headers": dict(headers)})
        payload = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("app.ai.transport.PinnedHttpTransport.post", fake_post)

    response = client.post(f"{PREFIX}/test", json={"planner": _OPENAI_PLANNER})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vision"]["provider"] == "mock"
    assert body["decision"]["provider"] == "mock"
    assert body["planner"]["provider"] == "openai"
    assert body["planner"]["model"] == "planner-model"
    assert body["planner"]["ok"] is True
    assert len(calls) == 1
    assert calls[0]["url"].startswith("https://planner.example.test/v1")
    assert calls[0]["headers"]["Authorization"] == "Bearer planner-secret-key"


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
    assert [entry["field"] for entry in missing] == ["decision.apiKey", "planner.apiKey"]
    assert all(entry["rule"] == "missing" for entry in missing)
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
        "planner": {
            "ok": True,
            "provider": "mock",
            "model": "mock-planner",
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
        "app.ai.transport.PinnedHttpTransport.post",
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
    assert body["planner"]["ok"] is True
    assert body["vision"]["provider"] == "openai"
    assert body["vision"]["model"] == "vision-model"
    assert body["vision"]["latencyMs"] >= 0
    assert body["planner"]["provider"] == "openai"
    assert body["planner"]["model"] == "decision-model"

    assert len(calls) == 3
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
        "app.ai.transport.PinnedHttpTransport.post",
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
    assert body["planner"]["ok"] is False
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
        "app.ai.transport.PinnedHttpTransport.post",
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


def _local_openai(
    base_url: str = "http://127.0.0.1:11434/v1",
    api_key: str = "local-secret-key",
) -> dict[str, Any]:
    return {
        "provider": "openai",
        "model": "local-model",
        "baseUrl": base_url,
        "apiKey": api_key,
    }


@pytest.mark.parametrize(
    "base_url",
    [
        "https://10.0.0.5/v1",
        "http://127.0.0.1:11434/v1",
        "https://169.254.169.254/latest",
        "https://[::ffff:127.0.0.1]/v1",
        "https://192.168.1.10/v1",
        "https://[fe80::1]/v1",
    ],
)
def test_disallowed_provider_urls_are_rejected_without_saving(
    client: TestClient,
    settings: Settings,
    base_url: str,
):
    response = client.post(
        PREFIX,
        json={"vision": _local_openai(base_url)},
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_provider_settings"
    fields = error["details"]["fields"]
    assert [entry["field"] for entry in fields] == ["vision.baseUrl"]
    assert fields[0]["rule"] == "invalid_url"
    assert base_url not in response.text
    assert not _saved_path(settings).exists()


def test_rejected_provider_url_is_not_logged(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.INFO):
        response = client.post(
            PREFIX,
            json={"vision": _local_openai("https://10.0.0.5/v1")},
        )

    assert response.status_code == 422, response.text
    assert "10.0.0.5" not in caplog.text
    assert "local-secret-key" not in caplog.text


def test_local_provider_urls_are_accepted_when_policy_allows(tmp_path: Path):
    settings = _settings(
        tmp_path,
        provider_url_policy="allow-local",
        provider_allow_insecure_http=True,
    )

    with TestClient(create_app(settings)) as client:
        response = client.post(PREFIX, json={"vision": _local_openai()})

        assert response.status_code == 200, response.text
        assert response.json()["vision"]["baseUrl"] == "http://127.0.0.1:11434/v1"


def test_allow_local_still_requires_https_unless_insecure_http_is_enabled(tmp_path: Path):
    settings = _settings(tmp_path, provider_url_policy="allow-local")

    with TestClient(create_app(settings)) as client:
        rejected = client.post(PREFIX, json={"vision": _local_openai()})
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["error"]["details"]["fields"][0]["field"] == "vision.baseUrl"

        accepted = client.post(
            PREFIX,
            json={"vision": _local_openai("https://127.0.0.1:11434/v1")},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["vision"]["baseUrl"] == "https://127.0.0.1:11434/v1"


def test_saved_local_provider_fails_startup_under_public_only(settings: Settings):
    _write_saved(
        settings,
        {
            "version": 1,
            "vision": {
                "provider": "openai",
                "model": "local-model",
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key": "saved-local-secret",
            },
        },
    )

    with pytest.raises(ProviderConfigurationError) as error:
        with TestClient(create_app(settings)):
            pass

    message = str(error.value)
    assert "127.0.0.1" not in message
    assert "saved-local-secret" not in message
    assert "vision.baseUrl" in message


def test_test_endpoint_rejects_disallowed_candidate_url(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail(*args: Any, **kwargs: Any) -> HttpResponse:
        raise AssertionError("the endpoint policy must reject before any request")

    monkeypatch.setattr("app.ai.transport.PinnedHttpTransport.post", fail)

    response = client.post(
        f"{PREFIX}/test",
        json={"vision": _local_openai("https://10.0.0.5/v1")},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_provider_settings"
    assert "10.0.0.5" not in response.text
