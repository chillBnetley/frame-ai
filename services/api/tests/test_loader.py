from __future__ import annotations

import hashlib
import io
import os
import struct
import time
import zlib
from pathlib import Path

import cv2
import numpy as np
import pytest
import tifffile
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


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_grayscale_and_palette_modes_become_rgb_float32():
    grayscale = Image.new("L", (4, 3), 128)
    loaded = load_image(_png(grayscale))
    assert loaded.rgb.shape == (3, 4, 3)
    assert np.allclose(loaded.rgb, 128 / 255, atol=1 / 255)
    assert loaded.alpha is None

    palette_source = Image.new("RGB", (3, 1))
    palette_source.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    palette = palette_source.convert("P")
    loaded_palette = load_image(_png(palette))
    expected = np.asarray(palette.convert("RGB"), dtype=np.float32) / 255.0
    assert np.array_equal(loaded_palette.rgb, expected)
    assert loaded_palette.alpha is None


def test_rgba_input_splits_alpha_without_white_compositing():
    rgba = Image.new("RGBA", (3, 1))
    rgba.putdata([(255, 0, 0, 255), (0, 255, 0, 128), (0, 0, 0, 0)])

    loaded = load_image(_png(rgba))

    assert loaded.alpha is not None
    assert loaded.alpha.shape == (1, 3)
    assert loaded.alpha.dtype == np.float32
    _assert_color(loaded.rgb[0, 0], RED)
    # A semi-transparent pixel keeps its own colour; it is not mixed with white.
    assert np.allclose(loaded.rgb[0, 1], np.array([0, 1, 0], dtype=np.float32), atol=1 / 255)
    assert np.allclose(loaded.alpha[0], np.array([1.0, 128 / 255, 0.0]), atol=1 / 255)


def test_alpha_can_still_be_composited_for_opaque_consumers():
    rgba = Image.new("RGBA", (2, 1))
    rgba.putdata([(255, 0, 0, 255), (0, 0, 0, 0)])

    loaded = load_image(_png(rgba), preserve_alpha=False)

    assert loaded.alpha is None
    _assert_color(loaded.rgb[0, 0], RED)
    _assert_color(loaded.rgb[0, 1], (255, 255, 255))


def test_la_and_palette_transparency_become_alpha():
    la = Image.new("LA", (2, 1))
    la.putdata([(200, 255), (100, 64)])
    loaded_la = load_image(_png(la))
    assert loaded_la.alpha is not None
    assert np.allclose(loaded_la.rgb[0, :, 0], np.array([200 / 255, 100 / 255]), atol=1 / 255)
    assert np.allclose(loaded_la.alpha[0], np.array([1.0, 64 / 255]), atol=1 / 255)

    palette = Image.new("P", (2, 1))
    palette.putpalette([255, 0, 0, 0, 0, 0] + [0, 0, 0] * 254)
    palette.putdata([0, 1])
    palette.info["transparency"] = 1
    loaded_palette = load_image(_png(palette))
    assert loaded_palette.alpha is not None
    _assert_color(loaded_palette.rgb[0, 0], RED)
    assert np.allclose(loaded_palette.alpha[0], np.array([1.0, 0.0]))


def test_rgb_inputs_have_no_alpha_and_match_the_opaque_path():
    payload = _encode_orientation(1)

    split = load_image(payload)
    opaque = load_image(payload, preserve_alpha=False)

    assert split.alpha is None
    assert opaque.alpha is None
    assert np.array_equal(split.rgb, opaque.rgb)


def test_16_bit_grayscale_preserves_its_range():
    values = np.array([[0, 65535], [32768, 1000]], dtype=np.uint16)
    buffer = io.BytesIO()
    Image.fromarray(values).save(buffer, format="PNG")

    loaded = load_image(buffer.getvalue())

    assert loaded.alpha is None
    assert loaded.rgb.dtype == np.float32
    assert loaded.rgb.shape == (2, 2, 3)
    assert np.allclose(loaded.rgb[..., 0], values.astype(np.float32) / 65535, atol=1 / 65535)
    assert np.allclose(loaded.rgb[..., 0], loaded.rgb[..., 1])
    assert np.allclose(loaded.rgb[..., 1], loaded.rgb[..., 2])


def _insert_png_chunk(payload: bytes, kind: bytes, data: bytes) -> bytes:
    chunk = (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )
    # PNG signature (8) + IHDR (25) end at byte 33.
    return payload[:33] + chunk + payload[33:]


def _png16(
    values: np.ndarray,
    *,
    exif: Image.Exif | None = None,
) -> bytes:
    if values.shape[2] == 4:
        source = np.dstack([values[..., 2::-1], values[..., 3]])
    else:
        source = values[..., ::-1]
    success, encoded = cv2.imencode(".png", np.ascontiguousarray(source))
    assert bool(success)
    payload = encoded.tobytes()
    if exif is not None:
        payload = _insert_png_chunk(payload, b"eXIf", exif.tobytes())
    return payload


