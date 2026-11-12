from __future__ import annotations

import base64
import json
import logging
import os
import stat
import sys
import traceback
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
from app.services.provider_settings_service import SETTINGS_FILENAME, ProviderSettingsService
from app.services.secret_store import (
    MASTER_KEY_FILENAME,
    InMemoryMasterKeyStore,
    SecretBox,
    SecretStoreError,
    blob_to_record,
    provider_settings_aad,
)

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


def test_settings_document_is_parsed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = _settings(tmp_path)
    path = _write_saved(settings, {"version": 2, "planner": {"model": "planner-model"}})
    real_read_text = Path.read_text
    reads: list[Path] = []

    def counting(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == path:
            reads.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)

    ProviderSettingsService(settings)

    assert len(reads) == 1


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
        "generative": {
            "provider": "mock",
            "model": "wanx2.1-imageedit",
            "baseUrl": "https://dashscope.aliyuncs.com",
            "hasApiKey": False,
            "apiKeySource": "none",
            "dailyImageLimit": 0,
            "ready": True,
        },
        "isMock": True,
        "hasSavedOverrides": False,
    }


def test_generative_settings_require_a_key_and_switch_the_provider(
    client: TestClient,
    settings: Settings,
):
    response = client.post(
        PREFIX,
        json={"generative": {"provider": "dashscope", "model": "wanx2.1-imageedit"}},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "invalid_provider_settings"
    assert "generative.apiKey" in json.dumps(body["error"]["details"])

    response = client.post(
        PREFIX,
        json={
            "generative": {
                "provider": "dashscope",
                "model": "wanx2.1-imageedit",
                "apiKey": "sk-generative-secret",
                "dailyImageLimit": 20,
            }
        },
    )
    assert response.status_code == 200, response.text
    generative = response.json()["generative"]
    assert generative == {
        "provider": "dashscope",
        "model": "wanx2.1-imageedit",
        "baseUrl": "https://dashscope.aliyuncs.com",
        "hasApiKey": True,
        "apiKeySource": "saved",
        "dailyImageLimit": 20,
        "ready": True,
    }

    stored = _saved_path(settings).read_text(encoding="utf-8")
    assert "sk-generative-secret" not in stored
    assert "sk-generative-secret" not in response.text

    service = client.app.state.generative_service
    assert service.provider.name == "dashscope"
    assert service.provider.model == "wanx2.1-imageedit"
    assert service.provider.is_mock is False


def test_generative_settings_can_return_to_mock(client: TestClient):
    client.post(
        PREFIX,
        json={
            "generative": {
                "provider": "dashscope",
                "apiKey": "sk-generative-secret",
            }
        },
    )
    response = client.post(PREFIX, json={"generative": {"provider": "mock"}})
    assert response.status_code == 200, response.text
    assert response.json()["generative"]["provider"] == "mock"
    assert response.json()["generative"]["ready"] is True
    assert client.app.state.generative_service.provider.name == "mock"


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

    raw = _saved_path(settings).read_text(encoding="utf-8")
    saved = json.loads(raw)
    assert saved["version"] == 2
    assert saved["vision"] == {
        "provider": "openai",
        "model": "vision-model",
        "base_url": "https://vision.example.test/v1",
    }
    assert saved["decision"]["base_url"] == "https://decision.example.test/v1"
    assert "api_key" not in saved["vision"]
    assert "api_key" not in saved["decision"]
    assert set(saved["secrets"]) == {"vision", "decision"}
    assert "planner" not in saved
    assert "vision-secret-key" not in raw
    assert "decision-secret-key" not in raw

    settings_service = client.app.state.provider_settings_service
    assert task_service.orchestrator is not orchestrator_before
    assert task_service.providers is settings_service.bundle

    reread = client.get(PREFIX).json()
    assert reread["hasSavedOverrides"] is True
    assert reread["vision"]["hasApiKey"] is True
    assert "secret-key" not in json.dumps(reread)

    # A fresh process reads the encrypted document back with the same master key.
    with TestClient(create_app(settings)) as restarted:
        body = restarted.get(PREFIX).json()
    assert body["vision"]["hasApiKey"] is True
    assert body["vision"]["apiKeySource"] == "saved"
    assert body["decision"]["hasApiKey"] is True
    assert body["decision"]["apiKeySource"] == "saved"
    assert "secret-key" not in json.dumps(body)


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

    raw = _saved_path(settings).read_text(encoding="utf-8")
    stored = json.loads(raw)
    assert stored["version"] == 2
    assert "api_key" not in stored["vision"]
    assert "api_key" not in stored["decision"]
    assert set(stored["secrets"]) == {"vision", "decision"}
    assert "vision-secret-key" not in raw
    assert "decision-secret-key" not in raw

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

    cleared_raw = _saved_path(settings).read_text(encoding="utf-8")
    assert set(json.loads(cleared_raw)["secrets"]) == {"decision"}
    assert "vision-secret-key" not in cleared_raw

    with TestClient(create_app(settings)) as restarted:
        body = restarted.get(PREFIX).json()
    assert body["vision"]["hasApiKey"] is False
    assert body["decision"]["hasApiKey"] is True
    assert body["decision"]["apiKeySource"] == "saved"


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
        "generative": {
            "ok": True,
            "provider": "mock",
            "model": "generative-mock-1",
            "latencyMs": 0,
            "code": None,
            "message": None,
        },
    }


