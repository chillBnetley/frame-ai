from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_image, upload


@pytest.mark.parametrize(
    ("image_format", "filename", "content_type", "expected_mime"),
    [
        ("PNG", "photo.png", "image/png", "image/png"),
        ("JPEG", "photo.jpg", "image/jpeg", "image/jpeg"),
        ("WEBP", "photo.webp", "image/webp", "image/webp"),
    ],
)
def test_upload_supported_formats(
    client: TestClient,
    image_format: str,
    filename: str,
    content_type: str,
    expected_mime: str,
):
    payload = make_image(image_format, size=(80, 60))

    response = upload(client, payload, filename, content_type)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"imageId", "originalName", "width", "height", "mimeType", "bytes"}
    assert body["originalName"] == filename
    assert body["width"] == 80
    assert body["height"] == 60
    assert body["mimeType"] == expected_mime
    assert body["bytes"] == len(payload)

    original = client.get(f"/api/v1/images/{body['imageId']}/original")
    assert original.status_code == 200
    assert original.headers["content-type"] == expected_mime
    assert original.headers["x-content-type-options"] == "nosniff"
    assert "inline" in original.headers["content-disposition"]
    assert original.content == payload


def test_preview_preserves_original_bytes_and_supports_download(
    client: TestClient, settings: Settings
):
    payload = make_image("PNG", size=(100, 70))
    created = upload(client, payload).json()
    storage_key = created["imageId"]
    stored_file = settings.data_dir / "originals" / f"{storage_key}.png"
    before = hashlib.sha256(stored_file.read_bytes()).hexdigest()

    preview = client.get(f"/api/v1/images/{created['imageId']}/original")
    download = client.get(f"/api/v1/images/{created['imageId']}/original?download=true")
    after = hashlib.sha256(stored_file.read_bytes()).hexdigest()

    assert preview.status_code == 200
    assert download.status_code == 200
    assert preview.content == payload
    assert download.content == payload
    assert before == after
    assert download.headers["content-disposition"].startswith("attachment;")


def test_upload_uses_server_generated_relative_path(client: TestClient, settings: Settings):
    response = upload(client, make_image("PNG"), filename="../../outside/evil.png")

    assert response.status_code == 201
    body = response.json()
    assert body["originalName"] == "evil.png"
    assert not (settings.data_dir.parent / "outside").exists()
    assert not (settings.data_dir.parent / "evil.png").exists()
    assert (settings.data_dir / "originals" / f"{body['imageId']}.png").is_file()


def test_upload_response_has_request_id(client: TestClient):
    response = upload(client, make_image("PNG"))

    assert response.status_code == 201
    assert response.headers["x-request-id"]


def test_registry_survives_app_restart(client: TestClient, settings: Settings):
    payload = make_image("PNG")
    image_id = upload(client, payload).json()["imageId"]

    with TestClient(create_app(settings)) as restarted:
        response = restarted.get(f"/api/v1/images/{image_id}/original")

    assert response.status_code == 200
    assert response.content == payload


def test_rejects_unsupported_declared_type(client: TestClient):
    response = upload(client, make_image("PNG"), "photo.png", "text/plain")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_rejects_spoofed_mime_type(client: TestClient):
    response = upload(client, make_image("JPEG"), "fake.png", "image/png")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "mime_mismatch"


def test_rejects_invalid_image_content(client: TestClient):
    response = upload(client, b"this is not an image", "photo.png", "image/png")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_image"


def test_rejects_empty_file(client: TestClient):
    response = upload(client, b"", "photo.png", "image/png")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"


def test_rejects_file_over_size_limit(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024,
        max_image_pixels=10_000_000,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )
    payload = make_image("PNG", size=(128, 128), noise=True)
    assert len(payload) > 1024

    with TestClient(create_app(settings)) as test_client:
        response = upload(test_client, payload)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert response.json()["error"]["details"]["maxBytes"] == 1024


def test_rejects_image_over_pixel_limit(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1000,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )

    with TestClient(create_app(settings)) as test_client:
        response = upload(test_client, make_image("PNG", size=(64, 48)))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_pixels_exceeded"
    assert response.json()["error"]["details"]["maxPixels"] == 1000


def test_unknown_image_returns_404(client: TestClient):
    response = client.get("/api/v1/images/00000000-0000-4000-8000-000000000000/original")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"


def test_malformed_image_id_returns_404(client: TestClient):
    response = client.get("/api/v1/images/not-a-uuid/original")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"


def test_missing_file_field_returns_422(client: TestClient):
    response = client.post("/api/v1/images", files={"wrong": ("photo.png", b"x", "image/png")})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["fields"][0]["field"].endswith("file")


def test_missing_stored_file_returns_404(client: TestClient, settings: Settings):
    image_id = upload(client, make_image("PNG")).json()["imageId"]
    stored_file = settings.data_dir / "originals" / f"{image_id}.png"
    stored_file.unlink()

    response = client.get(f"/api/v1/images/{image_id}/original")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_file_missing"
