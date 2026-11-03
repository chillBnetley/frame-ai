from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.core.errors import AppError
from app.imaging.loader import (
    load_image,
    load_proxy,
    proxy_cache_path,
    resize_to_max_edge,
)

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
QUADRANTS = (RED, GREEN, BLUE, YELLOW)


def _display_image(size: tuple[int, int] = (80, 50)) -> Image.Image:
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    half_w, half_h = size[0] // 2, size[1] // 2
    draw.rectangle((0, 0, half_w - 1, half_h - 1), fill=RED)
    draw.rectangle((half_w, 0, size[0] - 1, half_h - 1), fill=GREEN)
    draw.rectangle((0, half_h, half_w - 1, size[1] - 1), fill=BLUE)
    draw.rectangle((half_w, half_h, size[0] - 1, size[1] - 1), fill=YELLOW)
    return image


def _encode_orientation(orientation: int) -> bytes:
    display = _display_image()
    inverse = {
        1: None,
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_90,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_270,
    }[orientation]
    stored = display if inverse is None else display.transpose(inverse)
    exif = Image.Exif()
    exif[274] = orientation
    buffer = io.BytesIO()
    stored.save(buffer, format="PNG", exif=exif)
    return buffer.getvalue()


def _assert_color(pixel: np.ndarray, expected: tuple[int, int, int]) -> None:
    assert np.allclose(pixel, np.array(expected, dtype=np.float32) / 255.0, atol=2 / 255)


@pytest.mark.parametrize("orientation", range(1, 9))
def test_exif_orientation_is_normalized_to_display_order(orientation: int):
    loaded = load_image(_encode_orientation(orientation))

    assert (loaded.width, loaded.height) == (80, 50)
    assert loaded.rgb.dtype == np.float32
    _assert_color(loaded.rgb[12, 20], RED)
    _assert_color(loaded.rgb[12, 60], GREEN)
    _assert_color(loaded.rgb[37, 20], BLUE)
    _assert_color(loaded.rgb[37, 60], YELLOW)


def test_loading_does_not_modify_the_original_file(tmp_path: Path):
    payload = _encode_orientation(6)
    path = tmp_path / "photo.png"
    path.write_bytes(payload)
    before = hashlib.sha256(payload).hexdigest()

    load_image(path)
    load_image(path)

    assert path.read_bytes() == payload
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_grayscale_palette_and_alpha_modes_become_rgb_float32():
    grayscale = Image.new("L", (4, 3), 128)
    buffer = io.BytesIO()
    grayscale.save(buffer, format="PNG")
    loaded = load_image(buffer.getvalue())
    assert loaded.rgb.shape == (3, 4, 3)
    assert np.allclose(loaded.rgb, 128 / 255, atol=1 / 255)

    palette_source = Image.new("RGB", (3, 1))
    palette_source.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    palette = palette_source.convert("P")
    buffer = io.BytesIO()
    palette.save(buffer, format="PNG")
    loaded_palette = load_image(buffer.getvalue())
    expected = np.asarray(palette.convert("RGB"), dtype=np.float32) / 255.0
    assert np.array_equal(loaded_palette.rgb, expected)

    rgba = Image.new("RGBA", (2, 1))
    rgba.putdata([(255, 0, 0, 255), (0, 0, 0, 0)])
    buffer = io.BytesIO()
    rgba.save(buffer, format="PNG")
    loaded_alpha = load_image(buffer.getvalue())
    _assert_color(loaded_alpha.rgb[0, 0], RED)
    _assert_color(loaded_alpha.rgb[0, 1], (255, 255, 255))


def test_16_bit_grayscale_preserves_its_range():
    values = np.array([[0, 65535], [32768, 1000]], dtype=np.uint16)
    buffer = io.BytesIO()
    Image.fromarray(values).save(buffer, format="PNG")

    loaded = load_image(buffer.getvalue())

    assert loaded.rgb.dtype == np.float32
    assert loaded.rgb.shape == (2, 2, 3)
    assert np.allclose(loaded.rgb[..., 0], values.astype(np.float32) / 65535, atol=1 / 65535)
    assert np.allclose(loaded.rgb[..., 0], loaded.rgb[..., 1])
    assert np.allclose(loaded.rgb[..., 1], loaded.rgb[..., 2])


def test_cmyk_jpeg_becomes_rgb():
    buffer = io.BytesIO()
    Image.new("CMYK", (8, 8), (0, 255, 255, 0)).save(buffer, format="JPEG", quality=100)

    loaded = load_image(buffer.getvalue())

    assert loaded.rgb.dtype == np.float32
    pixel = loaded.rgb[4, 4]
    assert pixel[0] > 0.8
    assert pixel[1] < 0.2
    assert pixel[2] < 0.2


