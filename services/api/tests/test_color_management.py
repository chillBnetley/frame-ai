"""Colour-management boundaries for the render pipeline (stage 4 Task 7).

Each expectation is pinned to a measured value: inputs that Pillow or OpenCV
cannot colour-manage must fall back to the documented sRGB assumption instead of
changing silently.
"""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

import cv2
import numpy as np
import pytest
import tifffile
from numpy.typing import NDArray
from PIL import Image, ImageCms, ImageOps

from app.core.errors import AppError
from app.imaging.curves import apply_curves
from app.imaging.icc import UnsupportedProfileError, is_srgb_matrix_trc, transform_to_srgb
from app.imaging.loader import LoadedImage, load_image, load_proxy
from app.imaging.output import encode_image, to_uint16
from app.imaging.pipeline import render
from app.imaging.tone import linear_to_srgb, srgb_to_linear
from app.models.recipe import Adjustments, CurvePoint, CurveSet
from tests.icc_support import (
    _para_tag,
    build_adobe_rgb_like_profile,
    build_display_p3_like_profile,
    build_lut_only_profile,
    build_srgb_matrix_profile,
    build_srgb_matrix_profile_with_delta,
    build_structured_lut_profile,
)

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
        # LZW/JPEG TIFFs are outside the B5b input contract; these fixtures test
        # colour management, so keep them on an accepted compression.
        options["compression"] = "tiff_adobe_deflate"
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


def _insert_iccp(payload: bytes, profile: bytes) -> bytes:
    """Add an iCCP chunk to a PNG so 16-bit fixtures can carry a profile."""
    data = b"FRAME AI" + b"\0" + b"\0" + zlib.compress(profile)
    chunk = (
        struct.pack(">I", len(data))
        + b"iCCP"
        + data
        + struct.pack(">I", zlib.crc32(b"iCCP" + data) & 0xFFFFFFFF)
    )
    # PNG signature (8) + IHDR (25) end at byte 33, where iCCP belongs.
    return payload[:33] + chunk + payload[33:]


def _png16(values: NDArray[np.uint16], profile: bytes | None = None) -> bytes:
    if values.shape[2] == 4:
        source = np.dstack([values[..., 2::-1], values[..., 3]])
    else:
        source = values[..., ::-1]
    # cv2.imwrite fails on non-ASCII Windows paths, so encode in memory.
    success, encoded = cv2.imencode(".png", np.ascontiguousarray(source))
    assert bool(success)
    payload = encoded.tobytes()
    return payload if profile is None else _insert_iccp(payload, profile)


def _ramp16() -> NDArray[np.uint16]:
    ramp = np.arange(65536, dtype=np.uint16).reshape(256, 256)
    return np.stack([ramp, ramp, (65535 - ramp).astype(np.uint16)], axis=-1)


def _precision_stats(channel: NDArray[np.uint16]) -> tuple[int, float, int]:
    unique = int(np.unique(channel).size)
    divisible = float(np.count_nonzero(channel.astype(np.int64) % 257 == 0))
    steps = np.abs(np.diff(channel.astype(np.int32), axis=1))
    return unique, divisible / channel.size * 100.0, int(steps.max())


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


def test_16_bit_rgb_keeps_its_samples_instead_of_downconverting() -> None:
    values = np.zeros((8, 8, 3), dtype=np.uint16)
    for index in range(64):
        level = index * 65535 // 63
        row, column = divmod(index, 8)
        values[row, column] = (level, 65535 - level, 32768)
    loaded = load_image(_png16(values))

    reference = values.astype(np.float32) / np.float32(65535.0)
    assert loaded.bit_depth == 16
    assert loaded.rgb.dtype == np.float32
    assert float(np.abs(loaded.rgb - reference).max()) <= 1e-6

    # Pillow truncates 16-bit RGB through its 8-bit mode (511 -> 1, 1000 -> 3);
    # these neighbouring samples must stay distinct after the B5b decode.
    pair = np.zeros((1, 2, 3), dtype=np.uint16)
    pair[0, 0] = (511, 1000, 32768)
    pair[0, 1] = (512, 1001, 32769)
    decoded = load_image(_png16(pair)).rgb
    assert not np.array_equal(decoded[0, 0], decoded[0, 1])
    assert abs(float(decoded[0, 0, 0]) - 511 / 65535) <= 1e-6
    assert abs(float(decoded[0, 0, 1]) - 1000 / 65535) <= 1e-6


