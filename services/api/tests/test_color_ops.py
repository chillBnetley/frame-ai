from __future__ import annotations

import numpy as np

from app.imaging.color_ops import apply_color, apply_saturation, apply_vibrance
from app.imaging.tone import luma_srgb


def _rgb(*pixels: tuple[float, float, float]) -> np.ndarray:
    return np.array([pixels], dtype=np.float32)


def _chroma(pixel: np.ndarray) -> float:
    return float(pixel.max() - pixel.min())


def test_neutral_color_operations_are_identity():
    rgb = np.random.default_rng(0).random((6, 7, 3), dtype=np.float32)

    assert apply_saturation(rgb, 0) is rgb
    assert apply_vibrance(rgb, 0) is rgb
    assert apply_color(rgb, saturation=0, vibrance=0) is rgb


def test_minus_hundred_saturation_is_grayscale():
    rgb = np.random.default_rng(1).random((8, 9, 3), dtype=np.float32)

    gray = apply_saturation(rgb, -100)

    assert np.allclose(gray[..., 0], gray[..., 1], atol=1e-7)
    assert np.allclose(gray[..., 1], gray[..., 2], atol=1e-7)
    assert np.allclose(gray[..., 0], luma_srgb(rgb), atol=1e-6)


def test_positive_saturation_increases_chroma_without_clipping():
    rgb = _rgb((0.4, 0.5, 0.6))
    before = _chroma(rgb[0, 0])

    saturated = apply_saturation(rgb, 50)

    assert _chroma(saturated[0, 0]) > before
    assert float(saturated.min()) >= 0.0
    assert float(saturated.max()) <= 1.0


def test_vibrance_weights_low_chroma_more_strongly():
    low = _rgb((0.45, 0.5, 0.55))
    high = _rgb((0.8, 0.2, 0.2))

    low_before = _chroma(low[0, 0])
    high_before = _chroma(high[0, 0])
    low_after = _chroma(apply_vibrance(low, 100)[0, 0])
    high_after = _chroma(apply_vibrance(high, 100)[0, 0])

    assert low_after / low_before > high_after / high_before
    assert low_after > low_before
    assert high_after > high_before


def test_color_operations_keep_outputs_in_range():
    rgb = np.random.default_rng(2).uniform(-0.1, 1.1, (16, 16, 3)).astype(np.float32)

    result = apply_color(rgb, saturation=100, vibrance=100)

    assert float(result.min()) >= 0.0
    assert float(result.max()) <= 1.0
    assert np.array_equal(
        result,
        apply_vibrance(apply_saturation(rgb, 100), 100),
    )
