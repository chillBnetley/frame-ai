from __future__ import annotations

import logging
import os
import re
import stat
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.auth import API_TOKEN_HEX_CHARS, ApiTokenService
from app.core.config import Settings
from app.core.middleware import RateLimiter, rate_limit_category
from app.main import create_app

posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX file modes are not enforced on Windows",
)


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "data_dir": tmp_path / "data",
        "max_upload_bytes": 1024 * 1024,
        "max_image_pixels": 1_000_000,
        "allowed_origins": "http://testserver",
        "allowed_hosts": "testserver",
        "log_level": "WARNING",
        "api_auth_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def _token(settings: Settings) -> str:
    return settings.api_token_path.read_text(encoding="ascii")


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-FRAME-Token": _token(settings)}


def test_ensure_token_writes_hex_and_rotates(tmp_path: Path):
    service = ApiTokenService(tmp_path / "api-token")

    first = service.ensure_token()
    second = service.ensure_token()

    assert len(first) == API_TOKEN_HEX_CHARS
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first != second
    assert (tmp_path / "api-token").read_text(encoding="ascii") == second
    assert service.matches(second) is True
    assert service.matches(first) is False
    assert service.matches(None) is False
    assert service.matches("") is False
    assert service.matches("\xe9") is False


@posix_only
def test_token_file_is_private(tmp_path: Path):
    service = ApiTokenService(tmp_path / "api-token")

    service.ensure_token()

    assert stat.S_IMODE((tmp_path / "api-token").stat().st_mode) == 0o600


def test_token_file_override_is_resolved(tmp_path: Path):
    custom = tmp_path / "custom-token"
    settings = _settings(tmp_path, api_token_file=custom)

    assert settings.api_token_path == custom.resolve()


def test_token_value_never_reaches_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    settings = _settings(tmp_path)

    with caplog.at_level("DEBUG"):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/config", headers=auth_headers(settings)).status_code == 200
            token = _token(settings)

    assert token not in caplog.text