def _tiff16(values: np.ndarray, **options: object) -> bytes:
    buffer = io.BytesIO()
    tifffile.imwrite(
        buffer,
        np.ascontiguousarray(values),
        photometric="rgb",
        **options,
    )
    return buffer.getvalue()


def test_16_bit_rgb_png_preserves_samples_and_reports_depth():
    values = np.array([[[0, 511, 65535], [1000, 32768, 40000]]], dtype=np.uint16)

    loaded = load_image(_png16(values))

    assert loaded.bit_depth == 16
    assert loaded.alpha is None
    assert loaded.rgb.dtype == np.float32
    assert float(np.abs(loaded.rgb - values / 65535.0).max()) <= 1e-6


def test_16_bit_rgba_png_splits_alpha_and_composites_on_request():
    values = np.array(
        [[[1000, 2000, 3000, 0], [40000, 50000, 60000, 65535]]],
        dtype=np.uint16,
    )
    payload = _png16(values)

    loaded = load_image(payload)
    opaque = load_image(payload, preserve_alpha=False)

    assert loaded.bit_depth == 16
    assert loaded.alpha is not None
    assert float(np.abs(loaded.rgb - values[..., :3] / 65535.0).max()) <= 1e-6
    assert float(np.abs(loaded.alpha - values[..., 3] / 65535.0).max()) <= 1e-6
    coverage = values[..., 3:].astype(np.float32) / 65535.0
    expected = values[..., :3].astype(np.float32) / 65535.0 * coverage + (1.0 - coverage)
    assert opaque.alpha is None
    assert float(np.abs(opaque.rgb - expected).max()) <= 1e-6


@pytest.mark.parametrize("compression", [None, "deflate"])
def test_16_bit_tiff_rgb_round_trips(compression: str | None):
    values = np.array(
        [[[0, 511, 65535], [1000, 32768, 40000]]],
        dtype=np.uint16,
    )

    loaded = load_image(_tiff16(values, compression=compression))

    assert loaded.bit_depth == 16
    assert loaded.alpha is None
    assert float(np.abs(loaded.rgb - values / 65535.0).max()) <= 1e-6


def test_16_bit_tiff_rgba_splits_alpha():
    values = np.array(
        [[[1000, 2000, 3000, 0], [40000, 50000, 60000, 65535]]],
        dtype=np.uint16,
    )

    loaded = load_image(_tiff16(values, compression="deflate", extrasamples=["unassalpha"]))

    assert loaded.bit_depth == 16
    assert loaded.alpha is not None
    assert float(np.abs(loaded.rgb - values[..., :3] / 65535.0).max()) <= 1e-6
    assert float(np.abs(loaded.alpha - values[..., 3] / 65535.0).max()) <= 1e-6


@pytest.mark.parametrize(
    ("samples", "width"),
    [(3, 3), (3, 4), (4, 3), (4, 4)],
    ids=["rgb-w3", "rgb-w4", "rgba-w3", "rgba-w4"],
)
def test_16_bit_planar_separate_tiff_uses_tag_layout(samples: int, width: int):
    height = 5
    values = np.empty((samples, height, width), dtype=np.uint16)
    ramp = np.arange(height * width, dtype=np.uint16).reshape(height, width)
    for sample in range(3):
        values[sample] = ramp * 100 + sample * 10000 + 1
    if samples == 4:
        values[3] = ramp * 1000 + 7
    options: dict[str, object] = {"planarconfig": "separate"}
    if samples == 4:
        options["extrasamples"] = ["unassalpha"]

    loaded = load_image(_tiff16(values, **options))

    assert loaded.bit_depth == 16
    assert (loaded.width, loaded.height) == (width, height)
    expected = np.moveaxis(values[:3], 0, -1).astype(np.float32) / 65535.0
    assert np.allclose(loaded.rgb, expected, atol=1 / 65535)
    if samples == 4:
        assert loaded.alpha is not None
        assert np.allclose(loaded.alpha, values[3] / 65535.0, atol=1 / 65535)
    else:
        assert loaded.alpha is None


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16], ids=["8-bit", "16-bit"])
def test_tiff_associated_alpha_is_rejected(dtype):
    values = np.full((4, 4, 4), 128, dtype=dtype)
    values[..., 0] = 200
    buffer = io.BytesIO()
    tifffile.imwrite(buffer, values, photometric="rgb", extrasamples=["assocalpha"])

    with pytest.raises(AppError) as error:
        load_image(buffer.getvalue())

    assert error.value.status_code == 415
    assert error.value.code == "associated_alpha_not_supported"
    assert error.value.details["extraSamples"] == [1]
    assert "unassociated" in error.value.message


