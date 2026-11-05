from __future__ import annotations

import logging
from functools import lru_cache
from io import BytesIO
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms

ImageFormat = Literal["jpeg", "png"]
logger = logging.getLogger("frame_ai.output")

FORMAT_INFO: dict[ImageFormat, tuple[str, str, str]] = {
    "jpeg": ("JPEG", ".jpg", "image/jpeg"),
    "png": ("PNG", ".png", "image/png"),
}
JPEG_QUALITY = 90


def to_uint8(rgb: NDArray[np.float32], *, inplace: bool = False) -> NDArray[np.uint8]:
    if not np.isfinite(rgb).all():
        # ``astype(uint8)`` turns NaN into 0 without a word.  Sanitize first and
        # say so: a non-finite pixel is an upstream bug, but shipping a silently
        # black frame hides it.
        logger.warning("non_finite_pixels_sanitized")
        rgb = np.nan_to_num(rgb, copy=not inplace, nan=0.0, posinf=1.0, neginf=0.0)
    scaled = rgb if inplace else rgb * np.float32(255.0)
    if inplace:
        np.multiply(scaled, np.float32(255.0), out=scaled)
    np.rint(scaled, out=scaled)
    np.clip(scaled, 0.0, 255.0, out=scaled)
    quantized: NDArray[np.uint8] = scaled.astype(np.uint8)
    return np.ascontiguousarray(quantized)


@lru_cache(maxsize=1)
def srgb_icc_profile() -> bytes:
    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    # lcms stamps the current time into the profile header, which would make
    # encoded bytes differ between processes. Pin it (2020-01-01 00:00:00).
    profile[24:36] = bytes.fromhex("07e400010001000000000000")
    return bytes(profile)


def encode_image(
    pixels: NDArray[np.uint8],
    *,
    image_format: ImageFormat = "jpeg",
    quality: int = JPEG_QUALITY,
) -> bytes:
    if image_format not in FORMAT_INFO:
        raise ValueError(f"unsupported image format: {image_format}")
    if not 1 <= quality <= 100:
        raise ValueError("quality must be between 1 and 100")
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("pixels must be an HxWx3 uint8 array")

    format_name, _, _ = FORMAT_INFO[image_format]
    image = Image.fromarray(np.ascontiguousarray(pixels))
    buffer = BytesIO()
    options: dict[str, object] = {"icc_profile": srgb_icc_profile()}
    if image_format == "jpeg":
        options["quality"] = quality
        options["subsampling"] = 0 if quality >= 90 else 2
    image.save(buffer, format=format_name, **options)
    return buffer.getvalue()
