from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import cv2
import numpy as np
import tifffile
from numpy.typing import NDArray
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from app.core.errors import AppError
from app.imaging.icc import UnsupportedProfileError, is_srgb_matrix_trc, transform_to_srgb

logger = logging.getLogger("frame_ai.loader")

PROXY_VERSION = "loader/3"
PROXY_SUBDIR = "proxies"
PROXY_EDGE_STEP = 64
_UINT16_MODES = {"I;16", "I;16B", "I;16L", "I;16N"}
_SRGB_PROFILE = ImageCms.createProfile("sRGB")
# Windows refuses to replace a file another handle has open, so concurrent
# writers of the same content-addressed proxy must not race on the rename.
_PROXY_WRITE_LOCK = threading.Lock()


_ALPHA_EPSILON = 1e-6

BitDepth = Literal[8, 16]

# TIFF compression values accepted by the input gate. 1 = none, 8 = Adobe
# deflate, 32946 = deflate. LZW/JPEG need imagecodecs/Pillow codecs whose
# behaviour is not part of this contract, so they are rejected explicitly.
_TIFF_ALLOWED_COMPRESSION = frozenset({1, 8, 32946})
_TIFF_COMPRESSION_TAG = 259
_TIFF_BITS_PER_SAMPLE_TAG = 258
_TIFF_WIDTH_TAG = 256
_TIFF_HEIGHT_TAG = 257
_TIFF_EXTRASAMPLES_TAG = 338
_TIFF_ASSOCIATED_ALPHA = 1


@dataclass(frozen=True)
class LoadedImage:
    rgb: NDArray[np.float32]
    alpha: NDArray[np.float32] | None = None
    bit_depth: BitDepth = 8

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])

    @property
    def has_alpha(self) -> bool:
        return self.alpha is not None


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


def _apply_embedded_profile(image: Image.Image) -> Image.Image:
    raw = image.info.get("icc_profile")
    if not isinstance(raw, bytes) or not raw or image.mode not in {"RGB", "RGBA"}:
        return image
    try:
        source = ImageCms.ImageCmsProfile(BytesIO(raw))
        if str(source.profile.xcolor_space).strip() != "RGB":
            return image
        if "srgb" in (ImageCms.getProfileDescription(source) or "").lower():
            return image
        converted = ImageCms.profileToProfile(
            image.convert("RGB"),
            source,
            _SRGB_PROFILE,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        )
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return image
    if converted is None:
        return image
    if image.mode == "RGBA":
        converted.putalpha(image.getchannel("A"))
    return converted


def _to_float_rgb(image: Image.Image) -> NDArray[np.float32]:
    mode = image.mode
    if mode in _UINT16_MODES or mode == "I":
        values = np.asarray(image, dtype=np.float32) / np.float32(65535.0)
        gray = np.clip(values, 0.0, 1.0)
        return np.ascontiguousarray(np.repeat(gray[..., None], 3, axis=2))
    if mode == "F":
        gray = np.clip(np.asarray(image, dtype=np.float32), 0.0, 1.0)
        return np.ascontiguousarray(np.repeat(gray[..., None], 3, axis=2))

    # Profiles are applied after mode normalization so P/1/L/LA inputs are managed too.
    if mode == "CMYK":
        rgb_image = _cmyk_to_rgb(image)
    elif mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = _apply_embedded_profile(image.convert("RGBA"))
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        rgb_image = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        rgb_image = _apply_embedded_profile(image.convert("RGB"))

    data = np.asarray(rgb_image, dtype=np.float32)
    data /= np.float32(255.0)
    return np.ascontiguousarray(data)


def _to_float_rgba(
    image: Image.Image,
) -> tuple[NDArray[np.float32], NDArray[np.float32] | None]:
    """Split alpha instead of compositing it onto white."""
    mode = image.mode
    if mode not in {"RGBA", "LA"} and "transparency" not in image.info:
        return _to_float_rgb(image), None

    rgba = _apply_embedded_profile(image.convert("RGBA"))
    data = np.asarray(rgba, dtype=np.float32)
    data /= np.float32(255.0)
    rgb = np.ascontiguousarray(data[..., :3])
    alpha = np.ascontiguousarray(data[..., 3])
    return rgb, alpha


