"""Colour-management boundaries for the render pipeline (stage 4 Task 7).

Each expectation is pinned to a measured value: inputs that Pillow or OpenCV
cannot colour-manage must fall back to the documented sRGB assumption instead of
changing silently.
"""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image, ImageCms, ImageOps

from app.core.errors import AppError
from app.imaging.curves import apply_curves
from app.imaging.loader import LoadedImage, load_image, load_proxy
from app.imaging.pipeline import render
from app.imaging.tone import linear_to_srgb, srgb_to_linear
from app.models.recipe import Adjustments, CurvePoint, CurveSet
from tests.icc_support import build_display_p3_like_profile

P3_BYTES = build_display_p3_like_profile()
P3_PROFILE = ImageCms.ImageCmsProfile(io.BytesIO(P3_BYTES))
SRGB = ImageCms.createProfile("sRGB")
IMAGING_DIR = Path(__file__).resolve().parents[1] / "app" / "imaging"
LEVEL = np.float32(1.0 / 255.0)


def _p3_to_srgb(image: Image.Image) -> NDArray[np.float32]:
    converted = ImageCms.profileToProfile(
        image.convert("RGB"),
        P3_PROFILE,
        SRGB,
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        outputMode="RGB",
        flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
    )
    assert converted is not None
    return np.asarray(converted, dtype=np.float32) / 255.0


def _encode(
    image: Image.Image,
    *,
    fmt: str = "PNG",
    profile: bytes | None = None,
    exif: Image.Exif | None = None,
) -> bytes:
    options: dict[str, object] = {"format": fmt}
    if fmt == "JPEG":
        options["quality"] = 100
        options["subsampling"] = 0
    if fmt == "TIFF":
        options["compression"] = "tiff_lzw"
    if fmt == "WEBP":
        options["lossless"] = True
    if profile is not None:
        options["icc_profile"] = profile
    if exif is not None:
        options["exif"] = exif
    buffer = io.BytesIO()
    image.save(buffer, **options)
    return buffer.getvalue()


def _blocks() -> Image.Image:
    image = Image.new("RGB", (24, 8))
    for index, color in enumerate([(204, 51, 51), (51, 204, 51), (230, 160, 120)]):
        image.paste(color, (index * 8, 0, index * 8 + 8, 8))
    return image


def _gradient(height: int, width: int) -> NDArray[np.float32]:
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    fx = xx / max(width - 1, 1)
    fy = yy / max(height - 1, 1)
    return np.stack([fx, fy, 0.2 + 0.6 * fx * fy], axis=-1).astype(np.float32)


def _levels(array: NDArray[np.float32]) -> NDArray[np.float32]:
    return array / LEVEL


def test_palette_embedded_profile_is_converted_to_srgb() -> None:
    payload = _encode(_blocks().convert("P"), profile=P3_BYTES)

    loaded = load_image(payload).rgb

    with Image.open(io.BytesIO(payload)) as opened:
        rgb = opened.convert("RGB")
        reference = _p3_to_srgb(rgb)
        unconverted = np.asarray(rgb, dtype=np.float32) / 255.0
    assert np.abs(_levels(loaded - reference)).max() <= 1.0
    # Before Task 7 the profile was ignored for palette inputs: 37 levels off.
    assert np.abs(_levels(loaded - unconverted)).max() > 20.0


def test_one_bit_grayscale_and_la_inputs_are_managed_after_normalisation() -> None:
    for base in (
        Image.new("1", (8, 4), 1),
        Image.new("L", (8, 4), 200),
        Image.new("LA", (8, 4), (200, 255)),
    ):
        payload = _encode(base, profile=P3_BYTES)
        loaded = load_image(payload).rgb
        with Image.open(io.BytesIO(payload)) as opened:
            reference = _p3_to_srgb(opened.convert("RGB"))
        assert loaded.shape == (4, 8, 3)
        assert np.abs(_levels(loaded - reference)).max() <= 1.0


def test_opaque_rgba_matches_the_same_pixels_as_rgb() -> None:
    source = _blocks()
    opaque = source.convert("RGBA")

    loaded_rgb = load_image(_encode(source, profile=P3_BYTES)).rgb
    loaded_rgba = load_image(_encode(opaque, profile=P3_BYTES)).rgb

    assert np.abs(_levels(loaded_rgb - loaded_rgba)).max() <= 1.0