def test_test_endpoint_reports_generative_key_errors(client: TestClient):
    response = client.post(
        f"{PREFIX}/test",
        json={"generative": {"provider": "dashscope", "apiKey": ""}},
    )
    # Same contract as the text providers: an incomplete candidate is rejected
    # before any network call, naming the missing field.
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "invalid_provider_settings"
    assert "generative.apiKey" in json.dumps(body["error"]["details"])


def test_test_endpoint_checks_the_generative_provider_with_the_new_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []

    def fake_check(self, *, timeout=None):
        calls.append(self.model)
        return 12

    monkeypatch.setattr(
        "app.ai.providers.generative_dashscope.DashScopeGenerativeProvider.check_connection",
        fake_check,
    )
    response = client.post(
        f"{PREFIX}/test",
        json={
            "generative": {
                "provider": "dashscope",
                "model": "wanx2.1-imageedit",
                "apiKey": "sk-unsaved-key",
            }
        },
    )
    assert response.status_code == 200, response.text
    generative = response.json()["generative"]
    assert generative == {
        "ok": True,
        "provider": "dashscope",
        "model": "wanx2.1-imageedit",
        "latencyMs": 12,
        "code": None,
        "message": None,
    }
    assert calls == ["wanx2.1-imageedit"]


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


@pytest.mark.parametrize(
    "host",
    ["127.1", "2130706433", "0x7f000001", "0177.0.0.1"],
)
def test_legacy_numeric_provider_hosts_are_rejected_without_saving(
    client: TestClient,
    settings: Settings,
    host: str,
):
    response = client.post(
        PREFIX,
        json={"vision": _local_openai(f"https://{host}/v1")},
    )

    assert response.status_code == 422, response.text
    fields = response.json()["error"]["details"]["fields"]
    assert [entry["field"] for entry in fields] == ["vision.baseUrl"]
    assert fields[0]["rule"] == "invalid_url"
    assert not _saved_path(settings).exists()


def test_numeric_looking_domains_still_save(client: TestClient):
    for host in ("1.2.3.4.example.com", "123.com"):
        response = client.post(
            PREFIX,
            json={"vision": _local_openai(f"https://{host}/v1")},
        )
        assert response.status_code == 200, response.text


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


# --- B6b: encrypted provider settings (L5) ---


def _master_key_path(settings: Settings) -> Path:
    return settings.data_dir / MASTER_KEY_FILENAME


def _document(settings: Settings) -> dict[str, Any]:
    return json.loads(_saved_path(settings).read_text(encoding="utf-8"))


def _assert_no_plaintext(settings: Settings, secrets: list[str]) -> None:
    for path in settings.data_dir.rglob("*"):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        for secret in secrets:
            assert secret.encode("utf-8") not in raw, f"plaintext key leaked into {path.name}"


def _capture_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
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
    return calls


