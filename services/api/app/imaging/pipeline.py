from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from app.imaging.color_grading import apply_color_grading
from app.imaging.color_ops import apply_color
from app.imaging.curves import apply_curves
from app.imaging.detail import apply_detail
from app.imaging.geometry import apply_geometry, rotation_target_size
from app.imaging.hsl import apply_hsl
from app.imaging.loader import BitDepth, LoadedImage, resize_to_max_edge
from app.imaging.local import apply_local
from app.imaging.local_masks import apply_local_adjustments
from app.imaging.output import to_uint8, to_uint8_alpha
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


class RenderCancelled(Exception):
    """Raised when an export job's cancel token is set between render stages."""


def raise_if_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise RenderCancelled


@dataclass(frozen=True)
class RenderedImage:
    # 8-bit renders hand back quantised samples; 16-bit renders keep float32
    # perceptual values in [0, 1] so the export encoder decides the depth.
    rgb: NDArray[np.uint8] | NDArray[np.float32]
    canvas_width: int
    canvas_height: int
    quality: RenderQuality
    warnings: tuple[str, ...] = ()
    alpha: NDArray[np.uint8] | NDArray[np.float32] | None = None
    bit_depth: BitDepth = 8

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
    bit_depth: BitDepth = 8,
    cancel: threading.Event | None = None,
) -> RenderedImage:
    raise_if_cancelled(cancel)
    if bit_depth not in (8, 16):
        raise ValueError("bit_depth must be 8 or 16")
    source = image
    edge = _resolve_edge(quality, max_edge)
    if edge is not None:
        source = resize_to_max_edge(source, edge)

    denoise_simplified = (
        bit_depth == 8
        and quality == "export"
        and adjustments.denoise > 0
        and source.width * source.height > denoise_simplify_pixels
    )

    raise_if_cancelled(cancel)
    cropped, cropped_alpha = apply_geometry(
        source.rgb,
        source.alpha,
        rotation_deg=adjustments.rotation_deg,
        crop=adjustments.crop,
        quality=quality,
    )
    canvas_width, canvas_height = rotation_target_size(
        source.width,
        source.height,
        adjustments.rotation_deg,
    )

    raise_if_cancelled(cancel)
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
    raise_if_cancelled(cancel)
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
    raise_if_cancelled(cancel)
    perceptual = apply_detail(
        perceptual,
        # Denoise is decoded to 8 bits internally, which would defeat the point
        # of a 16-bit export. Skip it and say so instead of silently degrading.
        denoise=0.0 if bit_depth == 16 else adjustments.denoise,
        sharpen=adjustments.sharpen,
        grain=adjustments.grain,
        image_sha256=image_sha256,
        quality=quality,
        denoise_simplified=denoise_simplified,
    )

    if bit_depth == 16 and adjustments.denoise > 0:
        render_warnings.append("denoise_skipped_for_16bit")
    if denoise_simplified:
        render_warnings.append("denoise_simplified")
    raise_if_cancelled(cancel)
    if bit_depth == 16:
        rgb: NDArray[np.uint8] | NDArray[np.float32] = np.ascontiguousarray(perceptual)
        alpha: NDArray[np.uint8] | NDArray[np.float32] | None = (
            None
            if cropped_alpha is None
            else np.ascontiguousarray(np.clip(cropped_alpha, 0.0, 1.0))
        )
    else:
        rgb = to_uint8(perceptual, inplace=True)
        alpha = None if cropped_alpha is None else to_uint8_alpha(cropped_alpha)
    return RenderedImage(
        rgb=rgb,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        quality=quality,
        warnings=tuple(render_warnings),
        alpha=alpha,
        bit_depth=bit_depth,
    )
