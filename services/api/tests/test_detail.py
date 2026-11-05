from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.imaging.detail import (
    _grain_noise,
    apply_denoise,
    apply_detail,
    apply_grain,
    apply_sharpen,
    grain_seed,
)
from app.imaging.params_map import DENOISE_SEARCH_DRAFT, DENOISE_TEMPLATE_DRAFT
from app.imaging.tone import luma_srgb

SHA_A = "a" * 64
SHA_B = "b" * 64


def _high_frequency_energy(rgb: np.ndarray) -> float:
    luminance = luma_srgb(rgb)
    blurred = cv2.GaussianBlur(luminance, (0, 0), sigmaX=1.0, sigmaY=1.0)
    return float(np.mean((luminance - blurred) ** 2))


def _noisy_gradient() -> np.ndarray:
    height, width = 72, 96
    gradient = np.linspace(0.25, 0.75, width, dtype=np.float32)[None, :]
    base = np.repeat(gradient, height, axis=0)
    noise = np.random.default_rng(7).normal(0.0, 0.04, (height, width)).astype(np.float32)
    gray = np.clip(base + noise, 0.0, 1.0)
    return np.repeat(gray[..., None], 3, axis=2)


def _soft_edge() -> np.ndarray:
    height, width = 64, 96
    x = np.arange(width, dtype=np.float32)
    edge = 0.5 + 0.2 * np.tanh((x - width / 2) / 0.5)
    gray = np.repeat(edge[None, :], height, axis=0)
    return np.repeat(gray[..., None], 3, axis=2)


def test_neutral_detail_operations_are_identity():
    rgb = _noisy_gradient()

    assert apply_denoise(rgb, 0) is rgb
    assert apply_sharpen(rgb, 0) is rgb
    assert apply_grain(rgb, 0, image_sha256=SHA_A) is rgb
    assert np.array_equal(
        apply_detail(
            rgb,
            denoise=0,
            sharpen=0,
            grain=0,
            image_sha256=SHA_A,
        ),
        rgb,
    )


def test_denoise_reduces_high_frequency_energy():
    rgb = _noisy_gradient()
    before = _high_frequency_energy(rgb)

    denoised = apply_denoise(rgb, 80, quality="draft")

    assert denoised.dtype == np.float32
    assert _high_frequency_energy(denoised) < before * 0.6


def test_draft_and_final_denoise_use_different_search_windows():
    rgb = _noisy_gradient()

    draft = apply_denoise(rgb, 70, quality="draft")
    final = apply_denoise(rgb, 70, quality="final")

    assert not np.array_equal(draft, final)
    assert _high_frequency_energy(final) <= _high_frequency_energy(draft)


def test_simplified_denoise_uses_the_draft_search_window(monkeypatch):
    calls: list[tuple[int, int]] = []

    def fake_denoise(
        source: np.ndarray,
        destination: object,
        strength: float,
        colour_strength: float,
        template: int,
        search: int,
    ) -> np.ndarray:
        calls.append((template, search))
        return source

    monkeypatch.setattr(cv2, "fastNlMeansDenoisingColored", fake_denoise)

    apply_denoise(_noisy_gradient(), 50, quality="export", simplified=True)

    assert calls == [(DENOISE_TEMPLATE_DRAFT, DENOISE_SEARCH_DRAFT)]


def test_sharpen_increases_high_frequency_energy():
    rgb = _soft_edge()
    before = _high_frequency_energy(rgb)

    sharpened = apply_sharpen(rgb, 80)

    assert _high_frequency_energy(sharpened) > before
    assert 0.0 <= float(sharpened.min())
    assert float(sharpened.max()) <= 1.0


def test_sharpen_threshold_ignores_tiny_detail():
    rgb = np.full((32, 32, 3), 0.5, dtype=np.float32)
    rgb[:, ::2] += 1.0 / 1024.0

    sharpened = apply_sharpen(rgb, 100)

    assert np.array_equal(sharpened, rgb)


def test_grain_is_deterministic_per_image_and_independent_of_params():
    rgb = np.full((64, 64, 3), 0.5, dtype=np.float32)

    first = apply_grain(rgb, 40, image_sha256=SHA_A)
    second = apply_grain(rgb, 40, image_sha256=SHA_A)
    other = apply_grain(rgb, 40, image_sha256=SHA_B)
    uppercase = apply_grain(rgb, 40, image_sha256=SHA_A.upper())

    assert np.array_equal(first, second)
    assert np.array_equal(first, uppercase)
    assert not np.array_equal(first, other)
    assert grain_seed(SHA_A) == grain_seed(SHA_A.upper())
    assert grain_seed(SHA_A) != grain_seed(SHA_B)