def _source_prefix(source: Path | bytes, length: int) -> bytes:
    if isinstance(source, bytes):
        return source[:length]
    try:
        with source.open("rb") as handle:
            return handle.read(length)
    except OSError:
        return b""


def _read_source_bytes(source: Path | bytes) -> bytes:
    return source if isinstance(source, bytes) else source.read_bytes()


def _png_bit_depth(prefix: bytes) -> int:
    # 8-byte signature, then the IHDR length/type, then width (4), height (4),
    # bit depth at offset 24 and colour type at offset 25.
    if len(prefix) < 26 or prefix[:8] != b"\x89PNG\r\n\x1a\n":
        return 8
    if prefix[12:16] != b"IHDR":
        return 8
    return int(prefix[24])


def _tiff_tag_value(image: Image.Image, tag: int, default: Any) -> Any:
    tag_v2 = getattr(image, "tag_v2", None)
    if tag_v2 is None:
        return default
    try:
        return tag_v2.get(tag, default)
    except (AttributeError, KeyError, TypeError, ValueError):
        return default


def tiff_bits_per_sample(image: Image.Image) -> int:
    value = _tiff_tag_value(image, _TIFF_BITS_PER_SAMPLE_TAG, 8)
    if isinstance(value, (tuple, list)):
        samples = [int(item) for item in value if isinstance(item, (int, np.integer))]
        return max(samples, default=8)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 8


def tiff_extra_samples(image: Image.Image) -> tuple[int, ...]:
    value = _tiff_tag_value(image, _TIFF_EXTRASAMPLES_TAG, ())
    if value is None:
        return ()
    items = value if isinstance(value, (tuple, list)) else (value,)
    samples: list[int] = []
    for item in items:
        try:
            samples.append(int(item))
        except (TypeError, ValueError):
            samples.append(-1)
    return tuple(samples)


def validate_tiff_container(image: Image.Image) -> None:
    """Reject multi-page, compression and premultiplied-alpha variants."""
    frames = int(getattr(image, "n_frames", 1))
    if frames > 1:
        raise AppError(
            415,
            "tiff_multipage_not_supported",
            "Multi-page TIFF files are not supported.",
            {"pages": frames},
        )
    compression = _tiff_tag_value(image, _TIFF_COMPRESSION_TAG, 1)
    try:
        compression_value = int(compression)
    except (TypeError, ValueError):
        compression_value = -1
    if compression_value not in _TIFF_ALLOWED_COMPRESSION:
        raise AppError(
            415,
            "unsupported_tiff_compression",
            "This TIFF compression is not supported; use uncompressed or deflate.",
            {"compression": compression_value},
        )
    extra_samples = tiff_extra_samples(image)
    if _TIFF_ASSOCIATED_ALPHA in extra_samples:
        raise AppError(
            415,
            "associated_alpha_not_supported",
            "TIFF associated (premultiplied) alpha is not supported; use unassociated alpha.",
            {
                "extraSamples": list(extra_samples),
                "supported": "unassociated alpha only",
            },
        )


def image_bit_depth(image: Image.Image, source: Path | bytes) -> BitDepth:
    """Probe the stored sample depth without decoding pixel data twice."""
    if image.format == "PNG":
        return 16 if _png_bit_depth(_source_prefix(source, 26)) == 16 else 8
    if image.format == "TIFF":
        return 16 if tiff_bits_per_sample(image) >= 16 else 8
    if image.mode in _UINT16_MODES or image.mode == "I":
        return 16
    return 8


def probe_bit_depth(source: Path | bytes) -> BitDepth:
    """Cheap public probe for cache/memory decisions; failures read as 8-bit."""
    try:
        with _open_source(source) as image:
            return image_bit_depth(image, source)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return 8


