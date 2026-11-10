from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

PixelArray = NDArray[np.uint8]
MaskArray = NDArray[np.uint8]

_BLANK_STD_THRESHOLD = 0.5


def validate_removal_mask(mask: MaskArray) -> None:
    """Validate that the removal mask has valid coverage and non-zero editing target."""
    if mask.ndim != 2:
        raise ValueError(f"Removal mask must be 2D grayscale, got shape {mask.shape}")
    total_pixels = mask.size
    if total_pixels == 0:
        raise ValueError("Removal mask cannot be empty.")
    active_pixels = int(np.count_nonzero(mask > 0))
    if active_pixels == 0:
        raise ValueError("Removal mask has no active pixels to remove.")
    coverage = active_pixels / total_pixels
    if coverage > 0.95:
        raise ValueError(
            f"Removal mask coverage ({coverage:.1%}) exceeds maximum allowable 95%. "
            "Object removal requires surrounding context."
        )


def restore_removal_protected_region(
    input_pixels: PixelArray,
    output_pixels: PixelArray,
    mask: MaskArray,
) -> tuple[PixelArray, list[str]]:
    """Restores unmasked pixels byte-for-byte and validates inpainting changes.

    - Outside the mask (mask == 0), original input pixels are strictly restored.
    - Transition zone (0 < mask < 255) uses alpha-blending for smooth seam integration.
    - Inside the removal core (mask > 0), verifies that the output has visible variance
      and differs from the original input pixels.
    """
    if input_pixels.shape != output_pixels.shape:
        raise ValueError(
            f"Input {input_pixels.shape} and output {output_pixels.shape} shapes must match."
        )
    if mask.shape != input_pixels.shape[:2]:
        raise ValueError(
            f"Mask shape {mask.shape} does not match image dimensions {input_pixels.shape[:2]}."
        )

    active_mask = mask > 0
    if not np.any(active_mask):
        raise ValueError("Removal mask has no editable pixels.")

    input_active = input_pixels[active_mask]
    output_active = output_pixels[active_mask]
    if np.array_equal(input_active, output_active):
        raise ValueError("Removal area shows no visible change from the original photo.")

    core_mask = mask >= 128
    if np.count_nonzero(core_mask) > 16:
        core_output = output_pixels[core_mask].astype(np.float32)
        if float(np.std(core_output)) < _BLANK_STD_THRESHOLD:
            raise ValueError("Removal output region lacks visible variation or texture.")

    alpha = mask.astype(np.float32) / np.float32(255.0)
    blended = (
        input_pixels.astype(np.float32) * (np.float32(1.0) - alpha[..., None])
        + output_pixels.astype(np.float32) * alpha[..., None]
    )
    result = np.clip(np.rint(blended), 0.0, 255.0).astype(np.uint8)

    protected = mask == 0
    result[protected] = input_pixels[protected]

    warnings = ["protected_region_restored"]
    return np.ascontiguousarray(result), warnings


def simulate_object_removal(
    input_pixels: PixelArray,
    mask: MaskArray,
) -> PixelArray:
    """High-fidelity mock inpainting using Telea method with subtle synthetic grain."""
    binary_mask = (mask > 0).astype(np.uint8) * 255
    inpainted = cv2.inpaint(
        input_pixels,
        binary_mask,
        inpaintRadius=3,
        flags=cv2.INPAINT_TELEA,
    )
    h, w = input_pixels.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    noise = (((xx % 4) + (yy % 4)) - 3.0).astype(np.float32)
    grain_mask = (mask.astype(np.float32) / 255.0)[..., None]
    adjusted = inpainted.astype(np.float32) + noise[..., None] * grain_mask * 1.5
    res = np.clip(np.rint(adjusted), 0.0, 255.0).astype(np.uint8)
    return np.ascontiguousarray(res)