def test_v2_roundtrip_uses_the_saved_keys_after_restart(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    saved = client.post(
        PREFIX,
        json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION, "planner": _OPENAI_PLANNER},
    )
    assert saved.status_code == 200, saved.text
    assert _document(settings)["version"] == 2

    calls = _capture_requests(monkeypatch)
    with TestClient(create_app(settings)) as restarted:
        view = restarted.get(PREFIX).json()
        assert view["vision"]["apiKeySource"] == "saved"
        assert view["decision"]["apiKeySource"] == "saved"
        assert view["planner"]["apiKeySource"] == "saved"
        tested = restarted.post(f"{PREFIX}/test", json={})

    assert tested.status_code == 200, tested.text
    assert tested.json()["vision"]["ok"] is True
    assert tested.json()["decision"]["ok"] is True
    assert tested.json()["planner"]["ok"] is True
    assert [call["headers"]["Authorization"] for call in calls] == [
        "Bearer vision-secret-key",
        "Bearer decision-secret-key",
        "Bearer planner-secret-key",
    ]


def test_v1_document_migrates_to_v2_without_losing_fields(
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
):
    path = _write_saved(
        settings,
        {
            "version": 1,
            "vision": {
                "provider": "openai",
                "model": "vision-model",
                "base_url": "https://vision.example.test/v1",
                "api_key": "vision-secret-key",
            },
            "decision": {
                "provider": "openai",
                "model": "decision-model",
                "base_url": "https://decision.example.test/v1",
                "api_key": "decision-secret-key",
            },
            "planner": {"model": "planner-model"},
        },
    )

    with caplog.at_level(logging.INFO):
        with TestClient(create_app(settings)) as client:
            body = client.get(PREFIX).json()

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["version"] == 2
    assert document["vision"] == {
        "provider": "openai",
        "model": "vision-model",
        "base_url": "https://vision.example.test/v1",
    }
    assert document["decision"]["model"] == "decision-model"
    assert document["planner"] == {"model": "planner-model"}
    assert set(document["secrets"]) == {"vision", "decision"}
    for entry in ("vision", "decision", "planner"):
        assert "api_key" not in document.get(entry, {})
    assert "api_key" not in json.dumps(document)
    _assert_no_plaintext(settings, ["vision-secret-key", "decision-secret-key"])
    assert body["vision"]["apiKeySource"] == "saved"
    assert body["decision"]["apiKeySource"] == "saved"
    assert body["planner"]["model"] == "planner-model"
    assert body["planner"]["apiKeySource"] == "saved"
    assert "provider_settings_migrated from=1 to=2" in caplog.text
    assert "vision-secret-key" not in caplog.text
    assert "decision-secret-key" not in caplog.text


def test_invalid_v1_document_is_not_migrated(settings: Settings):
    path = _write_saved(
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
    before = path.read_bytes()

    with pytest.raises(ProviderConfigurationError):
        with TestClient(create_app(settings)):
            pass

    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".tmp").exists()


@pytest.mark.parametrize("failure", ["replace", "encrypt"])
def test_failed_migration_keeps_v1_bytes_and_fails_startup(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
):
    path = _write_saved(
        settings,
        {
            "version": 1,
            "vision": {
                "provider": "openai",
                "model": "vision-model",
                "base_url": "https://vision.example.test/v1",
                "api_key": "vision-secret-key",
            },
        },
    )
    before = path.read_bytes()

    if failure == "replace":

        def broken_replace(src: Any, dst: Any) -> None:
            raise OSError("replace denied")

        monkeypatch.setattr(os, "replace", broken_replace)
    else:

        def broken_encrypt(self: Any, plaintext: str, aad: bytes) -> Any:
            raise SecretStoreError("The provider API key could not be encrypted.")

        monkeypatch.setattr(SecretBox, "encrypt", broken_encrypt)

    with pytest.raises(ProviderConfigurationError):
        with TestClient(create_app(settings)):
            pass

    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".tmp").exists()
    assert json.loads(before)["version"] == 1


def _flip_ciphertext(settings: Settings, kind: str) -> None:
    document = _document(settings)
    raw = bytearray(base64.b64decode(document["secrets"][kind]["ciphertext"]))
    raw[len(raw) // 2] ^= 0x01
    document["secrets"][kind]["ciphertext"] = base64.b64encode(bytes(raw)).decode("ascii")
    _saved_path(settings).write_text(json.dumps(document), encoding="utf-8")


def test_tampered_ciphertext_fails_closed_without_leaking(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    _flip_ciphertext(settings, "vision")

    with pytest.raises(ProviderConfigurationError) as error:
        with TestClient(create_app(settings)):
            pass

    message = str(error.value)
    assert "Re-enter the API key" in message
    assert "vision-secret-key" not in message
    assert _document(settings)["version"] == 2


def test_secrets_cannot_be_swapped_between_providers(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION, "decision": _OPENAI_DECISION})
    assert saved.status_code == 200, saved.text
    document = _document(settings)
    document["secrets"]["vision"], document["secrets"]["decision"] = (
        document["secrets"]["decision"],
        document["secrets"]["vision"],
    )
    _saved_path(settings).write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProviderConfigurationError) as error:
        with TestClient(create_app(settings)):
            pass

    assert "Re-enter the API key" in str(error.value)