def test_non_rgb_device_profile_is_skipped_without_raising() -> None:
    lab_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB", 5000.0)).tobytes()
    payload = _encode(_blocks(), profile=lab_bytes)

    source_profile = ImageCms.ImageCmsProfile(io.BytesIO(lab_bytes))
    assert str(source_profile.profile.xcolor_space).strip().upper() != "RGB"
    with Image.open(io.BytesIO(payload)) as opened:
        expected = np.asarray(opened.convert("RGB"), dtype=np.float32) / 255.0

    assert np.array_equal(load_image(payload).rgb, expected)


@pytest.mark.parametrize(
    "profile",
    [b"not an icc profile", P3_BYTES[: len(P3_BYTES) // 2]],
)
def test_invalid_profiles_fall_back_to_the_srgb_assumption(profile: bytes) -> None:
    payload = _encode(_blocks(), profile=profile)

    with Image.open(io.BytesIO(payload)) as opened:
        expected = np.asarray(opened.convert("RGB"), dtype=np.float32) / 255.0

    assert np.abs(_levels(load_image(payload).rgb - expected)).max() <= 1.0


def test_untagged_input_defaults_to_srgb() -> None:
    payload = _encode(_blocks())

    with Image.open(io.BytesIO(payload)) as opened:
        assert "icc_profile" not in opened.info
        expected = np.asarray(opened.convert("RGB"), dtype=np.float32) / 255.0

    assert np.array_equal(load_image(payload).rgb, expected)


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_containers_get_identical_colour_management(image_format: str) -> None:
    source = Image.new("RGB", (24, 8), (204, 51, 51))

    loaded = load_image(_encode(source, fmt=image_format, profile=P3_BYTES)).rgb
    reference = load_image(_encode(source, fmt="PNG", profile=P3_BYTES)).rgb
    unconverted = np.float32([204, 51, 51]) / 255.0

    assert np.abs(_levels(loaded - reference)).max() <= 5.0
    assert np.abs(_levels(loaded - unconverted)).max() > 10.0


def test_jpeg_orientation_and_profile_are_applied_together() -> None:
    display = Image.new("RGB", (32, 16))
    for row in range(16):
        for column in range(32):
            display.putpixel((column, row), (column * 8, row * 16, 60))
    exif = Image.Exif()
    exif[0x0112] = 6
    payload = _encode(
        display.transpose(Image.Transpose.ROTATE_90),
        fmt="JPEG",
        profile=P3_BYTES,
        exif=exif,
    )

    loaded = load_image(payload)

    assert (loaded.width, loaded.height) == (32, 16)
    with Image.open(io.BytesIO(payload)) as opened:
        reference = _p3_to_srgb(ImageOps.exif_transpose(opened))
    assert np.abs(_levels(loaded.rgb - reference)).max() <= 4.0


def test_cmyk_with_an_rgb_device_profile_falls_back_without_raising() -> None:
    cmyk = Image.new("RGB", (8, 8), (200, 60, 60)).convert("CMYK")

    loaded = load_image(_encode(cmyk, fmt="TIFF", profile=P3_BYTES))

    assert loaded.rgb.shape == (8, 8, 3)
    assert np.abs(_levels(loaded.rgb - np.float32([200, 60, 60]) / 255.0)).max() <= 3.0


def test_16_bit_gray_keeps_float_precision_without_an_8_bit_step() -> None:
    values = np.array([[0, 65535], [32768, 1000]], dtype=np.uint16)
    buffer = io.BytesIO()
    Image.fromarray(values).save(buffer, format="PNG")

    loaded = load_image(buffer.getvalue()).rgb

    expected = values.astype(np.float32) / np.float32(65535.0)
    assert loaded.dtype == np.float32
    assert float(np.abs(loaded[..., 0] - expected).max()) <= 1e-6
    # An 8-bit intermediate would move 32768 to 128/255, i.e. by about 2e-3.
    assert abs(float(loaded[1, 0, 0]) - 32768 / 65535) < 1e-4


def test_16_bit_rgb_is_downconverted_at_decode_within_one_level(tmp_path: Path) -> None:
    values = np.zeros((8, 8, 3), dtype=np.uint16)
    for index in range(64):
        level = index * 65535 // 63
        row, column = divmod(index, 8)
        values[row, column] = (level, 65535 - level, 32768)
    path = tmp_path / "rgb16.png"
    # cv2.imwrite fails on non-ASCII Windows paths, so encode in memory.
    ok, encoded = cv2.imencode(".png", np.ascontiguousarray(values[:, :, ::-1]))
    assert bool(ok)
    path.write_bytes(encoded.tobytes())

    with Image.open(path) as opened:
        assert opened.mode == "RGB"  # Pillow has no 16-bit RGB mode.
    loaded = load_image(path).rgb

    reference = values.astype(np.float32) / np.float32(65535.0)
    assert np.abs(_levels(loaded - reference)).max() <= 1.0


def test_srgb_linear_round_trip_is_lossless_at_8_bit() -> None:
    values = np.arange(256, dtype=np.float32) / 255.0
    cube = np.ascontiguousarray(np.stack([values] * 3, axis=-1)[None, :, :])

    round_tripped = linear_to_srgb(srgb_to_linear(cube))

    assert round_tripped.dtype == np.float32
    assert float(np.abs(_levels(round_tripped - cube)).max()) <= 1e-4


@pytest.mark.parametrize(
    "module_name",
    [
        "pipeline.py",
        "tone.py",
        "color_ops.py",
        "curves.py",
        "hsl.py",
        "color_grading.py",
        "local.py",
        "local_masks.py",
        "geometry.py",
    ],
)
def test_render_stages_keep_float32(module_name: str) -> None:
    source = (IMAGING_DIR / module_name).read_text(encoding="utf-8")

    assert "astype(np.uint8)" not in source


def test_only_the_documented_sites_quantise_to_uint8() -> None:
    allowed = {"output.py", "detail.py", "loader.py", "analyzer.py"}

    found = {
        path.name
        for path in IMAGING_DIR.rglob("*.py")
        if "astype(np.uint8)" in path.read_text(encoding="utf-8")
    }

    assert found == allowed


STRONG_CURVE = CurveSet(
    master=(
        CurvePoint(x=0.0, y=0.0),
        CurvePoint(x=0.25, y=0.05),
        CurvePoint(x=0.5, y=0.95),
        CurvePoint(x=0.75, y=0.9),
        CurvePoint(x=1.0, y=1.0),
    )
)
CURLY_RECIPE = Adjustments(exposure_ev=0.7, contrast=40)
FIXTURE_SHA = "a" * 64


def test_proxy_quantisation_stays_below_visible_banding(tmp_path: Path) -> None:
    height, width, edge = 600, 800, 600
    smooth = _gradient(height, width)
    uint8 = np.clip(np.rint(smooth / LEVEL), 0, 255).astype(np.uint8)
    source_path = tmp_path / "smooth.png"
    Image.fromarray(uint8, "RGB").save(source_path, format="PNG")

    proxy = load_proxy(
        source_path.read_bytes(),
        original_sha256=FIXTURE_SHA,
        max_edge=edge,
        cache_dir=tmp_path / "proxies",
    )
    from_float = render(
        LoadedImage(rgb=np.ascontiguousarray(smooth)),
        CURLY_RECIPE,
        image_sha256=FIXTURE_SHA,
        curve=STRONG_CURVE,
        quality="final",
        max_edge=edge,
    )
    from_proxy = render(
        proxy,
        CURLY_RECIPE,
        image_sha256=FIXTURE_SHA,
        curve=STRONG_CURVE,
        quality="final",
        max_edge=edge,
    )

    assert from_float.rgb.shape == from_proxy.rgb.shape
    difference = np.abs(from_float.rgb.astype(np.int16) - from_proxy.rgb.astype(np.int16))
    assert int(difference.max()) <= 6
    assert float(difference.mean()) <= 1.0
    assert len(list((tmp_path / "proxies").glob("*.png"))) == 1


def test_strong_curve_bounds_input_quantisation_to_six_levels() -> None:
    smooth = _gradient(64, 512)
    quantised = np.clip(np.rint(smooth / LEVEL), 0, 255).astype(np.uint8).astype(np.float32) * LEVEL

    curved = apply_curves(np.ascontiguousarray(smooth), STRONG_CURVE)
    curved_quantised = apply_curves(np.ascontiguousarray(quantised), STRONG_CURVE)

    assert np.abs(_levels(curved - curved_quantised)).max() <= 6.0

    def peak_step(values: NDArray[np.float32]) -> float:
        return float(np.abs(np.diff(values)).max() / LEVEL)

    # The fixture ramp is finer than 8 bits, so quantisation aliases about two
    # columns per step and the curve doubles the visible step (2.6 -> 5.3 levels).
    assert peak_step(curved_quantised[0, :, 0]) <= 2.0 * peak_step(curved[0, :, 0]) + 1.0


def test_undecodable_payload_is_rejected() -> None:
    with pytest.raises(AppError) as error:
        load_image(b"\x00\x01\x02\x03")

    assert error.value.code == "invalid_image"
