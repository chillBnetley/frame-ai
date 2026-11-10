from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from app.models.generative import GenerativeOutpaintAlignment, GenerativeOutpaintParams

PixelArray = NDArray[np.uint8]
MaskArray = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class OutpaintGeometry:
    """Calculated canvas and coordinate geometry for an outpainting task."""

    base_width: int
    base_height: int
    target_width: int
    target_height: int
    offset_x: int  # left margin
    offset_y: int  # top margin

    @property
    def top(self) -> int:
        return self.offset_y

    @property
    def left(self) -> int:
        return self.offset_x

    @property
    def bottom(self) -> int:
        return self.target_height - (self.offset_y + self.base_height)

    @property
    def right(self) -> int:
        return self.target_width - (self.offset_x + self.base_width)

    @property
    def total_expanded_pixels(self) -> int:
        return (self.target_width * self.target_height) - (self.base_width * self.base_height)


def parse_aspect_ratio(ratio_str: str) -> tuple[int, int]:
    """Parse an aspect ratio string like '16:9', '4/3', or '1:1' into positive integers."""
    cleaned = ratio_str.strip()
    if not cleaned:
        raise ValueError("Aspect ratio string cannot be empty")
    delimiter = ":" if ":" in cleaned else ("/" if "/" in cleaned else None)
    if delimiter is not None:
        parts = cleaned.split(delimiter)
        if len(parts) == 2:
            try:
                rw = float(parts[0].strip())
                rh = float(parts[1].strip())
                if rw > 0 and rh > 0:
                    if rw.is_integer() and rh.is_integer():
                        return int(rw), int(rh)
                    mult = 1000
                    return int(round(rw * mult)), int(round(rh * mult))
            except ValueError:
                pass
    try:
        val = float(cleaned)
        if val > 0:
            return int(round(val * 1000)), 1000
    except ValueError:
        pass
    raise ValueError(
        f"Invalid aspect ratio: {ratio_str!r}. Expected format like '16:9', '1:1', or '4:3'."
    )


def compute_outpaint_geometry(
    base_width: int,
    base_height: int,
    params: GenerativeOutpaintParams,
    *,
    max_scale: float = 4.0,
) -> OutpaintGeometry:
    """Calculate the target dimensions and offset placement for outpainting."""
    if base_width <= 0 or base_height <= 0:
        raise ValueError("Base image dimensions must be positive.")

    left = params.left
    right = params.right
    top = params.top
    bottom = params.bottom

    cur_w = base_width + left + right
    cur_h = base_height + top + bottom

    if params.aspect_ratio:
        rw, rh = parse_aspect_ratio(params.aspect_ratio)
        if rw * cur_h >= rh * cur_w:
            target_h = cur_h
            target_w = int(np.ceil(cur_h * rw / rh))
        else:
            target_w = cur_w
            target_h = int(np.ceil(cur_w * rh / rw))

        extra_w = target_w - cur_w
        extra_h = target_h - cur_h

        align = (
            params.alignment.value
            if isinstance(params.alignment, GenerativeOutpaintAlignment)
            else str(params.alignment)
        )

        if align == "left":
            right += extra_w
        elif align == "right":
            left += extra_w
        else:
            left_half = extra_w // 2
            right_half = extra_w - left_half
            left += left_half
            right += right_half

        if align == "top":
            bottom += extra_h
        elif align == "bottom":
            top += extra_h
        else:
            top_half = extra_h // 2
            bottom_half = extra_h - top_half
            top += top_half
            bottom += bottom_half

    target_width = base_width + left + right
    target_height = base_height + top + bottom

    total_added = (target_width - base_width) + (target_height - base_height)
    if total_added <= 0:
        raise ValueError("Outpainting requires expanding at least one edge.")

    target_pixels = target_width * target_height
    base_pixels = base_width * base_height
    if target_pixels > max_scale * base_pixels:
        raise ValueError(
            f"Target area ({target_width}x{target_height}) "
            f"exceeds maximum allowed {max_scale:.1f}x expansion."
        )

    return OutpaintGeometry(
        base_width=base_width,
        base_height=base_height,
        target_width=target_width,
        target_height=target_height,
        offset_x=left,
        offset_y=top,
    )