def test_repeated_saves_use_a_fresh_nonce(client: TestClient, settings: Settings):
    first = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert first.status_code == 200, first.text
    before = _document(settings)["secrets"]["vision"]

    second = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert second.status_code == 200, second.text
    after = _document(settings)["secrets"]["vision"]

    assert before["nonce"] != after["nonce"]
    assert before["ciphertext"] != after["ciphertext"]
    assert len(base64.b64decode(after["nonce"])) == 12


def test_saved_keys_never_reach_disk_or_logs(
    client: TestClient,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.INFO):
        saved = client.post(
            PREFIX,
            json={
                "vision": _OPENAI_VISION,
                "decision": _OPENAI_DECISION,
                "planner": _OPENAI_PLANNER,
            },
        )
        assert saved.status_code == 200, saved.text
        assert client.get(PREFIX).status_code == 200
        assert client.post(f"{PREFIX}/reset").status_code == 200

    secrets = ["vision-secret-key", "decision-secret-key", "planner-secret-key"]
    _assert_no_plaintext(settings, secrets)
    for secret in secrets:
        assert secret not in caplog.text
    assert not _saved_path(settings).with_name(SETTINGS_FILENAME + ".tmp").exists()


def test_missing_master_key_fails_startup_and_asks_for_new_keys(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    master = _master_key_path(settings)
    assert master.exists()
    master.unlink()
    before = _saved_path(settings).read_bytes()

    with pytest.raises(ProviderConfigurationError) as error:
        with TestClient(create_app(settings)):
            pass

    message = str(error.value)
    assert "Re-enter the API key" in message
    assert "vision-secret-key" not in message
    # No plaintext fallback: the encrypted document is still the only source.
    assert _document(settings)["version"] == 2
    assert _saved_path(settings).read_bytes() == before
    # D1: a deleted master key must never be replaced by a freshly minted one.
    assert not master.exists()
    assert not list(settings.data_dir.glob(MASTER_KEY_FILENAME + "*"))


def test_first_master_key_is_still_created_when_v2_holds_no_secrets(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(PREFIX, json={"planner": {"model": "planner-model"}})
    assert saved.status_code == 200, saved.text
    document = _document(settings)
    assert document["version"] == 2
    assert document["secrets"] == {}
    assert not _master_key_path(settings).exists()

    # Nothing depends on a master key yet, so the first real key may create one.
    with TestClient(create_app(settings)) as restarted:
        response = restarted.post(PREFIX, json={"decision": _OPENAI_DECISION})
        assert response.status_code == 200, response.text

    assert _master_key_path(settings).exists()
    assert set(_document(settings)["secrets"]) == {"decision"}
    _assert_no_plaintext(settings, ["decision-secret-key"])


def test_overlong_decrypted_key_fails_closed_without_echoing_the_key(
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
):
    from app.services.provider_settings_service import ProviderSettingsService

    canary = "sk-CANARY-OVERLONG-" + "A" * 9000
    box = SecretBox(InMemoryMasterKeyStore())
    record = blob_to_record(box.encrypt(canary, provider_settings_aad("vision")))
    path = _saved_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "vision": {
                    "provider": "openai",
                    "model": "vision-model",
                    "base_url": "https://vision.example.test/v1",
                },
                "secrets": {"vision": record},
            }
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderConfigurationError) as error:
            ProviderSettingsService(settings, secret_box=box)

    message = str(error.value)
    rendered = "".join(traceback.format_exception(error.value))
    assert "could not be decrypted" in message
    assert "Re-enter the API key" in message
    # The exception type is the contract one and the pydantic input is not chained.
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    for text in (message, rendered, caplog.text):
        assert canary not in text
        assert canary[:64] not in text
        assert "input_value" not in text
    assert path.read_bytes() == before


