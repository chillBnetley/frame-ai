from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_image, upload


def test_unknown_route_uses_error_envelope(client: TestClient):
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.headers["x-request-id"]


def test_method_not_allowed_uses_error_envelope(client: TestClient):
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_validation_details_include_field_and_rule(client: TestClient):
    response = client.post("/api/v1/images", files={"wrong": ("photo.png", b"x", "image/png")})

    assert response.status_code == 422
    body = response.json()
    field = body["error"]["details"]["fields"][0]
    assert field["field"] == "file"
    assert field["rule"] == "missing"
    assert field["limit"] == {}
    assert "input" not in field


def test_unexpected_error_hides_traceback_and_keeps_request_id(tmp_path: Path, caplog):
    settings = Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        log_level="DEBUG",
    )
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("SECRET_INTERNAL_PATH")

    with caplog.at_level(logging.ERROR, logger="frame_ai.errors"):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom", headers={"X-Request-ID": "boom-request"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "Traceback" not in body["error"]["message"]
    assert "SECRET_INTERNAL_PATH" not in body["error"]["message"]
    assert response.headers["x-request-id"] == "boom-request"
    assert "boom-request" in caplog.text


def test_cors_preflight_for_allowed_origin(client: TestClient):
    response = client.options(
        "/api/v1/images",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://testserver"


def test_cors_preflight_for_denied_origin_uses_error_envelope(client: TestClient):
    response = client.options(
        "/api/v1/images",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cors_origin_denied"
    assert response.headers["x-request-id"]
    assert "access-control-allow-origin" not in response.headers


def test_middleware_payload_limit_uses_error_envelope(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024,
        content_length_allowance=0,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        log_level="WARNING",
    )

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/images",
            content=iter([b"x" * 2048]),
            headers={"Content-Type": "multipart/form-data; boundary=x"},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["x-request-id"]


def test_upload_response_is_not_affected_by_error_handlers(client: TestClient):
    response = upload(client, make_image("PNG"))

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")
