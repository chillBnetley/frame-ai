from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.imaging.local_masks import configure_mask_cache
from app.main import create_app
from app.repositories.db import connect


@pytest.fixture(autouse=True)
def isolated_mask_cache() -> Iterator[None]:
    # The weight cache is process-global and create_app() sizes it from
    # settings; reset it so one test never inherits another's entries.
    configure_mask_cache(0)
    yield
    configure_mask_cache(0)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        log_level="WARNING",
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def make_image(
    image_format: str = "PNG",
    size: tuple[int, int] = (64, 48),
    color: tuple[int, ...] | int = (120, 80, 40),
    noise: bool = False,
    mode: str = "RGB",
    exif_orientation: int | None = None,
) -> bytes:
    if noise:
        pixels = os.urandom(size[0] * size[1] * 3)
        image = Image.frombytes("RGB", size, pixels)
    else:
        image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    save_kwargs: dict[str, object] = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        save_kwargs["exif"] = exif
    image.save(buffer, format=image_format, **save_kwargs)
    return buffer.getvalue()


def upload(
    client: TestClient,
    payload: bytes,
    filename: str = "photo.png",
    content_type: str = "image/png",
):
    return client.post("/api/v1/images", files={"file": (filename, payload, content_type)})


def image_row(settings: Settings, image_id: str) -> dict[str, object]:
    connection = connect(settings.database_path)
    try:
        row = connection.execute(
            "SELECT * FROM image_asset WHERE id = ?",
            (image_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return dict(row)
