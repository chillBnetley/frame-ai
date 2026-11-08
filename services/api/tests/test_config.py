from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings
from app.services.image_service import ImageService
from tests.conftest import make_image, upload


def test_data_dir_is_identical_from_api_dir_and_repo_root():
    environment = {
        **os.environ,
        "FRAME_DATA_DIR": "data",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(REPO_ROOT / "services" / "api"),
    }
    script = "from app.core.config import Settings; print(Settings().data_dir)"

    resolved: list[str] = []
    for working_dir in (REPO_ROOT / "services" / "api", REPO_ROOT):
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=working_dir,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=60,
        )
        resolved.append(result.stdout.strip())

    assert resolved[0] == resolved[1]
    assert resolved[0] == str((REPO_ROOT / "data").resolve())


def test_relative_data_dir_resolves_against_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = Settings(data_dir="relative-data")

    assert settings.data_dir == (REPO_ROOT / "relative-data").resolve()
    assert settings.data_dir.is_absolute()


def test_preview_max_bytes_defaults_and_rejects_nonpositive_values():
    settings = Settings()

    assert settings.preview_max_bytes == 2 * 1024 * 1024 * 1024
    with pytest.raises(ValidationError):
        Settings(preview_max_bytes=0)


def test_provider_endpoint_policy_defaults_to_public_https():
    settings = Settings(_env_file=None)

    assert settings.provider_url_policy == "public-only"
    assert settings.provider_allow_insecure_http is False


def test_provider_endpoint_policy_reads_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FRAME_PROVIDER_URL_POLICY", "allow-local")
    monkeypatch.setenv("FRAME_PROVIDER_ALLOW_INSECURE_HTTP", "true")

    settings = Settings(_env_file=None)

    assert settings.provider_url_policy == "allow-local"
    assert settings.provider_allow_insecure_http is True


def test_provider_endpoint_policy_rejects_unknown_values():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, provider_url_policy="legacy")


def test_config_endpoint_exposes_runtime_limits(client: TestClient, settings: Settings):
    response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json() == {
        "maxUploadBytes": settings.max_upload_bytes,
        "maxJsonBodyBytes": settings.max_json_body_bytes,
        "maxImagePixels": settings.max_image_pixels,
        "allowedMimeTypes": ["image/jpeg", "image/png", "image/webp", "image/tiff"],
    }


def test_config_endpoint_rejects_writes(client: TestClient):
    response = client.post("/api/v1/config")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_startup_fails_when_disk_space_is_insufficient(settings, monkeypatch):
    service = ImageService(settings)
    usage = shutil.disk_usage(settings.data_dir.parent)
    monkeypatch.setattr(
        "app.services.image_service.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 0, "total": usage.total, "used": usage.used})(),
    )

    with pytest.raises(RuntimeError, match="Insufficient free disk space"):
        service.ensure_ready()


def test_uploaded_limit_matches_runtime_config(client: TestClient, settings):
    config = client.get("/api/v1/config").json()
    payload = make_image("PNG", size=(64, 48))

    assert config["maxUploadBytes"] == settings.max_upload_bytes
    assert config["maxJsonBodyBytes"] == settings.max_json_body_bytes
    assert upload(client, payload).status_code == 201


B6_ENV_VARIABLES = (
    "FRAME_PROVIDER_URL_POLICY",
    "FRAME_PROVIDER_ALLOW_INSECURE_HTTP",
    "FRAME_PROVIDER_SETTINGS_ENCRYPTION",
    "FRAME_PROVIDER_DAILY_REQUEST_LIMIT",
    "FRAME_PROVIDER_DAILY_TOKEN_LIMIT",
    "FRAME_API_AUTH_ENABLED",
    "FRAME_API_TOKEN_FILE",
    "FRAME_RATE_LIMIT_UPLOAD",
    "FRAME_RATE_LIMIT_EXPORT",
    "FRAME_RATE_LIMIT_ANALYSIS",
    "FRAME_RATE_LIMIT_PHOTOGRAPHER",
    "FRAME_RATE_LIMIT_SETTINGS",
    "FRAME_RATE_LIMIT_RENDER",
    "FRAME_RATE_LIMIT_DEFAULT",
)


def test_env_example_documents_every_b6_setting():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    documented: set[str] = set()
    for line in text.splitlines():
        candidate = line.lstrip("# ").strip()
        if "=" in candidate:
            documented.add(candidate.split("=", 1)[0].strip())

    assert set(B6_ENV_VARIABLES) <= documented
    for name in B6_ENV_VARIABLES:
        assert name.removeprefix("FRAME_").lower() in Settings.model_fields
    assert "ABSOLUTE" in text
    assert not re.search(r"\b[0-9a-f]{64}\b", text)
