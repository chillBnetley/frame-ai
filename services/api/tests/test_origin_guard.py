from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from tests.conftest import make_image


def test_cross_site_origin_is_rejected_for_uploads(client: TestClient, settings: Settings):
    response = client.post(
        "/api/v1/images",
        files={"file": ("photo.png", make_image("PNG"), "image/png")},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "origin_not_allowed"
    assert body["error"]["details"]["origin"] == "https://evil.example"
    assert response.headers["x-request-id"]
    original_dir = settings.originals_dir
    assert not original_dir.exists() or not any(original_dir.iterdir())


def test_unexpected_host_is_rejected(client: TestClient):
    response = client.get("/api/v1/health", headers={"Host": "evil.example"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_host"
    assert response.headers["x-request-id"]


def test_allowed_origin_can_write(client: TestClient):
    response = client.post(
        "/api/v1/images",
        files={"file": ("photo.png", make_image("PNG"), "image/png")},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 201


def test_cross_site_fetch_metadata_is_rejected(client: TestClient):
    response = client.post(
        "/api/v1/sessions",
        json={"imageId": "00000000-0000-4000-8000-000000000000"},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_preflight_allows_delete(client: TestClient):
    response = client.options(
        "/api/v1/analysis/00000000-0000-4000-8000-000000000000",
        headers={"Origin": "http://testserver", "Access-Control-Request-Method": "DELETE"},
    )

    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_preflight_for_unsupported_method_returns_the_json_envelope(client: TestClient):
    response = client.options(
        "/api/v1/images",
        headers={"Origin": "http://testserver", "Access-Control-Request-Method": "PUT"},
    )

    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-request-id"]
    body = response.json()
    assert body["error"]["code"] == "cors_method_denied"
    assert body["error"]["details"]["method"] == "PUT"
