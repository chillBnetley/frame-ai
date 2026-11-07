from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms

from app.analysis import preprocessing
from app.analysis.preprocessing import (
    ALPHA_LIMITATION,
    PreprocessedImage,
    preprocess_image,
    preprocess_original,
)
from app.core.errors import AppError
from app.services.image_service import ImageService
from tests.conftest import make_image, upload
from tests.icc_support import build_display_p3_like_profile

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)

INVERSE_ORIENTATION = {
    1: None,
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_90,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_270,
}


def _encode(image: Image.Image, image_format: str = "PNG", **options: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def _write(tmp_path: Path, payload: bytes, name: str = "photo.png") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def _run(
    path: Path,
    *,
    display_width: int,
    display_height: int,
    exif_orientation: int = 1,
    max_edge: int = 512,
    max_pixels: int = 40_000_000,
) -> PreprocessedImage:
    return preprocess_original(
        path,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        display_width=display_width,
        display_height=display_height,
        exif_orientation=exif_orientation,
        max_edge=max_edge,
        max_pixels=max_pixels,
    )


def _model_image(result: PreprocessedImage) -> Image.Image:
    with Image.open(io.BytesIO(result.image.data)) as opened:
        opened.load()
        return opened.copy()


def test_output_is_memory_jpeg_without_metadata_and_original_is_untouched(tmp_path: Path):
    payload = make_image("PNG", size=(64, 48), color=(120, 80, 40))
    path = _write(tmp_path, payload)
    before = hashlib.sha256(payload).hexdigest()

    result = _run(path, display_width=64, display_height=48)

    assert result.image.mime_type == "image/jpeg"
    assert result.image.data.startswith(b"\xff\xd8")
    assert result.original_sha256 == before
    assert result.had_alpha is False
    assert result.limitations == ()
    assert path.read_bytes() == payload
    assert sorted(item.name for item in tmp_path.iterdir()) == ["photo.png"]

    with Image.open(io.BytesIO(result.image.data)) as model:
        assert model.format == "JPEG"
        assert model.size == (64, 48)
        assert len(model.getexif()) == 0
        assert "exif" not in model.info
        assert "icc_profile" not in model.info


def test_long_edge_is_scaled_without_upscaling(tmp_path: Path):
    wide = _write(tmp_path, make_image("PNG", size=(1200, 300)), "wide.png")
    small = _write(tmp_path, make_image("PNG", size=(100, 50)), "small.png")

    wide_result = _run(wide, display_width=1200, display_height=300, max_edge=512)
    small_result = _run(small, display_width=100, display_height=50, max_edge=512)

    assert (wide_result.image.width, wide_result.image.height) == (512, 128)
    assert (small_result.image.width, small_result.image.height) == (100, 50)


def test_transparent_png_is_composited_to_white_and_reported(tmp_path: Path):
    image = Image.new("RGBA", (8, 4))
    image.paste((255, 0, 0, 255), (0, 0, 4, 4))
    image.paste((0, 0, 0, 0), (4, 0, 8, 4))
    path = _write(tmp_path, _encode(image))

    result = _run(path, display_width=8, display_height=4, max_edge=512)

    assert result.had_alpha is True
    assert result.limitations == (ALPHA_LIMITATION,)
    model = _model_image(result).convert("RGB")
    left = np.asarray(model)[1, 1]
    right = np.asarray(model)[1, 6]
    assert left[0] > 230 and left[1] < 30 and left[2] < 30
    assert np.all(right > 245)


def test_exif_orientation_is_applied_and_stripped(tmp_path: Path):
    display = Image.new("RGB", (12, 8))
    display.paste(RED, (0, 0, 6, 4))
    display.paste(GREEN, (6, 0, 12, 4))
    display.paste(BLUE, (0, 4, 6, 8))
    display.paste(YELLOW, (6, 4, 12, 8))
    inverse = INVERSE_ORIENTATION[6]
    stored = display if inverse is None else display.transpose(inverse)
    exif = Image.Exif()
    exif[274] = 6
    path = _write(tmp_path, _encode(stored, exif=exif))

    result = _run(
        path,
        display_width=12,
        display_height=8,
        exif_orientation=6,
        max_edge=512,
    )

    assert (result.image.width, result.image.height) == (12, 8)
    assert result.exif_orientation == 6
    model = np.asarray(_model_image(result).convert("RGB"))
    assert model[2, 2, 0] > 230 and model[2, 2, 1] < 30
    assert model[2, 9, 1] > 230 and model[2, 9, 0] < 30
    with Image.open(io.BytesIO(result.image.data)) as opened:
        assert len(opened.getexif()) == 0


def test_embedded_icc_profile_is_converted_to_srgb(tmp_path: Path):
    profile_bytes = build_display_p3_like_profile()
    image = Image.new("RGB", (16, 16), (200, 60, 60))
    path = _write(tmp_path, _encode(image, icc_profile=profile_bytes))

    result = _run(path, display_width=16, display_height=16, max_edge=512)

    source_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
    expected = ImageCms.profileToProfile(
        image,
        source_profile,
        ImageCms.createProfile("sRGB"),
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        outputMode="RGB",
        flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
    )
    assert expected is not None
    expected_pixel = np.asarray(expected)[8, 8].astype(np.float32)
    actual_pixel = np.asarray(_model_image(result).convert("RGB"))[8, 8].astype(np.float32)
    assert np.abs(actual_pixel - expected_pixel).max() <= 6


def test_empty_corrupt_and_oversized_files_are_rejected(tmp_path: Path):
    empty = _write(tmp_path, b"", "empty.png")
    with pytest.raises(AppError) as empty_error:
        _run(empty, display_width=1, display_height=1)
    assert empty_error.value.code == "empty_file"

    corrupt = _write(tmp_path, b"not an image", "corrupt.png")
    with pytest.raises(AppError) as corrupt_error:
        _run(corrupt, display_width=1, display_height=1)
    assert corrupt_error.value.code == "invalid_image"

    oversized = _write(tmp_path, make_image("PNG", size=(64, 48)), "large.png")
    with pytest.raises(AppError) as pixel_error:
        _run(oversized, display_width=64, display_height=48, max_pixels=100)
    assert pixel_error.value.code == "image_too_many_pixels"


def test_hash_mismatch_before_reading_is_rejected(tmp_path: Path):
    path = _write(tmp_path, make_image("PNG", size=(16, 16)))

    with pytest.raises(AppError) as error:
        preprocess_original(
            path,
            expected_sha256="0" * 64,
            display_width=16,
            display_height=16,
            exif_orientation=1,
            max_edge=512,
            max_pixels=1_000_000,
        )

    assert error.value.code == "original_changed"


def test_hash_change_during_reading_is_rejected(tmp_path: Path, monkeypatch):
    path = _write(tmp_path, make_image("PNG", size=(16, 16)))
    original_load = preprocessing.load_image

    def tampering_load(
        source: Path,
        *,
        max_pixels: int | None = None,
        preserve_alpha: bool = True,
    ):
        loaded = original_load(
            source,
            max_pixels=max_pixels,
            preserve_alpha=preserve_alpha,
        )
        path.write_bytes(b"replaced while reading")
        return loaded

    monkeypatch.setattr(preprocessing, "load_image", tampering_load)

    with pytest.raises(AppError) as error:
        _run(path, display_width=16, display_height=16)

    assert error.value.code == "original_changed"


@pytest.mark.parametrize("max_edge", [511, 2049])
def test_max_edge_is_bounded(tmp_path: Path, max_edge: int):
    path = _write(tmp_path, make_image("PNG", size=(16, 16)))

    with pytest.raises(ValueError, match="max_edge"):
        _run(path, display_width=16, display_height=16, max_edge=max_edge)


def test_service_lookup_uses_the_stored_record(client, settings):
    response = upload(client, make_image("PNG", size=(80, 60)))
    assert response.status_code == 201
    image_id = response.json()["imageId"]

    result = preprocess_image(
        ImageService(settings),
        image_id,
        max_edge=512,
        max_pixels=settings.max_image_pixels,
    )

    assert (result.image.width, result.image.height) == (80, 60)
    assert result.original_width == 80
    assert result.original_height == 60


def test_preprocessed_copy_rejects_an_oversized_limit(tmp_path: Path):
    payload = _encode(Image.new("RGB", (640, 480), (120, 80, 40)))
    path = _write(tmp_path, payload)

    with pytest.raises(AppError) as excinfo:
        preprocess_original(
            path,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            display_width=640,
            display_height=480,
            exif_orientation=1,
            max_edge=512,
            max_pixels=40_000_000,
            max_bytes=1,
        )

    assert excinfo.value.status_code == 413
    assert excinfo.value.code == "analysis_input_too_large"