def _orientation(image: Image.Image) -> int:
    try:
        value = image.getexif().get(0x0112, 1)
    except (OSError, SyntaxError, ValueError):
        return 1
    if isinstance(value, int) and 1 <= value <= 8:
        return value
    return 1


def _orient_array(
    rgb: NDArray[np.float32],
    alpha: NDArray[np.float32] | None,
    orientation: int,
) -> tuple[NDArray[np.float32], NDArray[np.float32] | None]:
    if orientation == 1:
        return rgb, alpha
    if orientation == 2:
        rgb = np.fliplr(rgb)
        alpha = None if alpha is None else np.fliplr(alpha)
    elif orientation == 3:
        rgb = np.rot90(rgb, 2)
        alpha = None if alpha is None else np.rot90(alpha, 2)
    elif orientation == 4:
        rgb = np.flipud(rgb)
        alpha = None if alpha is None else np.flipud(alpha)
    elif orientation == 5:
        rgb = np.swapaxes(rgb, 0, 1)
        alpha = None if alpha is None else np.swapaxes(alpha, 0, 1)
    elif orientation == 6:
        rgb = np.rot90(rgb, -1)
        alpha = None if alpha is None else np.rot90(alpha, -1)
    elif orientation == 7:
        rgb = np.flipud(np.fliplr(np.swapaxes(rgb, 0, 1)))
        alpha = None if alpha is None else np.flipud(np.fliplr(np.swapaxes(alpha, 0, 1)))
    elif orientation == 8:
        rgb = np.rot90(rgb, 1)
        alpha = None if alpha is None else np.rot90(alpha, 1)
    return np.ascontiguousarray(rgb), None if alpha is None else np.ascontiguousarray(alpha)


def _apply_sixteen_bit_profile(
    rgb: NDArray[np.float32],
    raw_profile: bytes | None,
) -> NDArray[np.float32]:
    if not raw_profile or is_srgb_matrix_trc(raw_profile):
        return rgb
    try:
        return transform_to_srgb(rgb, raw_profile)
    except UnsupportedProfileError as exc:
        raise AppError(
            422,
            "unsupported_icc_profile",
            "The embedded ICC profile is not supported for 16-bit input.",
            {"reason": str(exc)},
        ) from exc


def _decode_sixteen_bit_pixels(
    payload: bytes,
    image_format: str,
) -> tuple[NDArray[np.uint16], NDArray[np.uint16] | None]:
    if image_format == "PNG":
        # Pillow has no 16-bit RGB mode and silently truncates samples on load;
        # OpenCV preserves CV_16U exactly and returns BGR(A).
        decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None or decoded.dtype != np.uint16 or decoded.ndim != 3:
            raise AppError(415, "invalid_image", "The 16-bit image could not be decoded.")
        if decoded.shape[2] == 3:
            return np.ascontiguousarray(decoded[..., ::-1]), None
        if decoded.shape[2] == 4:
            return (
                np.ascontiguousarray(decoded[..., [2, 1, 0]]),
                np.ascontiguousarray(decoded[..., 3]),
            )
        raise AppError(415, "invalid_image", "The 16-bit image has unsupported channels.")

    if image_format == "TIFF":
        try:
            with tifffile.TiffFile(BytesIO(payload)) as tiff:
                page = tiff.pages[0]
                if not isinstance(page, tifffile.TiffPage):
                    raise AppError(
                        415,
                        "invalid_image",
                        "The 16-bit TIFF is not a single image page.",
                    )
                planar_config = int(page.planarconfig)
                samples = int(page.samplesperpixel)
                tiff_width = int(page.tags[_TIFF_WIDTH_TAG].value)
                tiff_height = int(page.tags[_TIFF_HEIGHT_TAG].value)
                array = np.asarray(page.asarray())
        except (IndexError, KeyError, OSError, TypeError, ValueError) as exc:
            raise AppError(415, "invalid_image", "The 16-bit TIFF could not be decoded.") from exc
        if array.dtype != np.uint16 or array.ndim != 3:
            raise AppError(415, "invalid_image", "The 16-bit TIFF is not an RGB image.")
        if planar_config == 2:
            # PlanarConfiguration=2 stores samples as (S, H, W).  It must be
            # identified from the TIFF tags, never inferred from a trailing
            # dimension of 3/4: a 3-pixel-wide chunky image has that shape too.
            if samples not in {3, 4} or array.shape != (samples, tiff_height, tiff_width):
                raise AppError(
                    415,
                    "invalid_image",
                    "The 16-bit TIFF layout does not match its metadata.",
                )
            array = np.moveaxis(array, 0, -1)
        elif planar_config == 1:
            if samples not in {3, 4} or array.shape != (tiff_height, tiff_width, samples):
                raise AppError(
                    415,
                    "invalid_image",
                    "The 16-bit TIFF layout does not match its metadata.",
                )
        else:
            raise AppError(
                415,
                "invalid_image",
                "The 16-bit TIFF has an unsupported planar configuration.",
            )
        if array.shape[-1] == 3:
            return np.ascontiguousarray(array), None
        return (
            np.ascontiguousarray(array[..., :3]),
            np.ascontiguousarray(array[..., 3]),
        )

    raise AppError(415, "invalid_image", "The image could not be decoded.")