def test_16_bit_planar_tiff_shape_must_match_rgb_metadata():
    # With planarconfig=separate tifffile records the first axis as
    # SamplesPerPixel; five samples cannot be an RGB/RGBA image and must not be
    # reinterpreted from a coincidental trailing dimension.
    values = np.zeros((5, 3, 3), dtype=np.uint16)
    buffer = io.BytesIO()
    tifffile.imwrite(
        buffer,
        values,
        photometric="rgb",
        planarconfig="separate",
    )

    with pytest.raises(AppError) as error:
        load_image(buffer.getvalue())

    assert error.value.status_code == 415
    assert error.value.code == "invalid_image"


@pytest.mark.parametrize("compression", ["tiff_lzw", "jpeg"])
def test_tiff_rejects_compressions_outside_the_contract(compression: str):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 80, 40)).save(buffer, format="TIFF", compression=compression)

    with pytest.raises(AppError) as error:
        load_image(buffer.getvalue())

    assert error.value.status_code == 415
    assert error.value.code == "unsupported_tiff_compression"


def test_tiff_rejects_multiple_pages():
    frames = [Image.new("RGB", (8, 8), color) for color in (RED, GREEN)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="TIFF", save_all=True, append_images=frames[1:])

    with pytest.raises(AppError) as error:
        load_image(buffer.getvalue())

    assert error.value.status_code == 415
    assert error.value.code == "tiff_multipage_not_supported"


def _display16(size: tuple[int, int] = (80, 50)) -> np.ndarray:
    return np.asarray(_display_image(size), dtype=np.uint16) * 257


@pytest.mark.parametrize("orientation", range(1, 9))
def test_16_bit_png_exif_orientation_is_applied(orientation: int):
    display = _display16()
    inverse = {
        1: None,
        2: lambda array: array[:, ::-1],
        3: lambda array: array[::-1, ::-1],
        4: lambda array: array[::-1],
        5: lambda array: np.swapaxes(array, 0, 1),
        6: lambda array: np.rot90(array, 1),
        7: lambda array: np.flipud(np.fliplr(np.swapaxes(array, 0, 1))),
        8: lambda array: np.rot90(array, -1),
    }[orientation]
    stored = np.ascontiguousarray(display if inverse is None else inverse(display))
    exif = Image.Exif()
    exif[274] = orientation

    loaded = load_image(_png16(stored, exif=exif))

    assert loaded.bit_depth == 16
    assert (loaded.width, loaded.height) == (80, 50)
    for (row, column), color in (
        ((12, 20), RED),
        ((12, 60), GREEN),
        ((37, 20), BLUE),
        ((37, 60), YELLOW),
    ):
        expected = np.array(color, dtype=np.float32) / 255.0
        assert np.allclose(loaded.rgb[row, column], expected, atol=2 / 65535)


def test_resize_to_max_edge_preserves_the_16_bit_flag():
    loaded = load_image(_png16(_display16((160, 100))))

    resized = resize_to_max_edge(loaded, 80)

    assert loaded.bit_depth == 16
    assert resized.bit_depth == 16
    assert (resized.width, resized.height) == (80, 50)


def test_proxy_for_16_bit_source_uses_a_separate_cache_entry(tmp_path: Path):
    payload = _png16(_display16((160, 100)))
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"

    proxy = load_proxy(payload, original_sha256=digest, max_edge=40, cache_dir=cache_dir)
    sixteen_key = proxy_cache_path(cache_dir, digest, 40, bit_depth=16)
    eight_key = proxy_cache_path(cache_dir, digest, 40, bit_depth=8)

    assert proxy.bit_depth == 8  # proxies stay RGB PNG at 8 bits
    assert (proxy.width, proxy.height) == (40, 25)
    assert sixteen_key.is_file()
    assert not eight_key.exists()
    assert sixteen_key != eight_key
    with Image.open(sixteen_key) as cached:
        assert cached.mode == "RGB"


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
    assert resized.alpha is None
    assert 0.0 <= float(resized.rgb.min())
    assert float(resized.rgb.max()) <= 1.0


def test_resize_to_max_edge_scales_alpha_without_colour_bleed():
    rgba = Image.new("RGBA", (4, 2), (255, 0, 0, 0))
    rgba.putpixel((0, 0), (255, 0, 0, 255))
    rgba.putpixel((1, 0), (255, 0, 0, 255))
    loaded = load_image(_png(rgba))

    resized = resize_to_max_edge(loaded, 2)

    assert (resized.width, resized.height) == (2, 1)
    assert resized.alpha is not None
    # The transparent half must stay transparent; its premultiplied colour must
    # not pull the opaque half toward black.
    assert resized.alpha[0, 0] > 0.0
    assert resized.alpha[0, 1] == 0.0
    assert resized.rgb[0, 0, 0] > 0.99
    assert 0.0 <= float(resized.rgb.min()) <= float(resized.rgb.max()) <= 1.0


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
