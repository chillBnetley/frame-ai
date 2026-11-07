from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from app.ai.base import ModelImage
from app.core.errors import AppError
from app.imaging.loader import LoadedImage, load_image, resize_to_max_edge
from app.services.image_service import ImageService

ANALYSIS_MIN_EDGE = 512
ANALYSIS_MAX_EDGE_LIMIT = 2048
ANALYSIS_JPEG_QUALITY = 85
ALPHA_LIMITATION = "原图包含透明通道，已按白底合成后分析；原图未被修改。"
ORIGINAL_CHANGED_MESSAGE = "The original image changed before analysis completed."
INPUT_TOO_LARGE_MESSAGE = "The analysis image copy exceeds the configured size limit."


@dataclass(frozen=True, slots=True)
class PreprocessedImage:
    image: ModelImage
    original_sha256: str
    original_width: int
    original_height: int
    exif_orientation: int
    had_alpha: bool
    limitations: tuple[str, ...]


def preprocess_image(
    images: ImageService,
    image_id: str,
    *,
    max_edge: int,
    max_pixels: int,
    max_bytes: int | None = None,
) -> PreprocessedImage:
    record, path = images.get_original(image_id)
    return preprocess_original(
        path,
        expected_sha256=record.sha256,
        display_width=record.width,
        display_height=record.height,
        exif_orientation=record.exif_orientation,
        max_edge=max_edge,
        max_pixels=max_pixels,
        max_bytes=max_bytes,
    )


def preprocess_original(
    path: Path,
    *,
    expected_sha256: str,
    display_width: int,
    display_height: int,
    exif_orientation: int,
    max_edge: int,
    max_pixels: int,
    max_bytes: int | None = None,
) -> PreprocessedImage:
    if not ANALYSIS_MIN_EDGE <= max_edge <= ANALYSIS_MAX_EDGE_LIMIT:
        raise ValueError(
            f"max_edge must be between {ANALYSIS_MIN_EDGE} and {ANALYSIS_MAX_EDGE_LIMIT}"
        )

    _ensure_non_empty(path)
    digest_before = _sha256_file(path)
    if digest_before != expected_sha256.lower():
        raise AppError(500, "original_changed", ORIGINAL_CHANGED_MESSAGE)

    had_alpha = _has_alpha(path)
    loaded = load_image(path, max_pixels=max_pixels, preserve_alpha=False)
    scaled = resize_to_max_edge(loaded, max_edge)
    encoded = _encode_jpeg(scaled)
    if max_bytes is not None and len(encoded) > max_bytes:
        raise AppError(
            413,
            "analysis_input_too_large",
            INPUT_TOO_LARGE_MESSAGE,
            {"maxBytes": max_bytes},
        )

    digest_after = _sha256_file(path)
    if digest_after != digest_before:
        raise AppError(500, "original_changed", ORIGINAL_CHANGED_MESSAGE)

    limitations = (ALPHA_LIMITATION,) if had_alpha else ()
    return PreprocessedImage(
        image=ModelImage(
            data=encoded,
            mime_type="image/jpeg",
            width=scaled.width,
            height=scaled.height,
        ),
        original_sha256=digest_before,
        original_width=display_width,
        original_height=display_height,
        exif_orientation=exif_orientation,
        had_alpha=had_alpha,
        limitations=limitations,
    )


def _ensure_non_empty(path: Path) -> None:
    try:
        if path.stat().st_size == 0:
            raise AppError(400, "empty_file", "The original image file is empty.")
    except FileNotFoundError as exc:
        raise AppError(
            404, "image_file_missing", "The original image file is not available."
        ) from exc
    except OSError as exc:
        raise AppError(500, "storage_error", "The original image could not be read.") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_alpha(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            return image.mode in {"RGBA", "LA"} or "transparency" in image.info
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def _encode_jpeg(image: LoadedImage) -> bytes:
    pixels = np.clip(np.rint(image.rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    buffer = BytesIO()
    Image.fromarray(pixels).save(
        buffer,
        format="JPEG",
        quality=ANALYSIS_JPEG_QUALITY,
        subsampling=0,
    )
    return buffer.getvalue()


__all__ = [
    "ALPHA_LIMITATION",
    "ANALYSIS_JPEG_QUALITY",
    "ANALYSIS_MAX_EDGE_LIMIT",
    "ANALYSIS_MIN_EDGE",
    "PreprocessedImage",
    "preprocess_image",
    "preprocess_original",
]
