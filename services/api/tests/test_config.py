from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

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


def test_config_endpoint_exposes_runtime_limits(client: TestClient):
    response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json() == {
        "maxUploadBytes": 1024 * 1024,
        "maxImagePixels": 1_000_000,
        "allowedMimeTypes": ["image/jpeg", "image/png", "image/webp"],
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
    assert upload(client, payload).status_code == 201
