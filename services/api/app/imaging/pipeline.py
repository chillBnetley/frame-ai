from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.imaging.color_ops import apply_color
from app.imaging.detail import apply_detail
from app.imaging.geometry import crop_pixels, rotate_inscribed
from app.imaging.loader import LoadedImage, resize_to_max_edge
from app.imaging.local import apply_local
from app.imaging.output import to_uint8
from app.imaging.params_map import DRAFT_MAX_EDGE, FINAL_MAX_EDGE
from app.imaging.tone import apply_contrast, apply_tone_linear, linear_to_srgb, srgb_to_linear
from app.models.recipe import Adjustments, RenderQuality


@dataclass(frozen=True)
class RenderedImage:
    rgb: NDArray[np.uint8]
    canvas_width: int
    canvas_height: int
    quality: RenderQuality

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])


def tier_max_edge(quality: RenderQuality) -> int | None:
    if quality == "draft":
        return DRAFT_MAX_EDGE
    if quality == "final":
        return FINAL_MAX_EDGE
    return None


def _resolve_edge(quality: RenderQuality, max_edge: int | None) -> int | None:
    if max_edge is not None:
        if max_edge <= 0:
            raise ValueError("max_edge must be positive")
        return max_edge
    return tier_max_edge(quality)


def render(
    image: LoadedImage,
    adjustments: Adjustments,
    *,
    image_sha256: str,
    quality: RenderQuality = "final",
    max_edge: int | None = None,
) -> RenderedImage:
    source = image
    edge = _resolve_edge(quality, max_edge)
    if edge is not None:
        source = resize_to_max_edge(source, edge)

    rotated = rotate_inscribed(source.rgb, adjustments.rotation_deg, quality=quality)
    canvas_height, canvas_width = rotated.shape[:2]
    cropped = crop_pixels(rotated, adjustments.crop)

    linear = srgb_to_linear(cropped)
    linear = apply_tone_linear(
        linear,
        exposure_ev=adjustments.exposure_ev,
        temperature=adjustments.temperature,
        tint=adjustments.tint,
        highlights=adjustments.highlights,
        shadows=adjustments.shadows,
    )
    perceptual = linear_to_srgb(linear)
    perceptual = apply_contrast(perceptual, adjustments.contrast)
    perceptual = apply_color(
        perceptual,
        saturation=adjustments.saturation,
        vibrance=adjustments.vibrance,
    )
    perceptual = apply_local(
        perceptual,
        clarity=adjustments.clarity,
        vignette=adjustments.vignette,
    )
    perceptual = apply_detail(
        perceptual,
        denoise=adjustments.denoise,
        sharpen=adjustments.sharpen,
        grain=adjustments.grain,
        image_sha256=image_sha256,
        quality=quality,
    )

    return RenderedImage(
        rgb=to_uint8(perceptual),
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        quality=quality,
    )
