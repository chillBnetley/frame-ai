from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def make_image(
    image_format: str = "PNG",
    size: tuple[int, int] = (64, 48),
    color: tuple[int, int, int] = (120, 80, 40),
    noise: bool = False,
) -> bytes:
    mode = "RGB"
    if noise:
        pixels = os.urandom(size[0] * size[1] * 3)
        image = Image.frombytes(mode, size, pixels)
    else:
        image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def upload(
    client: TestClient,
    payload: bytes,
    filename: str = "photo.png",
    content_type: str = "image/png",
):
    return client.post("/api/v1/images", files={"file": (filename, payload, content_type)})
