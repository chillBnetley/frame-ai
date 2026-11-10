from __future__ import annotations

import hashlib
import math

import numpy as np
from numpy.typing import NDArray

PixelArray = NDArray[np.uint8]
MaskArray = NDArray[np.uint8]

_BLANK_STD_THRESHOLD = 0.5
_MIN_CORE_PIXELS = 16
_MAX_EDIT_COVERAGE = 0.95


def validate_local_edit_mask(mask: MaskArray) -> None:
    """Validate the editable region mask for a local generative edit."""
    if mask.ndim != 2:
        raise ValueError(f"Edit mask must be 2D grayscale, got shape {mask.shape}")
    if mask.size == 0:
        raise ValueError("Edit mask cannot be empty.")
    if int(np.count_nonzero(mask > 0)) == 0:
        raise ValueError("Edit mask has no active pixels to edit.")
    coverage = int(np.count_nonzero(mask > 0)) / mask.size
    if coverage > _MAX_EDIT_COVERAGE:
        raise ValueError(
            f"Edit mask coverage ({coverage:.1%}) exceeds maximum allowable "
            f"{_MAX_EDIT_COVERAGE:.0%}. "
            "Local editing requires a protected context region."
        )


def restore_local_edit_protected_region(
    input_pixels: PixelArray,
    output_pixels: PixelArray,
    mask: MaskArray,
) -> tuple[PixelArray, list[str]]:
    """Restore unmasked pixels byte-for-byte and validate the local repaint.

    - Outside the mask (mask == 0), original input pixels are strictly restored.
    - Transition zone (0 < mask < 255) uses alpha blending to remove hard seams.
    - Inside the edit core (mask >= 128) the output must have changed relative to
      the input and carry visible texture variance.
    """
    if input_pixels.shape != output_pixels.shape:
        raise ValueError(
            f"Input {input_pixels.shape} and output {output_pixels.shape} shapes must match."
        )
    if mask.shape != input_pixels.shape[:2]:
        raise ValueError(
            f"Mask shape {mask.shape} does not match image dimensions {input_pixels.shape[:2]}."
        )

    active = mask > 0
    if not np.any(active):
        raise ValueError("Edit mask has no editable pixels.")

    if np.array_equal(input_pixels[active], output_pixels[active]):
        raise ValueError("Edited area shows no visible change from the original photo.")

    core = mask >= 128
    if int(np.count_nonzero(core)) >= _MIN_CORE_PIXELS:
        if float(np.std(output_pixels[core].astype(np.float32))) < _BLANK_STD_THRESHOLD:
            raise ValueError("Edited region lacks visible variation or texture.")

    alpha = mask.astype(np.float32) / np.float32(255.0)
    blended = (
        input_pixels.astype(np.float32) * (np.float32(1.0) - alpha[..., None])
        + output_pixels.astype(np.float32) * alpha[..., None]
    )
    result = np.clip(np.rint(blended), 0.0, 255.0).astype(np.uint8)
    protected = mask == 0
    result[protected] = input_pixels[protected]

    return np.ascontiguousarray(result), ["protected_region_restored"]


def simulate_local_repaint(
    input_pixels: PixelArray,
    mask: MaskArray,
    instruction: str,
) -> PixelArray:
    """Deterministic stand-in for a masked instruction-driven repaint.

    Tint, gradient direction and texture scale all come from the prompt digest, so
    the same instruction always repaints the same way. Pixels outside the mask are
    copied from the input untouched.
    """
    if input_pixels.ndim != 3 or input_pixels.shape[2] != 3:
        raise ValueError(f"Input must be HxWx3 RGB, got shape {input_pixels.shape}")
    if mask.shape != input_pixels.shape[:2]:
        raise ValueError(
            f"Mask shape {mask.shape} does not match image dimensions {input_pixels.shape[:2]}."
        )

    height, width = mask.shape
    digest = hashlib.sha256(f"local|{instruction.strip().lower()}".encode()).digest()
    source = input_pixels.astype(np.float32)
    tint = np.array(
        (
            32.0 + digest[0] % 176,
            32.0 + digest[1] % 176,
            32.0 + digest[2] % 176,
        ),
        dtype=np.float32,
    )

    yy, xx = np.mgrid[0:height, 0:width]
    angle = (digest[3] / 255.0) * math.pi
    projected = xx * math.cos(angle) + yy * math.sin(angle)
    span = float(projected.max() - projected.min()) or 1.0
    ramp = (projected - float(projected.min())) / span
    ramp_strength = np.float32(12.0 + digest[4] % 28)

    cell = 6 + int(digest[5] % 18)
    checker = (((xx // cell) + (yy // cell)) % 2).astype(np.float32)

    repaint = source * np.float32(0.68) + tint * np.float32(0.32)
    repaint += ((ramp - np.float32(0.5)) * ramp_strength)[..., None]
    repaint += ((checker - np.float32(0.5)) * np.float32(14.0))[..., None]

    alpha = mask.astype(np.float32) / np.float32(255.0)
    blended = source * (np.float32(1.0) - alpha[..., None]) + repaint * alpha[..., None]
    pixels = np.clip(np.rint(blended), 0.0, 255.0).astype(np.uint8)
    pixels[mask == 0] = input_pixels[mask == 0]

    return np.ascontiguousarray(pixels)