def test_16_bit_adobe_rgb_ramp_keeps_more_than_60000_levels() -> None:
    payload = _png16(_ramp16(), build_adobe_rgb_like_profile())

    loaded = load_image(payload)
    unique, divisible, step = _precision_stats(to_uint16(loaded.rgb)[..., 1])

    assert loaded.bit_depth == 16
    assert unique > 60000
    # Fewer than 1% of the values are exact 8-bit replicas, so the output was
    # not quantised through an 8-bit intermediate.
    assert divisible < 1.0
    assert step <= 2


def test_eight_bit_intermediate_collapses_the_same_ramp_to_256_levels() -> None:
    ramp = _ramp16()
    eight = np.rint(ramp.astype(np.float32) / 257.0).astype(np.uint8)
    payload = _encode(Image.fromarray(eight, "RGB"), profile=build_adobe_rgb_like_profile())

    loaded = load_image(payload)
    channel = np.clip(np.rint(loaded.rgb[..., 1] * 65535.0), 0, 65535).astype(np.uint16)
    unique, divisible, step = _precision_stats(channel)

    # This is the counterexample the 16-bit gate above must not regress to.
    assert loaded.bit_depth == 8
    assert unique < 300
    assert divisible == pytest.approx(100.0)
    assert step >= 500


@pytest.mark.parametrize(
    "profile",
    [
        build_adobe_rgb_like_profile(),
        build_adobe_rgb_like_profile(parametric=True),
        P3_BYTES,
    ],
    ids=["adobe-curv", "adobe-para", "display-p3"],
)
def test_16_bit_profile_conversion_matches_lcms_within_one_level(profile: bytes) -> None:
    colors = np.array(
        [(200, 60, 60), (60, 200, 60), (230, 160, 120), (20, 20, 20), (250, 240, 10)],
        dtype=np.uint16,
    )
    values = (colors * 257)[None, :, :]
    payload = _png16(values, profile)
    loaded = load_image(payload)

    with Image.open(io.BytesIO(payload)) as opened:
        assert opened.info["icc_profile"] == profile
    reference_image = Image.fromarray(colors.astype(np.uint8)[None], "RGB")
    reference = np.asarray(
        ImageCms.profileToProfile(
            reference_image,
            ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            SRGB,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        ),
        dtype=np.float32,
    )

    assert loaded.bit_depth == 16
    assert float(np.abs(loaded.rgb * 255.0 - reference).max()) <= 1.0


def test_16_bit_tiff_profile_is_converted_to_srgb() -> None:
    colors = np.array([(200, 60, 60), (230, 160, 120)], dtype=np.uint16)
    values = (colors * 257)[None, :, :]
    buffer = io.BytesIO()
    tifffile.imwrite(buffer, np.ascontiguousarray(values), photometric="rgb", iccprofile=P3_BYTES)

    loaded = load_image(buffer.getvalue())
    reference_image = Image.fromarray(colors.astype(np.uint8)[None], "RGB")
    reference = np.asarray(
        ImageCms.profileToProfile(
            reference_image,
            P3_PROFILE,
            SRGB,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        ),
        dtype=np.float32,
    )

    assert loaded.bit_depth == 16
    assert float(np.abs(loaded.rgb * 255.0 - reference).max()) <= 1.0


def test_16_bit_srgb_profile_and_untagged_inputs_are_untouched() -> None:
    values = np.array([[[0, 511, 65535], [1000, 32768, 40000]]], dtype=np.uint16)
    tagged = encode_image(
        to_uint16(values.astype(np.float32) / np.float32(65535.0)),
        image_format="png",
        bit_depth=16,
    )

    for payload in (tagged, _png16(values)):
        loaded = load_image(payload)
        assert loaded.bit_depth == 16
        assert float(np.abs(loaded.rgb - values / 65535.0).max()) <= 1e-6