def test_corrupt_master_key_fails_startup(client: TestClient, settings: Settings):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    _master_key_path(settings).write_bytes(b"not-a-master-key")

    with pytest.raises(ProviderConfigurationError) as error:
        with TestClient(create_app(settings)):
            pass

    assert "Re-enter the API key" in str(error.value)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_master_key_and_document_are_private_on_posix(
    client: TestClient,
    settings: Settings,
):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text

    assert stat.S_IMODE(_master_key_path(settings).stat().st_mode) == 0o600
    assert stat.S_IMODE(_saved_path(settings).stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_master_key_is_dpapi_protected_on_windows(client: TestClient, settings: Settings):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    master = _master_key_path(settings)

    assert master.exists()
    raw = master.read_bytes()
    # DPAPI blobs start with the provider revision magic; the file is not the key.
    assert raw.startswith(b"\x01\x00\x00\x00")
    assert len(raw) > 32
    assert b"vision-secret-key" not in raw


def test_encryption_off_writes_v1_and_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    settings = _settings(tmp_path, provider_settings_encryption="off")

    with caplog.at_level(logging.WARNING):
        with TestClient(create_app(settings)) as client:
            saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
            assert saved.status_code == 200, saved.text

    document = _document(settings)
    assert document["version"] == 1
    assert document["vision"]["api_key"] == "vision-secret-key"
    assert "secrets" not in document
    assert "provider_settings_encryption_disabled mode=off" in caplog.text
    assert "provider_settings_plaintext_write mode=off" in caplog.text


def test_off_mode_still_needs_the_master_key_to_read_v2(client: TestClient, settings: Settings):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    _master_key_path(settings).unlink()
    downgraded = settings.model_copy(update={"provider_settings_encryption": "off"})

    with pytest.raises(ProviderConfigurationError) as error:
        with TestClient(create_app(downgraded)):
            pass

    assert "Re-enter the API key" in str(error.value)
    assert _document(settings)["version"] == 2


def test_v2_entries_reject_a_smuggled_api_key(client: TestClient, settings: Settings):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    document = _document(settings)
    document["vision"]["api_key"] = "vision-secret-key"
    _saved_path(settings).write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ProviderConfigurationError):
        with TestClient(create_app(settings)):
            pass


def test_unsupported_document_version_fails_startup(settings: Settings):
    _write_saved(settings, {"version": 3, "vision": None})

    with pytest.raises(ProviderConfigurationError) as error:
        with TestClient(create_app(settings)):
            pass

    assert "unsupported format version" in str(error.value)


def test_encrypt_failure_on_save_keeps_the_previous_document(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    before = _saved_path(settings).read_bytes()

    def broken_encrypt(self: Any, plaintext: str, aad: bytes) -> Any:
        raise SecretStoreError("The provider API key could not be encrypted.")

    monkeypatch.setattr(SecretBox, "encrypt", broken_encrypt)

    response = client.post(PREFIX, json={"decision": _OPENAI_DECISION})

    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "secret_store_error"
    assert "decision-secret-key" not in response.text
    assert _saved_path(settings).read_bytes() == before
    assert client.get(PREFIX).json()["decision"]["provider"] == "mock"


def test_write_failure_on_save_keeps_the_previous_document(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    saved = client.post(PREFIX, json={"vision": _OPENAI_VISION})
    assert saved.status_code == 200, saved.text
    before = _saved_path(settings).read_bytes()

    def broken_replace(src: Any, dst: Any) -> None:
        raise OSError("replace denied")

    monkeypatch.setattr(os, "replace", broken_replace)

    response = client.post(PREFIX, json={"decision": _OPENAI_DECISION})

    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "provider_settings_write_failed"
    assert _saved_path(settings).read_bytes() == before
    assert not _saved_path(settings).with_name(SETTINGS_FILENAME + ".tmp").exists()


def test_service_accepts_an_injected_secret_box(settings: Settings):
    from app.models.provider_settings import ProviderSettingsUpdate
    from app.services.provider_settings_service import ProviderSettingsService

    box = SecretBox(InMemoryMasterKeyStore())
    service = ProviderSettingsService(settings, secret_box=box)

    service.apply(ProviderSettingsUpdate.model_validate({"vision": _OPENAI_VISION}))

    assert _document(settings)["version"] == 2
    assert not _master_key_path(settings).exists()
    restarted = ProviderSettingsService(settings, secret_box=box)
    assert restarted.view().vision.has_api_key is True
    _assert_no_plaintext(settings, ["vision-secret-key"])
