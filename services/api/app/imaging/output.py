from __future__ import annotations

import json
import logging
import struct
import zlib
from collections.abc import Mapping
from functools import lru_cache
from io import BytesIO
from typing import Any, Literal, TypeVar, cast

import cv2
import numpy as np
import tifffile
from numpy.typing import NDArray
from PIL import Image, ImageCms, PngImagePlugin

PROVENANCE_KEY = "FRAME-AI-Provenance"

ImageFormat = Literal["jpeg", "png", "tiff"]
BitDepth = Literal[8, 16]
logger = logging.getLogger("frame_ai.output")

FORMAT_INFO: dict[ImageFormat, tuple[str, str, str]] = {
    "jpeg": ("JPEG", ".jpg", "image/jpeg"),
    "png": ("PNG", ".png", "image/png"),
    "tiff": ("TIFF", ".tiff", "image/tiff"),
}
JPEG_QUALITY = 90

# PNG signature (8 bytes) + IHDR length/type/data/CRC (25 bytes).
_PNG_IHDR_END = 33
_ICC_PROFILE_NAME = b"sRGB"

_UInt = TypeVar("_UInt", np.uint8, np.uint16)


def to_uint8_alpha(alpha: NDArray[np.float32]) -> NDArray[np.uint8]:
    """Quantise a 0..1 coverage plane. Kept here so render stages stay float."""
    quantized = np.clip(np.rint(np.asarray(alpha, dtype=np.float32) * 255.0), 0.0, 255.0)
    return np.ascontiguousarray(quantized.astype(np.uint8))


def to_uint16_alpha(alpha: NDArray[np.float32]) -> NDArray[np.uint16]:
    """Quantise a 0..1 coverage plane to 16 bits."""
    quantized = np.clip(np.rint(np.asarray(alpha, dtype=np.float32) * 65535.0), 0.0, 65535.0)
    return np.ascontiguousarray(quantized.astype(np.uint16))


def _quantize_unit(
    rgb: NDArray[np.float32],
    maximum: float,
    dtype: type[_UInt],
    *,
    inplace: bool,
) -> NDArray[_UInt]:
    if not np.isfinite(rgb).all():
        # ``astype(uint8)`` turns NaN into 0 without a word.  Sanitize first and
        # say so: a non-finite pixel is an upstream bug, but shipping a silently
        # black frame hides it.
        logger.warning("non_finite_pixels_sanitized")
        rgb = np.nan_to_num(rgb, copy=not inplace, nan=0.0, posinf=1.0, neginf=0.0)
    scaled = rgb if inplace else rgb * np.float32(maximum)
    if inplace:
        np.multiply(scaled, np.float32(maximum), out=scaled)
    np.rint(scaled, out=scaled)
    np.clip(scaled, 0.0, maximum, out=scaled)
    quantized = scaled.astype(dtype)
    return np.ascontiguousarray(quantized)


def to_uint8(rgb: NDArray[np.float32], *, inplace: bool = False) -> NDArray[np.uint8]:
    return _quantize_unit(rgb, 255.0, np.uint8, inplace=inplace)


def to_uint16(rgb: NDArray[np.float32], *, inplace: bool = False) -> NDArray[np.uint16]:
    return _quantize_unit(rgb, 65535.0, np.uint16, inplace=inplace)


@lru_cache(maxsize=1)
def srgb_icc_profile() -> bytes:
    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    # lcms stamps the current time into the profile header, which would make
    # encoded bytes differ between processes. Pin it (2020-01-01 00:00:00).
    profile[24:36] = bytes.fromhex("07e400010001000000000000")
    return bytes(profile)


def _validate_alpha(
    pixels: NDArray[np.uint8] | NDArray[np.uint16],
    alpha: NDArray[np.uint8] | NDArray[np.uint16] | None,
) -> None:
    if alpha is None:
        return
    if alpha.dtype != pixels.dtype or alpha.shape != pixels.shape[:2]:
        raise ValueError("alpha must be an HxW array matching the pixels and dtype")


def _composite_on_white(
    pixels: NDArray[np.uint8],
    alpha: NDArray[np.uint8],
) -> NDArray[np.uint8]:
    coverage = alpha.astype(np.float32) / np.float32(255.0)
    composited = pixels.astype(np.float32) * coverage[..., None] + np.float32(255.0) * (
        np.float32(1.0) - coverage[..., None]
    )
    return np.ascontiguousarray(np.clip(np.rint(composited), 0.0, 255.0).astype(np.uint8))