def test_root_and_health_need_no_token(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        health = client.get("/api/v1/health")
        assert health.status_code == 200


def test_api_requires_a_matching_token(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        missing = client.get("/api/v1/config")
        wrong = client.get("/api/v1/config", headers={"X-FRAME-Token": "not-the-token"})
        allowed = client.get("/api/v1/config", headers=auth_headers(settings))

    assert missing.status_code == 401
    assert missing.json()["error"] == {
        "code": "unauthorized",
        "message": "The API token is missing or invalid.",
        "details": {},
    }
    assert _token(settings) not in missing.text
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"
    assert allowed.status_code == 200


def test_non_ascii_token_header_is_rejected_without_an_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    settings = _settings(tmp_path)
    with caplog.at_level("DEBUG"):
        with TestClient(create_app(settings)) as client:
            rejected = client.get(
                "/api/v1/config",
                headers=[(b"x-frame-token", b"\xe9")],
            )
            allowed = client.get("/api/v1/config", headers=auth_headers(settings))

    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "unauthorized"
    assert "internal_error" not in rejected.text
    assert allowed.status_code == 200
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_options_preflight_is_not_authenticated(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/api/v1/images",
            headers={
                "Origin": "http://testserver",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-FRAME-Token",
            },
        )

    assert response.status_code != 401
    assert response.headers.get("access-control-allow-origin") == "http://testserver"
    assert "x-frame-token" in response.headers.get("access-control-allow-headers", "").lower()


def test_invalid_host_is_rejected_before_auth(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://evil.test") as client:
        response = client.get("/api/v1/config")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_host"


def test_cross_origin_write_is_rejected_before_auth(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/settings/nope",
            headers={"Origin": "http://evil.test"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_auth_rejects_before_the_body_limit_is_applied(tmp_path: Path):
    settings = _settings(
        tmp_path,
        max_upload_bytes=1024,
        content_length_allowance=0,
    )
    with TestClient(create_app(settings)) as client:
        rejected = client.post(
            "/api/v1/images",
            content=b"x" * 4096,
            headers={"Content-Type": "application/octet-stream"},
        )
        limited = client.post(
            "/api/v1/images",
            content=b"x" * 4096,
            headers={
                "Content-Type": "application/octet-stream",
                **auth_headers(settings),
            },
        )

    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "unauthorized"
    assert limited.status_code == 413


def test_auth_disabled_restores_anonymous_access(tmp_path: Path):
    settings = _settings(
        tmp_path,
        api_auth_enabled=False,
        rate_limit_analysis=1,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/config").status_code == 200
        first = client.post("/api/v1/analysis/nope")
        second = client.post("/api/v1/analysis/nope")

    assert first.status_code != 429
    assert second.status_code != 429
    assert not settings.api_token_path.exists()


def test_rotation_invalidates_the_old_token(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        old = _token(settings)
        assert client.get("/api/v1/config", headers={"X-FRAME-Token": old}).status_code == 200

        new = client.app.state.api_token_service.ensure_token()

        assert new != old
        assert client.get("/api/v1/config", headers={"X-FRAME-Token": old}).status_code == 401
        assert client.get("/api/v1/config", headers={"X-FRAME-Token": new}).status_code == 200


def test_rate_limit_rejects_with_retry_after_and_details(tmp_path: Path):
    settings = _settings(
        tmp_path,
        rate_limit_analysis=1,
        rate_limit_default=0,
    )
    with TestClient(create_app(settings)) as client:
        headers = auth_headers(settings)
        first = client.post("/api/v1/analysis/nope", headers=headers)
        limited = client.post("/api/v1/analysis/nope", headers=headers)

    assert first.status_code != 429
    assert limited.status_code == 429
    error = limited.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["message"] == "Too many requests. Try again later."
    assert error["details"]["category"] == "analysis"
    assert error["details"]["retryAfterSeconds"] >= 1
    assert int(limited.headers["retry-after"]) == error["details"]["retryAfterSeconds"]


def test_reads_do_not_consume_the_rate_limit(tmp_path: Path):
    settings = _settings(tmp_path, rate_limit_analysis=1)
    with TestClient(create_app(settings)) as client:
        headers = auth_headers(settings)
        for _ in range(3):
            assert client.get("/api/v1/analysis/nope", headers=headers).status_code != 429


def test_zero_limit_never_rejects(tmp_path: Path):
    settings = _settings(tmp_path, rate_limit_analysis=0)
    with TestClient(create_app(settings)) as client:
        headers = auth_headers(settings)
        for _ in range(5):
            assert client.post("/api/v1/analysis/nope", headers=headers).status_code != 429


def test_categories_have_independent_buckets(tmp_path: Path):
    settings = _settings(
        tmp_path,
        rate_limit_analysis=1,
        rate_limit_settings=1,
    )
    with TestClient(create_app(settings)) as client:
        headers = auth_headers(settings)
        client.post("/api/v1/analysis/nope", headers=headers)
        assert client.post("/api/v1/analysis/nope", headers=headers).status_code == 429
        assert client.post("/api/v1/settings/nope", headers=headers).status_code != 429


def test_rate_limit_category_mapping():
    assert rate_limit_category("/api/v1/images") == "upload"
    assert rate_limit_category("/api/v1/images/abc") == "upload"
    assert rate_limit_category("/api/v1/exports") == "export"
    assert rate_limit_category("/api/v1/analysis") == "analysis"
    assert rate_limit_category("/api/v1/ai/photographer/chat") == "photographer"
    assert rate_limit_category("/api/v1/settings/providers") == "settings"
    assert rate_limit_category("/api/v1/sessions/abc/render") == "render"
    assert rate_limit_category("/api/v1/sessions/abc/export") == "export"
    assert rate_limit_category("/api/v1/previews/abc") == "render"
    assert rate_limit_category("/api/v1/sessions/abc/undo") == "default"


def test_rate_limiter_refills_over_the_window():
    now = [0.0]
    limiter = RateLimiter({"analysis": 2}, window_seconds=60.0, clock=lambda: now[0])

    assert limiter.consume("analysis") is None
    assert limiter.consume("analysis") is None
    blocked = limiter.consume("analysis")
    assert blocked is not None and blocked >= 1

    now[0] = 30.0
    assert limiter.consume("analysis") is None
    assert limiter.consume("analysis") is not None


def test_rate_limiter_zero_capacity_is_unlimited():
    limiter = RateLimiter({"analysis": 0, "upload": 0})

    assert all(limiter.consume("analysis") is None for _ in range(100))
    assert limiter.consume("unknown") is None


def test_rate_limiter_is_thread_safe():
    limiter = RateLimiter({"analysis": 5}, window_seconds=60.0, clock=lambda: 0.0)
    barrier = threading.Barrier(20)
    allowed: list[int] = []
    rejected: list[int] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        result = limiter.consume("analysis")
        with lock:
            if result is None:
                allowed.append(1)
            else:
                rejected.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(allowed) == 5
    assert len(rejected) == 15


def test_token_write_failure_preserves_the_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / "api-token"
    service = ApiTokenService(path)
    original = service.ensure_token()
    real_replace = os.replace

    def broken_replace(src: str, dst: str) -> None:
        if Path(dst) == path:
            raise OSError("replace denied")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", broken_replace)

    with pytest.raises(OSError):
        service.ensure_token()

    assert path.read_text(encoding="ascii") == original
    assert not path.with_name(path.name + ".tmp").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_token_rotation_survives_a_hardened_acl(tmp_path: Path):
    import subprocess

    service = ApiTokenService(tmp_path / "api-token")
    service.ensure_token()
    path = tmp_path / "api-token"
    user = os.environ.get("USERNAME") or ""
    assert user
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
        check=False,
        capture_output=True,
        timeout=10,
    )

    second = service.ensure_token()

    assert path.read_text(encoding="ascii") == second
