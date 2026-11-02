from __future__ import annotations

import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.core.errors import AppError

DECLARED_MIME_TO_FORMAT = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

FORMAT_INFO = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}

SUPPORTED_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")

ORIENTATION_TAG = 0x0112
_SWAPPING_ORIENTATIONS = {5, 6, 7, 8}


@dataclass(frozen=True)
class DecodedImage:
    detected_format: str
    mime_type: str
    extension: str
    width: int
    height: int
    exif_orientation: int


def normalize_declared_mime(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _read_orientation(image: Image.Image) -> int:
    try:
        value: Any = image.getexif().get(ORIENTATION_TAG, 1)
    except (OSError, SyntaxError, ValueError):
        return 1
    if isinstance(value, int) and 1 <= value <= 8:
        return value
    return 1


def display_dimensions(width: int, height: int, orientation: int) -> tuple[int, int]:
    """Return dimensions as displayed after EXIF orientation is applied."""
    if orientation in _SWAPPING_ORIENTATIONS:
        return height, width
    return width, height


def _pixel_error(width: int, height: int, max_pixels: int) -> AppError:
    return AppError(
        413,
        "image_too_many_pixels",
        "The image dimensions exceed the configured pixel limit.",
        {"width": width, "height": height, "maxPixels": max_pixels},
    )


def inspect_image(data: bytes, declared_mime: str, max_pixels: int) -> DecodedImage:
    """Validate an uploaded image without trusting the client-provided MIME type."""
    if not data:
        raise AppError(400, "empty_file", "The uploaded file is empty.")

    expected_format = DECLARED_MIME_TO_FORMAT.get(declared_mime)
    if expected_format is None:
        raise AppError(
            415,
            "unsupported_media_type",
            "Only JPEG, PNG, and WebP images are supported.",
            {"allowedMimeTypes": list(SUPPORTED_MIME_TYPES)},
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                detected_format = image.format

                if not detected_format or detected_format not in FORMAT_INFO:
                    raise AppError(
                        415,
                        "unsupported_media_type",
                        "Only JPEG, PNG, and WebP images are supported.",
                        {"allowedMimeTypes": list(SUPPORTED_MIME_TYPES)},
                    )

                if width <= 0 or height <= 0:
                    raise AppError(
                        415, "invalid_image", "The uploaded image has invalid dimensions."
                    )

                # Pixel limits are enforced before reading EXIF or decoding pixels:
                # Pillow's PNG getexif() and load() both materialize image data.
                if width * height > max_pixels:
                    raise _pixel_error(width, height, max_pixels)

                if getattr(image, "n_frames", 1) > 1:
                    raise AppError(
                        415,
                        "animated_not_supported",
                        "Animated images are not supported.",
                    )

                orientation = _read_orientation(image)
                image.load()
    except AppError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise AppError(
            413,
            "image_too_many_pixels",
            "The image dimensions exceed the configured pixel limit.",
            {"maxPixels": max_pixels},
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise AppError(415, "invalid_image", "The uploaded file is not a valid image.") from exc

    if detected_format != expected_format:
        raise AppError(
            415,
            "mime_mismatch",
            "The declared content type does not match the actual image format.",
            {
                "declaredMimeType": declared_mime,
                "detectedMimeType": FORMAT_INFO[detected_format][1],
            },
        )

    display_width, display_height = display_dimensions(width, height, orientation)
    extension, mime_type = FORMAT_INFO[detected_format]
    return DecodedImage(
        detected_format=detected_format,
        mime_type=mime_type,
        extension=extension,
        width=display_width,
        height=display_height,
        exif_orientation=orientation,
    )
