from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.imaging.color_grading import apply_color_grading
from app.imaging.color_ops import apply_color
from app.imaging.curves import apply_curves
from app.imaging.detail import apply_detail
from app.imaging.geometry import crop_pixels, rotate_inscribed
from app.imaging.hsl import apply_hsl
from app.imaging.loader import LoadedImage, resize_to_max_edge
from app.imaging.local import apply_local
from app.imaging.local_masks import apply_local_adjustments
from app.imaging.output import to_uint8
from app.imaging.params_map import (
    DRAFT_MAX_EDGE,
    EXPORT_DENOISE_SIMPLIFY_PIXELS,
    FINAL_MAX_EDGE,
)
from app.imaging.tone import apply_contrast, apply_tone_linear, linear_to_srgb, srgb_to_linear
from app.models.recipe import (
    Adjustments,
    ColorGrading,
    CurveSet,
    HslAdjustments,
    LocalAdjustment,
    RenderQuality,
    UserMask,
)


@dataclass(frozen=True)
class RenderedImage:
    rgb: NDArray[np.uint8]
    canvas_width: int
    canvas_height: int
    quality: RenderQuality
    warnings: tuple[str, ...] = ()

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
    curve: CurveSet | None = None,
    hsl: HslAdjustments | None = None,
    color_grading: ColorGrading | None = None,
    masks: tuple[UserMask, ...] = (),
    local_adjustments: tuple[LocalAdjustment, ...] = (),
    quality: RenderQuality = "final",
    max_edge: int | None = None,
    denoise_simplify_pixels: int = EXPORT_DENOISE_SIMPLIFY_PIXELS,
) -> RenderedImage:
    source = image
    edge = _resolve_edge(quality, max_edge)
    if edge is not None:
        source = resize_to_max_edge(source, edge)

    denoise_simplified = (
        quality == "export"
        and adjustments.denoise > 0
        and source.width * source.height > denoise_simplify_pixels
    )

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
        whites=adjustments.whites,
        blacks=adjustments.blacks,
    )
    perceptual = linear_to_srgb(linear, inplace=True)
    perceptual = apply_contrast(perceptual, adjustments.contrast)
    if curve is not None:
        perceptual = apply_curves(perceptual, curve)
    if hsl is not None:
        perceptual = apply_hsl(perceptual, hsl)
    perceptual = apply_color(
        perceptual,
        saturation=adjustments.saturation,
        vibrance=adjustments.vibrance,
    )
    if color_grading is not None:
        perceptual = apply_color_grading(perceptual, color_grading)
    render_warnings: list[str] = []
    if local_adjustments:
        perceptual, local_warnings = apply_local_adjustments(
            perceptual,
            local_adjustments,
            masks,
            source_width=source.width,
            source_height=source.height,
            rotation_deg=adjustments.rotation_deg,
            crop=adjustments.crop,
        )
        render_warnings.extend(local_warnings)
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
        denoise_simplified=denoise_simplified,
    )

    if denoise_simplified:
        render_warnings.append("denoise_simplified")
    return RenderedImage(
        rgb=to_uint8(perceptual, inplace=True),
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        quality=quality,
        warnings=tuple(render_warnings),
    )
