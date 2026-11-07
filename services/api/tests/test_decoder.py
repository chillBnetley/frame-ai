from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import tifffile
from fastapi.testclient import TestClient
from PIL import Image

from app.core.errors import AppError
from app.imaging.decoder import inspect_image
from tests.conftest import make_image, upload


@pytest.mark.parametrize("bit_depth", [8, 16])
@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_tiff_orientation_metadata_matches_the_rendered_preview(
    client: TestClient,
    orientation: int,
    bit_depth: int,
):
    dtype = np.uint8 if bit_depth == 8 else np.uint16
    # Stored as 4x2 (width x height); both orientations display as 2x4.
    pixels = np.zeros((2, 4, 3), dtype=dtype)
    pixels[0, :, 0] = np.array([0, 80, 160, 255], dtype=dtype)
    pixels[1, :, 1] = np.array([255, 160, 80, 0], dtype=dtype)
    buffer = io.BytesIO()
    tifffile.imwrite(
        buffer,
        pixels,
        photometric="rgb",
        compression="deflate",
        extratags=[(274, "H", 1, orientation, False)],
    )

    response = upload(client, buffer.getvalue(), "rotated.tiff", "image/tiff")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["exifOrientation"] == orientation
    assert (body["width"], body["height"]) == (2, 4)

    session = client.post("/api/v1/sessions", json={"imageId": body["imageId"]})
    assert session.status_code == 201, session.text
    rendered = client.post(
        f"/api/v1/sessions/{session.json()['sessionId']}/render",
        json={"recipe": {}, "quality": "final"},
    )
    assert rendered.status_code == 200, rendered.text
    assert (rendered.json()["width"], rendered.json()["height"]) == (2, 4)

    preview = client.get(str(rendered.json()["previewUrl"]))
    assert preview.status_code == 200
    with Image.open(io.BytesIO(preview.content)) as image:
        assert image.size == (2, 4)


@pytest.mark.parametrize("orientation", range(1, 9))
def test_exif_orientation_controls_display_dimensions(client: TestClient, orientation: int):
    payload = make_image(
        "JPEG",
        size=(320, 200),
        exif_orientation=orientation,
    )

    response = upload(client, payload, "rotated.jpg", "image/jpeg")

    assert response.status_code == 201
    body = response.json()
    assert body["exifOrientation"] == orientation
    if orientation in {5, 6, 7, 8}:
        assert (body["width"], body["height"]) == (200, 320)
    else:
        assert (body["width"], body["height"]) == (320, 200)


def test_rejects_animated_webp(client: TestClient):
    frames = [Image.new("RGB", (64, 48), color) for color in ((255, 0, 0), (0, 0, 255))]
    buffer = io.BytesIO()
    frames[0].save(
        buffer,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )

    response = upload(client, buffer.getvalue(), "animated.webp", "image/webp")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "animated_not_supported"


def test_rejects_truncated_jpeg(client: TestClient):
    payload = make_image("JPEG", size=(256, 192), noise=True)
    truncated = payload[: len(payload) // 2]

    response = upload(client, truncated, "broken.jpg", "image/jpeg")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_image"


@pytest.mark.parametrize(
    ("mode", "image_format", "color", "filename", "content_type"),
    [
        ("L", "PNG", 128, "gray.png", "image/png"),
        ("P", "PNG", 0, "palette.png", "image/png"),
        ("RGBA", "PNG", (10, 20, 30, 128), "alpha.png", "image/png"),
        ("CMYK", "JPEG", (0, 128, 128, 0), "cmyk.jpg", "image/jpeg"),
        ("I;16", "PNG", 1000, "sixteen.png", "image/png"),
    ],
)
def test_accepts_common_color_modes(
    client: TestClient,
    mode: str,
    image_format: str,
    color,
    filename: str,
    content_type: str,
):
    payload = make_image(
        image_format,
        size=(64, 48),
        color=color,
        mode=mode,
    )

    response = upload(client, payload, filename, content_type)

    assert response.status_code == 201
    body = response.json()
    assert (body["width"], body["height"]) == (64, 48)


def test_pixel_bomb_is_rejected_before_decode(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bomb = make_image("PNG", size=(9000, 9000), color=1, mode="1")
    assert len(bomb) < 1_000_000

    def fail_load(self: Image.Image) -> None:
        raise AssertionError("the bomb must be rejected before load")

    monkeypatch.setattr(Image.Image, "load", fail_load)

    response = upload(client, bomb, "bomb.png", "image/png")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_many_pixels"


def test_decoder_rejects_pixel_limit_without_loading(tmp_path: Path, monkeypatch):
    bomb = make_image("PNG", size=(9000, 9000), color=1, mode="1")

    def fail_load(self: Image.Image) -> None:
        raise AssertionError("the bomb must be rejected before load")

    monkeypatch.setattr(Image.Image, "load", fail_load)

    with pytest.raises(AppError) as raised:
        inspect_image(bomb, "image/png", max_pixels=1_000_000)

    assert raised.value.status_code == 413
    assert raised.value.code == "image_too_many_pixels"