def _load_sixteen_bit(
    source: Path | bytes,
    image: Image.Image,
    *,
    preserve_alpha: bool,
) -> LoadedImage:
    payload = _read_source_bytes(source)
    rgb16, alpha16 = _decode_sixteen_bit_pixels(payload, str(image.format))
    rgb = np.ascontiguousarray(rgb16.astype(np.float32) / np.float32(65535.0))
    alpha = (
        None
        if alpha16 is None
        else np.ascontiguousarray(alpha16.astype(np.float32) / np.float32(65535.0))
    )
    raw_profile = image.info.get("icc_profile")
    rgb = _apply_sixteen_bit_profile(rgb, raw_profile if isinstance(raw_profile, bytes) else None)
    rgb, alpha = _orient_array(rgb, alpha, _orientation(image))
    if alpha is not None and not preserve_alpha:
        rgb = np.ascontiguousarray(rgb * alpha[..., None] + (np.float32(1.0) - alpha[..., None]))
        alpha = None
    return LoadedImage(rgb=rgb, alpha=alpha, bit_depth=16)


def load_image(
    source: Path | bytes,
    *,
    max_pixels: int | None = None,
    preserve_alpha: bool = True,
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
                if image.format == "TIFF":
                    validate_tiff_container(image)
                if getattr(image, "n_frames", 1) > 1:
                    raise AppError(
                        415,
                        "animated_not_supported",
                        "Animated images are not supported.",
                    )
                depth = image_bit_depth(image, source)
                if (
                    depth == 16
                    and image.format in {"PNG", "TIFF"}
                    and image.mode in {"RGB", "RGBA"}
                ):
                    # 16-bit RGB/RGBA bypasses Pillow, which would truncate the
                    # samples before the profile or pipeline ever sees them.
                    return _load_sixteen_bit(source, image, preserve_alpha=preserve_alpha)
                image.load()
                oriented = ImageOps.exif_transpose(image)
                if preserve_alpha:
                    rgb, alpha = _to_float_rgba(oriented)
                else:
                    rgb, alpha = _to_float_rgb(oriented), None
                depth = 16 if oriented.mode in _UINT16_MODES or oriented.mode == "I" else 8
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

    return LoadedImage(rgb=rgb, alpha=alpha, bit_depth=depth)


def _resize_float_rgba(
    rgb: NDArray[np.float32],
    alpha: NDArray[np.float32],
    width: int,
    height: int,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Resize premultiplied colour so transparent pixels cannot bleed."""
    premultiplied = rgb * alpha[..., None]
    resized_rgb = cv2.resize(
        premultiplied,
        (width, height),
        interpolation=cv2.INTER_AREA,
    )
    resized_alpha = np.clip(
        cv2.resize(alpha, (width, height), interpolation=cv2.INTER_AREA),
        0.0,
        1.0,
    )
    safe = resized_alpha > _ALPHA_EPSILON
    unpremultiplied = np.zeros_like(resized_rgb)
    np.divide(
        resized_rgb,
        resized_alpha[..., None],
        out=unpremultiplied,
        where=safe[..., None],
    )
    unpremultiplied = np.clip(unpremultiplied, 0.0, 1.0)
    unpremultiplied[~safe] = 0.0
    return (
        np.ascontiguousarray(unpremultiplied),
        np.ascontiguousarray(resized_alpha),
    )


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
    if image.alpha is not None:
        rgb, alpha = _resize_float_rgba(
            image.rgb,
            image.alpha,
            target_width,
            target_height,
        )
        return LoadedImage(rgb=rgb, alpha=alpha, bit_depth=image.bit_depth)
    resized = cv2.resize(
        image.rgb,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )
    return LoadedImage(
        rgb=np.ascontiguousarray(np.clip(resized, 0.0, 1.0)),
        bit_depth=image.bit_depth,
    )


def proxy_cache_directory(preview_dir: Path) -> Path:
    return preview_dir / PROXY_SUBDIR


def _aligned_proxy_edge(max_edge: int) -> int:
    if max_edge <= 0:
        raise ValueError("max_edge must be positive")
    return ((max_edge + PROXY_EDGE_STEP - 1) // PROXY_EDGE_STEP) * PROXY_EDGE_STEP


def proxy_cache_path(
    cache_dir: Path,
    original_sha256: str,
    max_edge: int,
    *,
    bit_depth: BitDepth = 8,
) -> Path:
    try:
        digest = bytes.fromhex(original_sha256)
    except ValueError as exc:
        raise ValueError("original_sha256 must be hexadecimal") from exc
    if len(digest) != 32:
        raise ValueError("original_sha256 must be a 64-character sha256 digest")
    aligned_edge = _aligned_proxy_edge(max_edge)
    # 8-bit keys stay byte-identical to loader/3. A 16-bit source gets a
    # separate key so an old proxy built from truncated Pillow pixels is never
    # reused; the cached pixels are still RGB PNG.
    suffix = "|b16" if bit_depth == 16 else ""
    key = hashlib.sha256(
        f"{original_sha256.lower()}|{PROXY_VERSION}|{aligned_edge}{suffix}".encode()
    ).hexdigest()
    return cache_dir / f"{key}.png"


def _quantize(image: LoadedImage) -> LoadedImage:
    data = np.clip(np.rint(image.rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    return LoadedImage(rgb=np.ascontiguousarray(data.astype(np.float32) / 255.0))


def _write_proxy(image: LoadedImage, destination: Path) -> None:
    data = np.clip(np.rint(image.rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    with _PROXY_WRITE_LOCK:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(data, "RGB").save(temporary, format="PNG")
            for attempt in range(5):
                try:
                    os.replace(temporary, destination)
                    break
                except PermissionError:
                    if attempt == 4:
                        logger.warning("proxy_cache_write_failed path=%s", destination)
                        break
                    time.sleep(0.02)
        except OSError:
            logger.warning("proxy_cache_write_failed path=%s", destination)
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
    aligned_edge = _aligned_proxy_edge(max_edge)
    bit_depth = probe_bit_depth(source)
    path = proxy_cache_path(cache_dir, original_sha256, aligned_edge, bit_depth=bit_depth)
    if path.is_file():
        try:
            cached = load_image(path, preserve_alpha=False)
        except AppError:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        else:
            try:
                os.utime(path, None)
            except OSError:
                pass
            return resize_to_max_edge(cached, max_edge)

    # Proxies are RGB PNGs shared with the white-background preview path, so a
    # transparent source is composited here and never stored in the cache.
    loaded = load_image(source, max_pixels=max_pixels, preserve_alpha=False)
    if max(loaded.width, loaded.height) <= aligned_edge:
        return resize_to_max_edge(loaded, max_edge)

    proxy = _quantize(resize_to_max_edge(loaded, aligned_edge))
    _write_proxy(proxy, path)
    return resize_to_max_edge(proxy, max_edge)
