from __future__ import annotations

import hashlib
import os
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

PROXY_VERSION = "loader/1"
_UINT16_MODES = {"I;16", "I;16B", "I;16L", "I;16N"}


@dataclass(frozen=True)
class LoadedImage:
    rgb: NDArray[np.float32]

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])


def _open_source(source: Path | bytes) -> Image.Image:
    if isinstance(source, bytes):
        return Image.open(BytesIO(source))
    return Image.open(source)


def _cmyk_to_rgb(image: Image.Image) -> Image.Image:
    profile = image.info.get("icc_profile")
    if isinstance(profile, bytes) and profile:
        try:
            converted = ImageCms.profileToProfile(
                image,
                BytesIO(profile),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
            if converted is not None:
                return converted
        except (ImageCms.PyCMSError, OSError):
            pass
    return image.convert("RGB")


def _to_float_rgb(image: Image.Image) -> NDArray[np.float32]:
    mode = image.mode
    if mode in _UINT16_MODES or mode == "I":
        values = np.asarray(image, dtype=np.float32) / np.float32(65535.0)
        gray = np.clip(values, 0.0, 1.0)
        return np.ascontiguousarray(np.repeat(gray[..., None], 3, axis=2))
    if mode == "F":
        gray = np.clip(np.asarray(image, dtype=np.float32), 0.0, 1.0)
        return np.ascontiguousarray(np.repeat(gray[..., None], 3, axis=2))

    if mode == "CMYK":
        rgb_image = _cmyk_to_rgb(image)
    elif mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        rgb_image = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        rgb_image = image.convert("RGB")

    data = np.asarray(rgb_image, dtype=np.float32)
    data /= np.float32(255.0)
    return np.ascontiguousarray(data)


def load_image(
    source: Path | bytes,
    *,
    max_pixels: int | None = None,
) -> LoadedImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with _open_source(source) as image:
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise AppError(415, "invalid_image", "The image has invalid dimensions.")
                if max_pixels is not None and width * height > max_pixels:
                    raise AppError(
                        413,
                        "image_too_many_pixels",
                        "The image dimensions exceed the configured pixel limit.",
                        {"width": width, "height": height, "maxPixels": max_pixels},
                    )
                if getattr(image, "n_frames", 1) > 1:
                    raise AppError(
                        415,
                        "animated_not_supported",
                        "Animated images are not supported.",
                    )
                image.load()
                oriented = ImageOps.exif_transpose(image)
                rgb = _to_float_rgb(oriented)
    except AppError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise AppError(
            413,
            "image_too_many_pixels",
            "The image dimensions exceed the configured pixel limit.",
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise AppError(415, "invalid_image", "The image could not be decoded.") from exc

    return LoadedImage(rgb=rgb)


def resize_to_max_edge(image: LoadedImage, max_edge: int) -> LoadedImage:
    if max_edge <= 0:
        raise ValueError("max_edge must be positive")
    height, width = image.rgb.shape[:2]
    longest = max(width, height)
    if longest <= max_edge:
        return image

    scale = max_edge / longest
    target_width = max(1, round(width * scale))
    target_height = max(1, round(height * scale))
    resized = cv2.resize(
        image.rgb,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )
    return LoadedImage(rgb=np.ascontiguousarray(np.clip(resized, 0.0, 1.0)))


def proxy_cache_path(cache_dir: Path, original_sha256: str, max_edge: int) -> Path:
    try:
        digest = bytes.fromhex(original_sha256)
    except ValueError as exc:
        raise ValueError("original_sha256 must be hexadecimal") from exc
    if len(digest) != 32:
        raise ValueError("original_sha256 must be a 64-character sha256 digest")
    if max_edge <= 0:
        raise ValueError("max_edge must be positive")
    key = hashlib.sha256(
        f"{original_sha256.lower()}|{PROXY_VERSION}|{max_edge}".encode()
    ).hexdigest()
    return cache_dir / f"{key}.png"


def _quantize(image: LoadedImage) -> LoadedImage:
    data = np.clip(np.rint(image.rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    return LoadedImage(rgb=np.ascontiguousarray(data.astype(np.float32) / 255.0))


def _write_proxy(image: LoadedImage, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(np.rint(image.rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        Image.fromarray(data, "RGB").save(temporary, format="PNG")
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def load_proxy(
    source: Path | bytes,
    *,
    original_sha256: str,
    max_edge: int,
    cache_dir: Path,
    max_pixels: int | None = None,
) -> LoadedImage:
    path = proxy_cache_path(cache_dir, original_sha256, max_edge)
    if path.is_file():
        try:
            return load_image(path)
        except AppError:
            path.unlink(missing_ok=True)

    loaded = load_image(source, max_pixels=max_pixels)
    if max(loaded.width, loaded.height) <= max_edge:
        return loaded

    proxy = _quantize(resize_to_max_edge(loaded, max_edge))
    _write_proxy(proxy, path)
    return proxy
