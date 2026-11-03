from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, ImageCms, ImageOps

from app.imaging.loader import load_image
from tests.icc_support import build_display_p3_like_profile

P3_BYTES = build_display_p3_like_profile()
P3_PROFILE = ImageCms.ImageCmsProfile(io.BytesIO(P3_BYTES))
SRGB_PROFILE = ImageCms.createProfile("sRGB")

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


def _encode(
    image: Image.Image,
    *,
    profile: bytes | None = None,
    exif: Image.Exif | None = None,
) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, object] = {}
    if profile is not None:
        options["icc_profile"] = profile
    if exif is not None:
        options["exif"] = exif
    image.save(buffer, format="PNG", **options)
    return buffer.getvalue()


def _decode(payload: bytes) -> Image.Image:
    with Image.open(io.BytesIO(payload)) as opened:
        return opened.convert("RGB").copy()


def _p3_to_srgb(image: Image.Image) -> np.ndarray:
    converted = ImageCms.profileToProfile(
        image.convert("RGB"),
        P3_PROFILE,
        SRGB_PROFILE,
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        outputMode="RGB",
        flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
    )
    assert converted is not None
    return np.asarray(converted, dtype=np.float32)


def _color_blocks() -> Image.Image:
    image = Image.new("RGB", (24, 8))
    for index, color in enumerate([(200, 60, 60), (60, 200, 60), (230, 160, 120)]):
        image.paste(color, (index * 8, 0, index * 8 + 8, 8))
    return image


def _gradient() -> Image.Image:
    height, width = 24, 32
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    pixels = np.stack(
        [
            20.0 + 200.0 * xx / width,
            10.0 + 220.0 * yy / height,
            60.0 + 120.0 * (xx + yy) / (width + height),
        ],
        axis=-1,
    )
    return Image.fromarray(np.clip(np.rint(pixels), 0, 255).astype(np.uint8), mode="RGB")


def test_p3_profile_is_converted_to_srgb():
    payload = _encode(_color_blocks(), profile=P3_BYTES)

    loaded = load_image(payload)
    expected = _p3_to_srgb(_decode(payload)) / 255.0

    assert np.abs(loaded.rgb - expected).max() * 255 <= 1.0


def test_srgb_profile_is_untouched():
    srgb_bytes = ImageCms.ImageCmsProfile(SRGB_PROFILE).tobytes()
    payload = _encode(_color_blocks(), profile=srgb_bytes)

    loaded = load_image(payload)
    expected = np.asarray(_decode(payload), dtype=np.float32) / 255.0

    assert np.allclose(loaded.rgb, expected, atol=1e-6)


def test_broken_profile_falls_back():
    payload = _encode(_color_blocks(), profile=b"not an icc profile")

    loaded = load_image(payload)
    expected = np.asarray(_decode(payload), dtype=np.float32) / 255.0

    assert np.allclose(loaded.rgb, expected, atol=1e-6)


def test_no_profile_untouched():
    payload = _encode(_color_blocks())

    loaded = load_image(payload)
    expected = np.asarray(_decode(payload), dtype=np.float32) / 255.0

    assert np.allclose(loaded.rgb, expected, atol=1e-6)


@pytest.mark.parametrize("orientation", range(1, 9))
def test_profile_and_exif_orientation_together(orientation: int):
    display = _gradient()
    inverse = INVERSE_ORIENTATION[orientation]
    stored = display if inverse is None else display.transpose(inverse)
    exif = Image.Exif()
    exif[274] = orientation
    payload = _encode(stored, profile=P3_BYTES, exif=exif)

    loaded = load_image(payload)
    with Image.open(io.BytesIO(payload)) as opened:
        expected = _p3_to_srgb(ImageOps.exif_transpose(opened)) / 255.0

    assert (loaded.width, loaded.height) == (32, 24)
    assert loaded.rgb.shape == expected.shape
    assert np.abs(loaded.rgb - expected).max() * 255 <= 1.0
