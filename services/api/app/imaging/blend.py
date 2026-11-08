from __future__ import annotations

from typing import cast

import numpy as np
from numpy.typing import NDArray

RgbArray = NDArray[np.float32]
BlendMode = str


def blend_channels(base: RgbArray, adjusted: RgbArray, mode: BlendMode) -> RgbArray:
    """Blend one already-clipped adjusted colour into the base colour."""
    if mode == "normal":
        return adjusted
    if mode == "multiply":
        return cast(RgbArray, np.multiply(base, adjusted, dtype=np.float32))
    if mode == "screen":
        return cast(
            RgbArray,
            np.subtract(
                np.float32(1.0),
                np.multiply(np.float32(1.0) - base, np.float32(1.0) - adjusted, dtype=np.float32),
                dtype=np.float32,
            ),
        )
    if mode == "overlay":
        return cast(
            RgbArray,
            np.where(
                base <= np.float32(0.5),
                np.multiply(np.float32(2.0) * base, adjusted, dtype=np.float32),
                np.subtract(
                    np.float32(1.0),
                    np.multiply(
                        np.float32(2.0) * (np.float32(1.0) - base),
                        np.float32(1.0) - adjusted,
                        dtype=np.float32,
                    ),
                    dtype=np.float32,
                ),
            ).astype(np.float32, copy=False),
        )
    raise ValueError(f"unknown blend mode: {mode}")


def composite_layer(
    base: RgbArray,
    adjusted: RgbArray,
    weight: NDArray[np.float32] | float,
    mode: BlendMode,
) -> RgbArray:
    """Composite ``adjusted`` over ``base`` with a per-pixel weight.

    Non-normal modes clip the adjusted result first so multiplied/screen values
    stay inside the displayable range of their inputs. ``weight`` may be a
    scalar or an array broadcastable to the image (e.g. ``HxWx1``).
    """
    if mode == "normal":
        blended = adjusted
    else:
        blended = blend_channels(base, np.clip(adjusted, 0.0, 1.0), mode)
    output = base + (blended - base) * weight
    clipped = np.clip(output, 0.0, 1.0)
    return np.ascontiguousarray(clipped, dtype=np.float32)


__all__ = ["composite_layer", "blend_channels"]
