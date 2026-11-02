from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms

ImageFormat = Literal["jpeg", "png"]

FORMAT_INFO: dict[ImageFormat, tuple[str, str, str]] = {
    "jpeg": ("JPEG", ".jpg", "image/jpeg"),
    "png": ("PNG", ".png", "image/png"),
}
JPEG_QUALITY = 90


def to_uint8(rgb: NDArray[np.float32]) -> NDArray[np.uint8]:
    quantized: NDArray[np.uint8] = np.clip(np.rint(rgb * np.float32(255.0)), 0.0, 255.0).astype(
        np.uint8
    )
    return np.ascontiguousarray(quantized)


@lru_cache(maxsize=1)
def srgb_icc_profile() -> bytes:
    profile: bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return profile


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
