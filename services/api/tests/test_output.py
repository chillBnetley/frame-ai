from __future__ import annotations

import logging
from io import BytesIO

import numpy as np
import pytest
from PIL import Image, ImageCms

from app.imaging.output import FORMAT_INFO, encode_image, srgb_icc_profile, to_uint8


def _pixels() -> np.ndarray:
    height, width = 24, 32
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    red = np.repeat(x, height, axis=0)
    green = np.repeat(y, width, axis=1)
    blue = np.full((height, width), 128.0)
    return np.stack([red, green, blue], axis=-1).astype(np.uint8)


def test_to_uint8_clips_and_rounds():
    rgb = np.array([[[-0.4, 100.6 / 255.0, 1.4], [0.5, 0.0, 1.0]]], dtype=np.float32)

    result = to_uint8(rgb)

    assert result.dtype == np.uint8
    assert result.tolist() == [[[0, 101, 255], [128, 0, 255]]]


def test_to_uint8_sanitizes_non_finite_values_and_warns(caplog: pytest.LogCaptureFixture):
    rgb = np.array([[[np.nan, np.inf, -np.inf], [0.5, -1.0, 2.0]]], dtype=np.float32)

    with caplog.at_level(logging.WARNING, logger="frame_ai.output"):
        result = to_uint8(rgb)

    assert result.tolist() == [[[0, 255, 0], [128, 0, 255]]]
    assert "non_finite_pixels_sanitized" in caplog.text


def test_inplace_sanitizing_does_not_leave_non_finite_pixels():
    rgb = np.array([[[np.nan, np.inf, 0.25]]], dtype=np.float32)

    result = to_uint8(rgb, inplace=True)

    assert result.tolist() == [[[0, 255, 64]]]
    assert not np.any(np.isnan(rgb))


@pytest.mark.parametrize("image_format", ["jpeg", "png"])
def test_encoded_images_keep_dimensions_and_embed_srgb_icc(image_format: str):
    pixels = _pixels()

    payload = encode_image(pixels, image_format=image_format)

    with Image.open(BytesIO(payload)) as image:
        expected_format, extension, mime_type = FORMAT_INFO[image_format]
        assert image.format == expected_format
        assert image.size == (pixels.shape[1], pixels.shape[0])
        assert image.mode == "RGB"
        assert len(image.getexif()) == 0
        assert image.info["icc_profile"] == srgb_icc_profile()
        if image_format == "jpeg":
            assert "exif" not in image.info
        else:
            assert not any(key.startswith(("exif", "text", "XML")) for key in image.info)
        assert extension and mime_type


def test_encoded_payloads_contain_no_metadata_chunks():
    jpeg = encode_image(_pixels(), image_format="jpeg")
    png = encode_image(_pixels(), image_format="png")

    assert b"Exif\x00\x00" not in jpeg
    assert b"http://ns.adobe.com/xap" not in jpeg
    for chunk in (b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"):
        assert chunk not in png


def test_encoding_is_byte_for_byte_deterministic():
    pixels = _pixels()

    assert encode_image(pixels, image_format="jpeg") == encode_image(pixels, image_format="jpeg")
    assert encode_image(pixels, image_format="png") == encode_image(pixels, image_format="png")


def test_srgb_profile_creation_time_is_pinned():
    # lcms writes the current time into the header; a pinned value keeps
    # encoded output identical across processes.
    profile = srgb_icc_profile()

    assert profile[24:36] == bytes.fromhex("07e400010001000000000000")


def test_embedded_profile_is_srgb():
    profile = ImageCms.ImageCmsProfile(BytesIO(srgb_icc_profile()))

    assert "srgb" in ImageCms.getProfileDescription(profile).lower()


def test_encode_rejects_invalid_inputs():
    pixels = _pixels()

    with pytest.raises(ValueError):
        encode_image(pixels.astype(np.float32))
    with pytest.raises(ValueError):
        encode_image(pixels[..., 0])
    with pytest.raises(ValueError):
        encode_image(pixels, image_format="gif")
    with pytest.raises(ValueError):
        encode_image(pixels, quality=0)
    with pytest.raises(ValueError):
        encode_image(pixels, quality=101)