def test_16_bit_lut_profile_is_rejected_as_unsupported() -> None:
    payload = _png16(_ramp16()[:4, :4], build_lut_only_profile())

    with pytest.raises(AppError) as error:
        load_image(payload)

    assert error.value.status_code == 422
    assert error.value.code == "unsupported_icc_profile"


def test_srgb_description_cannot_hide_a_lut_profile() -> None:
    profile = build_lut_only_profile(description="sRGB compatible LUT profile")
    values = _ramp16()[:4, :4]
    tiff = io.BytesIO()
    tifffile.imwrite(tiff, np.ascontiguousarray(values), photometric="rgb", iccprofile=profile)

    for payload in (_png16(values, profile), tiff.getvalue()):
        with pytest.raises(AppError) as error:
            load_image(payload)

        assert error.value.status_code == 422
        assert error.value.code == "unsupported_icc_profile"


def test_srgb_description_does_not_shortcut_a_non_srgb_matrix_profile() -> None:
    profile = build_display_p3_like_profile(description="sRGB compatible LUT profile")
    colors = np.array(
        [(200, 60, 60), (60, 200, 60), (230, 160, 120), (20, 20, 20)],
        dtype=np.uint16,
    )
    values = (colors * 257)[None, :, :]
    payload = _png16(values, profile)

    loaded = load_image(payload)
    reference = np.asarray(
        ImageCms.profileToProfile(
            Image.fromarray(colors.astype(np.uint8)[None], "RGB"),
            ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            SRGB,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        ),
        dtype=np.float32,
    )

    assert not np.allclose(loaded.rgb, values / 65535.0, atol=1e-6)
    assert float(np.abs(loaded.rgb * 255.0 - reference).max()) <= 1.0


def test_structurally_exact_srgb_profile_is_untouched_regardless_of_description() -> None:
    profile = build_srgb_matrix_profile(description="Custom matrix profile")
    values = np.array([[[1000, 5000, 40000], [65535, 0, 32768]]], dtype=np.uint16)

    loaded = load_image(_png16(values, profile))

    assert np.allclose(loaded.rgb, values / 65535.0, atol=1e-6)


def test_lcms_srgb_profile_passes_the_structural_check() -> None:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    assert is_srgb_matrix_trc(profile)
    assert not is_srgb_matrix_trc(build_lut_only_profile(description="sRGB compatible"))


def _identity_grid() -> NDArray[np.float32]:
    axis = np.linspace(0.0, 1.0, 17, dtype=np.float32)
    return np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(1, -1, 3)


def test_identity_shortcut_stays_within_one_eight_bit_level() -> None:
    grid = _identity_grid()
    lcms = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()

    assert is_srgb_matrix_trc(lcms)
    lcms_error = np.abs(transform_to_srgb(grid, lcms).astype(np.float64) - grid.astype(np.float64))
    assert float(lcms_error.max() * 255.0) <= 1.0

    exact = build_srgb_matrix_profile()
    assert is_srgb_matrix_trc(exact)
    exact_error = np.abs(
        transform_to_srgb(grid, exact).astype(np.float64) - grid.astype(np.float64)
    )
    assert float(exact_error.max() * 255.0) <= 0.1

    # This matrix sits inside the old element-wise tolerance but drifts about
    # 16 8-bit levels at the dark end, so the composed-sample gate must reject it.
    drifted = build_srgb_matrix_profile_with_delta((-1, 1, 1, -1, -1, -1, -1, -1, -1))
    drift_error = np.abs(
        transform_to_srgb(grid, drifted).astype(np.float64) - grid.astype(np.float64)
    )
    assert float(drift_error.max() * 255.0) > 1.0
    assert not is_srgb_matrix_trc(drifted)


@pytest.mark.parametrize("tag", ["D2B0", "D2B3", "B2D0", "B2D3"])
def test_v4_structured_lut_tags_fail_closed(tag: str) -> None:
    profile = build_structured_lut_profile(tag)
    rgb = np.zeros((1, 1, 3), dtype=np.float32)

    assert not is_srgb_matrix_trc(profile)
    with pytest.raises(UnsupportedProfileError):
        transform_to_srgb(rgb, profile)
    with pytest.raises(AppError) as error:
        load_image(_png16(np.zeros((1, 1, 3), dtype=np.uint16), profile))

    assert error.value.status_code == 422
    assert error.value.code == "unsupported_icc_profile"


