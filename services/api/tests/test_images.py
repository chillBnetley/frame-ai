from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
import tifffile
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.main import create_app
from tests.conftest import image_row, make_image, upload


@pytest.mark.parametrize(
    ("image_format", "filename", "content_type", "expected_mime"),
    [
        ("PNG", "photo.png", "image/png", "image/png"),
        ("JPEG", "photo.jpg", "image/jpeg", "image/jpeg"),
        ("WEBP", "photo.webp", "image/webp", "image/webp"),
        ("TIFF", "photo.tiff", "image/tiff", "image/tiff"),
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
    assert set(body) == {
        "imageId",
        "originalName",
        "width",
        "height",
        "exifOrientation",
        "mimeType",
        "bytes",
    }
    assert body["originalName"] == filename
    assert body["width"] == 80
    assert body["height"] == 60
    assert body["exifOrientation"] == 1
    assert body["mimeType"] == expected_mime
    assert body["bytes"] == len(payload)

    original = client.get(f"/api/v1/images/{body['imageId']}/original")
    assert original.status_code == 200
    assert original.headers["content-type"] == expected_mime
    assert original.headers["x-content-type-options"] == "nosniff"
    assert "inline" in original.headers["content-disposition"]
    assert original.content == payload


def _png16(size: tuple[int, int] = (64, 48)) -> bytes:
    width, height = size
    values = np.zeros((height, width, 3), dtype=np.uint16)
    values[..., 0] = np.linspace(0, 65535, width, dtype=np.uint16)[None, :]
    success, encoded = cv2.imencode(".png", np.ascontiguousarray(values[..., ::-1]))
    assert bool(success)
    return encoded.tobytes()


def _tiff16(size: tuple[int, int] = (64, 48)) -> bytes:
    width, height = size
    values = np.zeros((height, width, 3), dtype=np.uint16)
    values[..., 1] = np.linspace(0, 65535, width, dtype=np.uint16)[None, :]
    buffer = io.BytesIO()
    tifffile.imwrite(buffer, values, photometric="rgb", compression="deflate")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "content_type", "builder"),
    [
        ("photo16.png", "image/png", _png16),
        ("photo16.tiff", "image/tiff", _tiff16),
    ],
)
def test_upload_accepts_16_bit_png_and_tiff(
    client: TestClient,
    filename: str,
    content_type: str,
    builder,
):
    payload = builder()

    response = upload(client, payload, filename, content_type)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mimeType"] == content_type
    assert (body["width"], body["height"]) == (64, 48)
    assert body["bytes"] == len(payload)
    original = client.get(f"/api/v1/images/{body['imageId']}/original")
    assert original.status_code == 200
    assert original.content == payload


def test_upload_rejects_unsupported_tiff_compression(client: TestClient):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 80, 40)).save(buffer, format="TIFF", compression="tiff_lzw")

    response = upload(client, buffer.getvalue(), "photo.tiff", "image/tiff")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_tiff_compression"


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16], ids=["8-bit", "16-bit"])
def test_upload_rejects_tiff_associated_alpha(client: TestClient, dtype):
    values = np.full((4, 4, 4), 128, dtype=dtype)
    buffer = io.BytesIO()
    tifffile.imwrite(buffer, values, photometric="rgb", extrasamples=["assocalpha"])

    response = upload(client, buffer.getvalue(), "premultiplied.tiff", "image/tiff")

    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "associated_alpha_not_supported"
    assert error["details"]["extraSamples"] == [1]


def test_upload_rejects_multi_page_tiff(client: TestClient):
    frames = [Image.new("RGB", (8, 8), color) for color in ((255, 0, 0), (0, 255, 0))]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="TIFF", save_all=True, append_images=frames[1:])

    response = upload(client, buffer.getvalue(), "photo.tiff", "image/tiff")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "tiff_multipage_not_supported"


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


def test_registry_sha256_and_size_match_uploaded_bytes(client: TestClient, settings: Settings):
    payload = make_image("PNG", size=(96, 64), noise=True)
    image_id = upload(client, payload).json()["imageId"]

    record = image_row(settings, image_id)

    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["bytes"] == len(payload)


