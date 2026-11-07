from __future__ import annotations

import logging
from io import BytesIO

import cv2
import numpy as np
import pytest
import tifffile
from PIL import Image, ImageCms

from app.imaging.output import (
    FORMAT_INFO,
    encode_image,
    srgb_icc_profile,
    to_uint8,
    to_uint16,
    to_uint16_alpha,
)


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


def test_png_with_alpha_writes_rgba_pixels_and_icc():
    pixels = _pixels()
    alpha = np.zeros(pixels.shape[:2], dtype=np.uint8)
    alpha[:, alpha.shape[1] // 2 :] = 255

    payload = encode_image(pixels, image_format="png", alpha=alpha)

    with Image.open(BytesIO(payload)) as image:
        assert image.mode == "RGBA"
        assert image.size == (pixels.shape[1], pixels.shape[0])
        decoded = np.asarray(image, dtype=np.uint8)
        assert np.array_equal(decoded[..., :3], pixels)
        assert np.array_equal(decoded[..., 3], alpha)
        assert image.info["icc_profile"] == srgb_icc_profile()
        assert not any(key.startswith(("exif", "text", "XML")) for key in image.info)


def test_jpeg_with_alpha_composites_each_pixel_on_white():
    height, width = 8, 8
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[..., 0] = 200
    alpha = np.zeros((height, width), dtype=np.uint8)
    alpha[2:6, 2:6] = 255
    alpha[0, 0] = 128

    payload = encode_image(pixels, image_format="jpeg", quality=100, alpha=alpha)

    with Image.open(BytesIO(payload)) as image:
        assert image.mode == "RGB"
        decoded = np.asarray(image, dtype=np.uint8)
    # Fully transparent pixels encode as pure white; fully opaque pixels keep
    # their colour. JPEG is lossy, so allow a small codec tolerance.
    assert np.all(decoded[0, 1:] >= 250)
    assert np.all(decoded[7, 1:] >= 250)
    assert np.allclose(decoded[4, 4, :3], np.array([200, 0, 0]), atol=3)
    # 50% coverage lands halfway between the colour and white.
    assert np.allclose(decoded[0, 0, :], np.array([228, 128, 128]), atol=4)


def _pixels16() -> np.ndarray:
    height, width = 24, 32
    x = np.linspace(0, 65535, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 65535, height, dtype=np.float32)[:, None]
    red = np.repeat(x, height, axis=0)
    green = np.repeat(y, width, axis=1)
    blue = np.full((height, width), 32768.0)
    return np.stack([red, green, blue], axis=-1).astype(np.uint16)


def test_to_uint16_keeps_sixteen_bits_of_precision():
    rgb = np.array([[[0.0, 1.0 / 65535.0, 0.5], [1.0, 0.25, 32768.0 / 65535.0]]], dtype=np.float32)

    result = to_uint16(rgb)

    assert result.dtype == np.uint16
    assert result.tolist() == [[[0, 1, 32768], [65535, 16384, 32768]]]


def test_to_uint16_alpha_quantises_coverage():
    alpha = np.array([[0.0, 0.5, 1.0, 1.0 / 65535.0]], dtype=np.float32)

    result = to_uint16_alpha(alpha)

    assert result.dtype == np.uint16
    assert result.tolist() == [[0, 32768, 65535, 1]]


def test_sixteen_bit_png_is_a_real_sixteen_bit_container():
    pixels = _pixels16()

    payload = encode_image(pixels, image_format="png", bit_depth=16)

    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    assert payload[24] == 16  # IHDR bit depth
    assert payload[25] == 2  # colour type: truecolour
    assert b"iCCP" in payload
    with Image.open(BytesIO(payload)) as image:
        assert image.info["icc_profile"] == srgb_icc_profile()
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded is not None
    assert decoded.dtype == np.uint16
    assert np.array_equal(decoded[..., ::-1], pixels)


def test_sixteen_bit_png_with_alpha_uses_colour_type_six():
    pixels = _pixels16()
    alpha = np.zeros(pixels.shape[:2], dtype=np.uint16)
    alpha[:, alpha.shape[1] // 2 :] = 65535

    payload = encode_image(pixels, image_format="png", bit_depth=16, alpha=alpha)

    assert payload[24] == 16
    assert payload[25] == 6  # colour type: truecolour + alpha
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded is not None
    assert decoded.shape == (pixels.shape[0], pixels.shape[1], 4)
    assert np.array_equal(decoded[..., [2, 1, 0]], pixels)
    assert np.array_equal(decoded[..., 3], alpha)


def test_sixteen_bit_tiff_writes_deflate_icc_and_no_metadata():
    pixels = _pixels16()

    payload = encode_image(pixels, image_format="tiff", bit_depth=16)

    with tifffile.TiffFile(BytesIO(payload)) as tiff:
        page = tiff.pages[0]
        assert page.dtype == np.uint16
        assert page.shape == pixels.shape
        assert page.compression == 32946  # deflate
        assert page.tags[34675].value == srgb_icc_profile()
        assert page.tags.get(338) is None
        for absent in (270, 305, 306):  # ImageDescription / Software / DateTime
            assert absent not in page.tags
        assert np.array_equal(page.asarray(), pixels)


def test_sixteen_bit_tiff_with_alpha_marks_unassociated_alpha():
    pixels = _pixels16()
    alpha = np.full(pixels.shape[:2], 65535, dtype=np.uint16)
    alpha[0, 0] = 0

    payload = encode_image(pixels, image_format="tiff", bit_depth=16, alpha=alpha)

    with tifffile.TiffFile(BytesIO(payload)) as tiff:
        page = tiff.pages[0]
        assert page.samplesperpixel == 4
        assert page.tags[338].value == (2,)  # EXTRASAMPLE.UNASSALPHA
        decoded = page.asarray()
    assert np.array_equal(decoded[..., :3], pixels)
    assert np.array_equal(decoded[..., 3], alpha)


@pytest.mark.parametrize("image_format", ["png", "tiff"])
def test_sixteen_bit_encoding_is_byte_for_byte_deterministic(image_format: str):
    pixels = _pixels16()

    first = encode_image(pixels, image_format=image_format, bit_depth=16)
    second = encode_image(pixels, image_format=image_format, bit_depth=16)

    assert first == second


def test_sixteen_bit_jpeg_is_rejected():
    with pytest.raises(ValueError, match="JPEG does not support 16-bit"):
        encode_image(_pixels16(), image_format="jpeg", bit_depth=16)


def test_sixteen_bit_encoding_validates_dtype_and_alpha():
    with pytest.raises(ValueError, match="uint16"):
        encode_image(_pixels(), image_format="png", bit_depth=16)
    with pytest.raises(ValueError, match="alpha"):
        encode_image(
            _pixels16(),
            image_format="tiff",
            bit_depth=16,
            alpha=np.zeros(_pixels16().shape[:2], dtype=np.uint8),
        )


def test_eight_bit_tiff_round_trips_with_icc():
    pixels = _pixels()

    payload = encode_image(pixels, image_format="tiff")

    with tifffile.TiffFile(BytesIO(payload)) as tiff:
        page = tiff.pages[0]
        assert page.dtype == np.uint8
        assert page.compression == 32946
        assert page.tags[34675].value == srgb_icc_profile()
        assert np.array_equal(page.asarray(), pixels)


def test_alpha_shape_and_dtype_are_validated():
    pixels = _pixels()

    with pytest.raises(ValueError):
        encode_image(pixels, image_format="png", alpha=np.zeros((1, 1), dtype=np.uint8))
    with pytest.raises(ValueError):
        encode_image(
            pixels,
            image_format="png",
            alpha=np.zeros(pixels.shape[:2], dtype=np.float32),
        )


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