def test_grain_amplitude_scales_linearly_and_stays_monochrome():
    rgb = np.full((64, 64, 3), 0.5, dtype=np.float32)

    low = apply_grain(rgb, 40, image_sha256=SHA_A)
    high = apply_grain(rgb, 80, image_sha256=SHA_A)

    assert np.allclose(high - rgb, 2.0 * (low - rgb), atol=1e-6)
    assert np.allclose(np.diff(low, axis=-1), np.diff(rgb, axis=-1), atol=1e-6)


def test_grain_is_weighted_toward_midtones():
    midtone = apply_grain(np.full((64, 64, 3), 0.5, np.float32), 100, image_sha256=SHA_A)
    dark = apply_grain(np.full((64, 64, 3), 0.02, np.float32), 100, image_sha256=SHA_A)

    assert float(np.std(midtone)) > float(np.std(dark))


def test_apply_detail_runs_denoise_then_sharpen_then_grain():
    rgb = _noisy_gradient()

    expected = apply_grain(
        apply_sharpen(apply_denoise(rgb, 30, quality="final"), 20),
        15,
        image_sha256=SHA_A,
    )

    assert np.array_equal(
        apply_detail(
            rgb,
            denoise=30,
            sharpen=20,
            grain=15,
            image_sha256=SHA_A,
            quality="final",
        ),
        expected,
    )


def test_grain_added_last_survives_the_smoothing_stages():
    """Order proof that does not re-run the pipeline.

    On a flat frame, denoise and sharpen only ever take texture away, so grain
    that genuinely lands last keeps the exact spread it was given (measured
    0.03000 for both). Grain fed in first is measured at 0.00484 because the
    denoiser erases it.
    """
    flat = np.full((48, 64, 3), np.float32(128.0 / 255.0), dtype=np.float32)

    detailed = apply_detail(
        flat,
        denoise=100,
        sharpen=100,
        grain=60,
        image_sha256=SHA_A,
        quality="draft",
    )
    grain_only = apply_grain(flat, 60, image_sha256=SHA_A)
    grain_first = apply_sharpen(
        apply_denoise(apply_grain(flat, 60, image_sha256=SHA_A), 100, quality="draft"),
        100,
    )

    assert abs(float(np.std(detailed)) - float(np.std(grain_only))) <= 1e-4
    assert float(np.std(detailed)) > 4.0 * float(np.std(grain_first))


def test_smoothing_a_flat_region_beats_the_sharpen_first_order():
    """Denoising before sharpening leaves a flat area measurably cleaner.

    On the noisy ramp the middle columns hold no edge, so the spread there is
    pure residual noise: 0.0409 for denoise-then-sharpen against 0.0519 when the
    two swap and 0.0512 in the untouched input.
    """
    rgb = _noisy_gradient()

    detailed = apply_detail(
        rgb,
        denoise=40,
        sharpen=60,
        grain=0,
        image_sha256=SHA_A,
        quality="draft",
    )
    sharpen_first = apply_denoise(apply_sharpen(rgb, 60), 40, quality="draft")

    assert float(np.std(detailed[:, 20:40])) < 0.85 * float(np.std(sharpen_first[:, 20:40]))
    assert float(np.std(detailed[:, 20:40])) < float(np.std(rgb[:, 20:40]))


@pytest.mark.parametrize("amount", [25.0, 100.0])
def test_detail_outputs_stay_in_range(amount: float):
    rgb = _noisy_gradient()

    adjusted = apply_detail(
        rgb,
        denoise=amount,
        sharpen=amount,
        grain=amount,
        image_sha256=SHA_A,
        quality="draft",
    )

    assert adjusted.dtype == np.float32
    assert 0.0 <= float(adjusted.min())
    assert float(adjusted.max()) <= 1.0


def test_grain_noise_is_drawn_in_blocks_without_changing_the_stream():
    expected = np.random.default_rng(20261105).standard_normal((300, 7)).astype(np.float32)

    actual = _grain_noise(np.random.default_rng(20261105), 300, 7)

    assert actual.dtype == np.float32
    assert np.array_equal(actual, expected)