def _format_provenance(provenance: Mapping[str, Any] | None) -> str | None:
    if not provenance:
        return None
    return json.dumps(provenance, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _insert_iccp(payload: bytes, profile: bytes) -> bytes:
    """Insert an iCCP chunk between PNG IHDR and the first image chunk."""
    compressed = zlib.compress(profile)
    data = _ICC_PROFILE_NAME + b"\0" + b"\0" + compressed
    chunk = _make_png_chunk(b"iCCP", data)
    return payload[:_PNG_IHDR_END] + chunk + payload[_PNG_IHDR_END:]


def _encode_png_sixteen(
    pixels: NDArray[np.uint16],
    alpha: NDArray[np.uint16] | None,
    provenance_text: str | None = None,
) -> bytes:
    # OpenCV expects BGR(A); a 16-bit RGB source cannot go through Pillow.
    bgr = np.ascontiguousarray(pixels[..., ::-1])
    source = bgr if alpha is None else np.ascontiguousarray(np.dstack([bgr, alpha]))
    success, buffer = cv2.imencode(".png", source)
    if not success:
        raise ValueError("the 16-bit PNG could not be encoded")
    raw = buffer.tobytes()
    chunks: list[bytes] = []
    compressed = zlib.compress(srgb_icc_profile())
    iccp_data = _ICC_PROFILE_NAME + b"\0" + b"\0" + compressed
    chunks.append(_make_png_chunk(b"iCCP", iccp_data))
    if provenance_text is not None:
        text_data = PROVENANCE_KEY.encode("latin-1") + b"\0" + provenance_text.encode("latin-1")
        chunks.append(_make_png_chunk(b"tEXt", text_data))
    return raw[:_PNG_IHDR_END] + b"".join(chunks) + raw[_PNG_IHDR_END:]


def _encode_tiff(
    pixels: NDArray[np.uint8] | NDArray[np.uint16],
    alpha: NDArray[np.uint8] | NDArray[np.uint16] | None,
    provenance_text: str | None = None,
) -> bytes:
    array = pixels if alpha is None else np.dstack([pixels, alpha])
    buffer = BytesIO()
    # Keep the container reproducible: no host name, tool version or clock.
    kwargs: dict[str, Any] = {
        "photometric": "rgb",
        "compression": "deflate",
        "iccprofile": srgb_icc_profile(),
        "metadata": None,
        "software": False,
        "datetime": False,
        "extrasamples": None if alpha is None else ["unassalpha"],
    }
    if provenance_text is not None:
        kwargs["description"] = f"FRAME-AI:{provenance_text}"
    tifffile.imwrite(
        buffer,
        np.ascontiguousarray(array),
        **kwargs,
    )
    return buffer.getvalue()


def encode_image(
    pixels: NDArray[np.uint8] | NDArray[np.uint16],
    *,
    image_format: ImageFormat = "jpeg",
    quality: int = JPEG_QUALITY,
    alpha: NDArray[np.uint8] | NDArray[np.uint16] | None = None,
    bit_depth: BitDepth = 8,
    provenance: Mapping[str, Any] | None = None,
) -> bytes:
    if bit_depth not in (8, 16):
        raise ValueError("bit_depth must be 8 or 16")
    if image_format not in FORMAT_INFO:
        raise ValueError(f"unsupported image format: {image_format}")
    if not 1 <= quality <= 100:
        raise ValueError("quality must be between 1 and 100")

    provenance_text = _format_provenance(provenance)

    if bit_depth == 16:
        if image_format == "jpeg":
            raise ValueError("JPEG does not support 16-bit output")
        if pixels.dtype != np.uint16 or pixels.ndim != 3 or pixels.shape[2] != 3:
            raise ValueError("16-bit pixels must be an HxWx3 uint16 array")
        _validate_alpha(pixels, alpha)
        sixteen_pixels = cast(NDArray[np.uint16], pixels)
        sixteen_alpha = cast(NDArray[np.uint16] | None, alpha)
        if image_format == "png":
            return _encode_png_sixteen(sixteen_pixels, sixteen_alpha, provenance_text)
        return _encode_tiff(sixteen_pixels, sixteen_alpha, provenance_text)

    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("pixels must be an HxWx3 uint8 array")
    _validate_alpha(pixels, alpha)
    eight_pixels = cast(NDArray[np.uint8], pixels)
    eight_alpha = cast(NDArray[np.uint8] | None, alpha)

    if image_format == "tiff":
        return _encode_tiff(eight_pixels, eight_alpha, provenance_text)

    format_name, _, _ = FORMAT_INFO[image_format]
    if image_format == "png":
        if eight_alpha is None:
            image = Image.fromarray(np.ascontiguousarray(eight_pixels))
        else:
            rgba = np.dstack([eight_pixels, eight_alpha])
            image = Image.fromarray(np.ascontiguousarray(rgba), mode="RGBA")
    else:
        encoded_pixels = (
            eight_pixels if eight_alpha is None else _composite_on_white(eight_pixels, eight_alpha)
        )
        image = Image.fromarray(np.ascontiguousarray(encoded_pixels))
    buffer = BytesIO()
    options: dict[str, object] = {"icc_profile": srgb_icc_profile()}
    if image_format == "jpeg":
        options["quality"] = quality
        options["subsampling"] = 0 if quality >= 90 else 2
        if provenance_text is not None:
            exif = Image.Exif()
            exif[0x010E] = f"FRAME-AI:{provenance_text}"
            exif[0x0131] = "FRAME AI"
            options["exif"] = exif.tobytes()
    elif image_format == "png":
        if provenance_text is not None:
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_text("Software", "FRAME AI")
            pnginfo.add_text(PROVENANCE_KEY, provenance_text)
            options["pnginfo"] = pnginfo
    image.save(buffer, format=format_name, **options)
    return buffer.getvalue()