def build_outpaint_canvas(
    base_pixels: PixelArray,
    geometry: OutpaintGeometry,
    *,
    inner_mask: MaskArray | None = None,
) -> tuple[PixelArray, MaskArray]:
    """Generate the expanded input canvas and corresponding generative mask.

    The mask is 255 for editable regions (all outpainted area plus any inner_mask)
    and 0 for strictly protected areas (the base image minus inner_mask).
    """
    if base_pixels.shape[:2] != (geometry.base_height, geometry.base_width):
        raise ValueError("base_pixels dimensions do not match geometry.")

    canvas = cv2.copyMakeBorder(
        base_pixels,
        top=geometry.top,
        bottom=geometry.bottom,
        left=geometry.left,
        right=geometry.right,
        borderType=cv2.BORDER_REFLECT_101,
    )
    canvas[
        geometry.top : geometry.top + geometry.base_height,
        geometry.left : geometry.left + geometry.base_width,
    ] = base_pixels

    mask = np.full(
        (geometry.target_height, geometry.target_width),
        255,
        dtype=np.uint8,
    )
    mask[
        geometry.top : geometry.top + geometry.base_height,
        geometry.left : geometry.left + geometry.base_width,
    ] = 0

    if inner_mask is not None:
        if inner_mask.shape != (geometry.base_height, geometry.base_width):
            raise ValueError("inner_mask dimensions do not match base image.")
        mask[
            geometry.top : geometry.top + geometry.base_height,
            geometry.left : geometry.left + geometry.base_width,
        ] = inner_mask

    return np.ascontiguousarray(canvas, dtype=np.uint8), np.ascontiguousarray(mask, dtype=np.uint8)


def restore_outpaint_protected_region(
    base_pixels: PixelArray,
    generated_pixels: PixelArray,
    geometry: OutpaintGeometry,
    *,
    inner_mask: MaskArray | None = None,
) -> tuple[PixelArray, list[str]]:
    """Restore base pixels to guaranteed byte identity and validate outpainted output."""
    if generated_pixels.shape[:2] != (geometry.target_height, geometry.target_width):
        raise ValueError(
            f"Generated dimensions ({generated_pixels.shape[1]}x{generated_pixels.shape[0]}) "
            f"do not match target canvas ({geometry.target_width}x{geometry.target_height})."
        )
    if base_pixels.shape[:2] != (geometry.base_height, geometry.base_width):
        raise ValueError("Base image dimensions do not match geometry.")

    output = np.array(generated_pixels, copy=True)
    y_slice = slice(geometry.top, geometry.top + geometry.base_height)
    x_slice = slice(geometry.left, geometry.left + geometry.base_width)

    if inner_mask is None:
        output[y_slice, x_slice] = base_pixels
    else:
        gen_base = output[y_slice, x_slice]
        alpha = inner_mask.astype(np.float32) / 255.0
        blended = (
            base_pixels.astype(np.float32) * (1.0 - alpha[..., None])
            + gen_base.astype(np.float32) * alpha[..., None]
        )
        base_restored = np.clip(np.rint(blended), 0.0, 255.0).astype(np.uint8)
        protected_pixels = inner_mask == 0
        base_restored[protected_pixels] = base_pixels[protected_pixels]
        output[y_slice, x_slice] = base_restored

    mask_outpaint = np.ones((geometry.target_height, geometry.target_width), dtype=bool)
    mask_outpaint[y_slice, x_slice] = False
    outpaint_pixels = output[mask_outpaint]

    if float(np.std(outpaint_pixels.astype(np.float32))) < 0.5:
        raise ValueError("Outpainted region lacks visible variation or is blank.")

    warnings = ["protected_region_restored", "outpaint_region_extended"]
    return np.ascontiguousarray(output, dtype=np.uint8), warnings


__all__ = [
    "OutpaintGeometry",
    "build_outpaint_canvas",
    "compute_outpaint_geometry",
    "parse_aspect_ratio",
    "restore_outpaint_protected_region",
]