def test_rejects_multiple_files_in_single_field(client: TestClient):
    payload = make_image("PNG")

    response = client.post(
        "/api/v1/images",
        files=[
            ("file", ("first.png", payload, "image/png")),
            ("file", ("second.png", payload, "image/png")),
        ],
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_upload"
    assert body["error"]["details"]["fileCount"] == 2


def test_png_with_trailing_markup_is_served_as_nosniff_image(client: TestClient):
    payload = make_image("PNG") + b"\n<html><script>alert('x')</script></html>"

    response = upload(client, payload)

    assert response.status_code == 201
    original = client.get(f"/api/v1/images/{response.json()['imageId']}/original")
    assert original.status_code == 200
    assert original.headers["content-type"] == "image/png"
    assert original.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in original.headers["content-security-policy"]
    assert original.content == payload


@pytest.mark.parametrize(
    ("filename", "content_type", "payload"),
    [
        ("photo.gif", "image/gif", make_image("GIF")),
        ("photo.bmp", "image/bmp", make_image("BMP")),
        (
            "vector.svg",
            "image/svg+xml",
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>',
        ),
    ],
)
def test_rejects_non_supported_formats(
    client: TestClient,
    filename: str,
    content_type: str,
    payload: bytes,
):
    response = upload(client, payload, filename, content_type)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_logs_redact_original_filename_and_image_bytes(client: TestClient, caplog):
    marker = b"UPLOADED_IMAGE_BYTES_SECRET"
    payload = make_image("PNG") + marker

    with caplog.at_level(logging.DEBUG):
        response = upload(client, payload, filename="SECRET_NAME.png")

    assert response.status_code == 201
    assert "SECRET_NAME" not in caplog.text
    assert marker.decode("ascii") not in caplog.text


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


@pytest.mark.parametrize(
    ("payload", "filename", "declared_type", "detected_type"),
    [
        (make_image("JPEG"), "fake.png", "image/png", "image/jpeg"),
        (make_image("PNG"), "fake.jpg", "image/jpeg", "image/png"),
    ],
)
def test_rejects_spoofed_mime_type(
    client: TestClient,
    payload: bytes,
    filename: str,
    declared_type: str,
    detected_type: str,
):
    response = upload(client, payload, filename, declared_type)

    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "mime_mismatch"
    assert body["error"]["details"] == {
        "declaredMimeType": declared_type,
        "detectedMimeType": detected_type,
    }


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
        allowed_hosts="testserver",
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
        allowed_hosts="testserver",
        log_level="WARNING",
    )

    with TestClient(create_app(settings)) as test_client:
        response = upload(test_client, make_image("PNG", size=(64, 48)))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_many_pixels"
    assert response.json()["error"]["details"]["maxPixels"] == 1000


def test_library_lists_image_metadata_with_pagination(client: TestClient):
    uploaded = [
        upload(client, make_image("PNG", (64, 48), color), f"photo-{index}.png")
        for index, color in enumerate([(120, 80, 40), (40, 80, 120), (80, 120, 60)])
    ]
    assert all(response.status_code == 201 for response in uploaded)

    first = client.get("/api/v1/images?limit=2")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["images"]) == 2
    assert first_body["nextOffset"] == 2
    item = first_body["images"][0]
    assert set(item) == {
        "id",
        "originalName",
        "width",
        "height",
        "mimeType",
        "bytes",
        "createdAt",
    }
    assert "storageKey" not in item
    assert "sha256" not in item
    created = [entry["createdAt"] for entry in first_body["images"]]
    assert created == sorted(created, reverse=True)

    second = client.get(f"/api/v1/images?limit=2&offset={first_body['nextOffset']}")
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert len(second_body["images"]) == 1
    assert second_body["nextOffset"] is None
    ids = {entry["id"] for entry in first_body["images"]} | {
        entry["id"] for entry in second_body["images"]
    }
    assert ids == {str(response.json()["imageId"]) for response in uploaded}


def test_library_rejects_invalid_pagination(client: TestClient):
    assert client.get("/api/v1/images?limit=0").status_code == 422
    assert client.get("/api/v1/images?limit=201").status_code == 422
    assert client.get("/api/v1/images?offset=-1").status_code == 422


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
