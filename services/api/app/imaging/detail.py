from __future__ import annotations

import hashlib

import cv2
import numpy as np
from numpy.typing import NDArray

from app.imaging.params_map import (
    DENOISE_H,
    DENOISE_SEARCH_DRAFT,
    DENOISE_SEARCH_FINAL,
    DENOISE_TEMPLATE_DRAFT,
    DENOISE_TEMPLATE_FINAL,
    GRAIN_AMPLITUDE,
    GRAIN_BLUR_SIGMA_RATIO,
    GRAIN_MAX_SIGMA,
    GRAIN_MIN_SIGMA,
    GRAIN_SEED_SUFFIX,
    SHARPEN_MAX_SIGMA,
    SHARPEN_MIN_SIGMA,
    SHARPEN_SIGMA_RATIO,
    SHARPEN_STRENGTH,
    SHARPEN_THRESHOLD,
)
from app.imaging.tone import luminance_srgb
from app.models.recipe import RenderQuality

RgbArray = NDArray[np.float32]
_EPSILON = np.float32(1e-6)


def _blur(channel: NDArray[np.float32], sigma: float) -> NDArray[np.float32]:
    return np.asarray(
        cv2.GaussianBlur(
            channel,
            (0, 0),
            sigmaX=sigma,
            sigmaY=sigma,
            borderType=cv2.BORDER_REFLECT_101,
        ),
        dtype=np.float32,
    )


def grain_seed(image_sha256: str) -> int:
    digest = hashlib.sha256(f"{image_sha256.lower()}{GRAIN_SEED_SUFFIX}".encode()).digest()
    return int.from_bytes(digest[:8], "little")


def apply_denoise(rgb: RgbArray, amount: float, *, quality: RenderQuality = "final") -> RgbArray:
    if amount == 0:
        return rgb

    strength = DENOISE_H * amount / 100.0
    if quality == "draft":
        template, search = DENOISE_TEMPLATE_DRAFT, DENOISE_SEARCH_DRAFT
    else:
        template, search = DENOISE_TEMPLATE_FINAL, DENOISE_SEARCH_FINAL

    source = np.clip(np.rint(rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    denoised = cv2.fastNlMeansDenoisingColored(
        source,
        None,
        float(strength),
        float(strength),
        template,
        search,
    )
    return np.ascontiguousarray(denoised.astype(np.float32) / np.float32(255.0))


def apply_sharpen(rgb: RgbArray, amount: float) -> RgbArray:
    if amount == 0:
        return rgb

    height, width = rgb.shape[:2]
    sigma = min(max(SHARPEN_SIGMA_RATIO * max(width, height), SHARPEN_MIN_SIGMA), SHARPEN_MAX_SIGMA)
    luminance = luminance_srgb(rgb)
    detail = luminance - _blur(luminance, sigma)
    thresholded = np.sign(detail) * np.maximum(np.abs(detail) - np.float32(SHARPEN_THRESHOLD), 0.0)
    adjusted = luminance + thresholded * np.float32(SHARPEN_STRENGTH * amount / 100.0)

    ratio = np.ones_like(luminance)
    np.divide(adjusted, luminance, out=ratio, where=luminance > _EPSILON)
    return np.ascontiguousarray(np.clip(rgb * ratio[..., None], 0.0, 1.0))


def apply_grain(rgb: RgbArray, amount: float, *, image_sha256: str) -> RgbArray:
    if amount == 0:
        return rgb

    height, width = rgb.shape[:2]
    sigma = min(
        max(GRAIN_BLUR_SIGMA_RATIO * max(width, height), GRAIN_MIN_SIGMA),
        GRAIN_MAX_SIGMA,
    )
    rng = np.random.default_rng(grain_seed(image_sha256))
    noise = _blur(rng.standard_normal((height, width)).astype(np.float32), sigma)
    noise = (noise - np.float32(noise.mean())) / max(float(noise.std()), 1e-6)

    luminance = luminance_srgb(rgb)
    weight = np.float32(0.2) + np.float32(0.8) * (
        np.float32(1.0) - (np.float32(2.0) * luminance - np.float32(1.0)) ** 2
    )
    delta = noise * weight * np.float32(GRAIN_AMPLITUDE * amount / 100.0)
    return np.ascontiguousarray(np.clip(rgb + delta[..., None], 0.0, 1.0))


def apply_detail(
    rgb: RgbArray,
    *,
    denoise: float,
    sharpen: float,
    grain: float,
    image_sha256: str,
    quality: RenderQuality = "final",
) -> RgbArray:
    result = apply_denoise(rgb, denoise, quality=quality)
    result = apply_sharpen(result, sharpen)
    return apply_grain(result, grain, image_sha256=image_sha256)