@pytest.mark.parametrize(
    ("function_type", "params"),
    [
        (1, (2.2, 1.0, 0.0)),
        (2, (2.2, 1.0, 0.0, 0.0)),
    ],
    ids=["para-1", "para-2"],
)
def test_para_1_and_2_match_the_lcms_eight_bit_reference(
    function_type: int,
    params: tuple[float, ...],
) -> None:
    profile = build_srgb_matrix_profile(trc=_para_tag(function_type, *params))
    colors = np.array(
        [(200, 60, 60), (60, 200, 60), (230, 160, 120), (20, 20, 20)],
        dtype=np.uint16,
    )
    loaded = load_image(_png16((colors * 257)[None], profile))
    reference = np.asarray(
        ImageCms.profileToProfile(
            Image.fromarray(colors.astype(np.uint8)[None], "RGB"),
            ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            SRGB,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        ),
        dtype=np.float32,
    )

    assert float(np.abs(loaded.rgb * 255.0 - reference).max()) <= 1.0


@pytest.mark.parametrize(
    ("function_type", "params"),
    [
        (1, (2.2, 1.0, 0.0)),
        (2, (2.2, 1.0, 0.0, 0.0)),
        (4, (2.4, 1.0 / 1.055, 0.055 / 1.055, 1.0 / 12.92, 0.04045, 0.0, 0.0)),
    ],
    ids=["para-1", "para-2", "para-4"],
)
def test_parametric_trc_types_are_applied_with_endpoints_and_monotonicity(
    function_type: int,
    params: tuple[float, ...],
) -> None:
    profile = build_srgb_matrix_profile(
        description="Custom parametric profile",
        trc=_para_tag(function_type, *params),
    )
    ramp = np.linspace(0, 65535, 257, dtype=np.uint16).reshape(1, -1, 1)
    values = np.repeat(ramp, 3, axis=-1)

    loaded = load_image(_png16(values, profile))

    channel = loaded.rgb[0, :, 0].astype(np.float64)
    assert channel[0] == pytest.approx(0.0, abs=1e-7)
    assert channel[-1] == pytest.approx(1.0, abs=1e-5)
    assert np.all(np.diff(channel) >= -1e-6)
    # Only the type-4 curve with sRGB parameters is structurally sRGB; the
    # gamma-2.2 types must go through the conversion path instead of identity.
    assert is_srgb_matrix_trc(profile) is (function_type == 4)
    if function_type == 4:
        assert np.allclose(channel, ramp[0, :, 0] / 65535.0, atol=2e-4)


def _profile_variant(profile: bytes, offset: int, replacement: bytes) -> bytes:
    mutated = bytearray(profile)
    mutated[offset : offset + len(replacement)] = replacement
    return bytes(mutated)


@pytest.mark.parametrize(
    "profile",
    [
        _profile_variant(P3_BYTES, 0, struct.pack(">I", 0xFFFFFFFF)),
        _profile_variant(P3_BYTES, 128, struct.pack(">I", 0xFFFFFFFF)),
        _profile_variant(P3_BYTES, 136, struct.pack(">I", 0xFFFFFF00)),
        _profile_variant(P3_BYTES, 16, b"CMYK"),
        _profile_variant(P3_BYTES, 20, b"Lab "),
        P3_BYTES[: len(P3_BYTES) // 3],
    ],
    ids=["oversized-header", "tag-count", "tag-offset", "cmyk-space", "lab-pcs", "truncated"],
)
def test_16_bit_malformed_profiles_fail_safely(profile: bytes) -> None:
    payload = _png16(_ramp16()[:2, :2], profile)

    with pytest.raises(AppError) as error:
        load_image(payload)

    assert error.value.status_code == 422
    assert error.value.code == "unsupported_icc_profile"


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
    allowed = {
        "output.py",
        "detail.py",
        "loader.py",
        "analyzer.py",
        "semantic_models.py",
        "generative_masks.py",
        "generative_outpaint.py",
    }

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