def test_pixel_limit_and_invalid_payloads_are_rejected():
    payload = _encode_orientation(1)

    with pytest.raises(AppError) as oversized:
        load_image(payload, max_pixels=100)
    assert oversized.value.code == "image_too_many_pixels"

    with pytest.raises(AppError) as corrupt:
        load_image(b"not an image")
    assert corrupt.value.code == "invalid_image"


def test_animated_images_are_rejected():
    frames = [Image.new("RGB", (8, 8), color) for color in (RED, GREEN)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])

    with pytest.raises(AppError) as animated:
        load_image(buffer.getvalue())

    assert animated.value.code == "animated_not_supported"


def test_resize_to_max_edge_preserves_aspect_ratio():
    loaded = load_image(_encode_orientation(1))

    resized = resize_to_max_edge(loaded, 40)

    assert (resized.width, resized.height) == (40, 25)
    assert resized.rgb.dtype == np.float32
    assert 0.0 <= float(resized.rgb.min())
    assert float(resized.rgb.max()) <= 1.0


def test_proxy_is_cached_and_survives_original_removal(tmp_path: Path):
    payload = _encode_orientation(6)
    original = tmp_path / "photo.png"
    original.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"

    first = load_proxy(
        original,
        original_sha256=digest,
        max_edge=40,
        cache_dir=cache_dir,
    )
    cache_file = proxy_cache_path(cache_dir, digest, 40)

    assert (first.width, first.height) == (40, 25)
    assert cache_file.is_file()
    _assert_color(first.rgb[3, 10], RED)

    with Image.open(cache_file) as cached:
        assert len(cached.getexif()) == 0
        assert cached.format == "PNG"

    original.unlink()
    second = load_proxy(
        original,
        original_sha256=digest,
        max_edge=40,
        cache_dir=cache_dir,
    )
    assert np.array_equal(first.rgb, second.rgb)


def test_proxy_does_not_cache_images_within_the_edge_limit(tmp_path: Path):
    payload = _encode_orientation(1)
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"

    loaded = load_proxy(
        payload,
        original_sha256=digest,
        max_edge=200,
        cache_dir=cache_dir,
    )

    assert (loaded.width, loaded.height) == (80, 50)
    assert not cache_dir.exists()


def test_corrupt_proxy_cache_is_rebuilt(tmp_path: Path):
    payload = _encode_orientation(1)
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_file = proxy_cache_path(cache_dir, digest, 40)
    cache_file.write_bytes(b"broken")

    loaded = load_proxy(
        payload,
        original_sha256=digest,
        max_edge=40,
        cache_dir=cache_dir,
    )

    assert (loaded.width, loaded.height) == (40, 25)
    with Image.open(cache_file) as cached:
        assert cached.format == "PNG"


def test_proxy_cache_key_validates_hash_and_edge(tmp_path: Path):
    with pytest.raises(ValueError):
        proxy_cache_path(tmp_path, "not-a-digest", 40)
    with pytest.raises(ValueError):
        proxy_cache_path(tmp_path, "a" * 62, 40)
    with pytest.raises(ValueError):
        proxy_cache_path(tmp_path, "a" * 64, 0)

    first = proxy_cache_path(tmp_path, "a" * 64, 40)
    same_bucket = proxy_cache_path(tmp_path, "a" * 64, 41)
    next_bucket = proxy_cache_path(tmp_path, "a" * 64, 65)
    third = proxy_cache_path(tmp_path, "b" * 64, 40)
    assert first == same_bucket
    assert len({first, next_bucket, third}) == 3


def test_proxy_cache_hit_refreshes_mtime(tmp_path: Path):
    payload = _encode_orientation(1)
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"
    load_proxy(payload, original_sha256=digest, max_edge=40, cache_dir=cache_dir)
    cache_file = proxy_cache_path(cache_dir, digest, 40)
    old = time.time() - 7200
    os.utime(cache_file, (old, old))

    load_proxy(payload, original_sha256=digest, max_edge=40, cache_dir=cache_dir)

    assert cache_file.stat().st_mtime >= time.time() - 5


def test_proxy_write_failure_does_not_fail_the_render(tmp_path: Path, monkeypatch):
    payload = _encode_orientation(1)
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"

    def fail_replace(_source: str | os.PathLike[str], _target: str | os.PathLike[str]) -> None:
        raise PermissionError("cache file is locked")

    monkeypatch.setattr("app.imaging.loader.os.replace", fail_replace)

    loaded = load_proxy(
        payload,
        original_sha256=digest,
        max_edge=40,
        cache_dir=cache_dir,
    )

    assert (loaded.width, loaded.height) == (40, 25)
    assert list(cache_dir.glob("*.png")) == []
