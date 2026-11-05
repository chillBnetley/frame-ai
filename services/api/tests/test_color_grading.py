from __future__ import annotations

import numpy as np
import pytest

from app.imaging import color_grading as grading_imaging
from app.imaging.color_grading import apply_color_grading
from app.models.recipe import ColorGradeZone, ColorGrading

_REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
_SHAPES = {
    "gray": (1.0, 1.0, 1.0),
    "cool": (0.6, 0.9, 1.0),
    "warm": (1.0, 0.7, 0.35),
}


def _grays(values: list[float]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    return np.repeat(array[:, None, None], 3, axis=2)


def _tinted(values: list[float], shape: tuple[float, float, float]) -> np.ndarray:
    """Pixels of constant hue whose brightest channel equals each value.

    Rec.709 luma is then ``value * dot(shape, REC709)``, so a tinted row sits at a
    lower luma than the gray row of the same value while staying inside [0, 1].
    """
    weights = np.asarray(shape, dtype=np.float32)
    weights = weights / weights.max()
    array = np.asarray(values, dtype=np.float32)
    return array[:, None, None] * weights[None, None, :]


def _row(values: list[float], shape: str) -> np.ndarray:
    if shape == "gray":
        return _grays(values)
    return _tinted(values, _SHAPES[shape])


def _luma(rgb: np.ndarray) -> np.ndarray:
    return np.asarray(np.tensordot(rgb, _REC709, axes=([-1], [0])), dtype=np.float64)


def _zone_delta(rgb: np.ndarray, graded: np.ndarray) -> np.ndarray:
    return np.abs(graded - rgb).max(axis=-1).reshape(-1)


def test_neutral_grading_returns_the_input_array():
    rgb = _grays([0.05, 0.2, 0.5, 0.8, 0.95])

    assert np.array_equal(apply_color_grading(rgb, ColorGrading()), rgb)
    assert (
        apply_color_grading(
            rgb,
            ColorGrading(
                balance=40,
                blending=10,
                shadows=ColorGradeZone(hue=220, saturation=0),
            ),
        )
        is rgb
    )


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_shadows_zone_affects_dark_pixels_most(shape: str):
    rgb = _row([0.1, 0.5, 0.9], shape)
    graded = apply_color_grading(
        rgb,
        ColorGrading(shadows=ColorGradeZone(hue=220, saturation=100)),
    )

    delta = _zone_delta(rgb, graded)
    assert delta[0] > 0.05
    assert delta[0] > delta[1] > delta[2]
    assert delta[2] == 0.0


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_midtones_zone_affects_middle_pixels_most(shape: str):
    rgb = _row([0.1, 0.5, 0.9], shape)
    graded = apply_color_grading(
        rgb,
        ColorGrading(midtones=ColorGradeZone(hue=160, saturation=100)),
    )

    delta = _zone_delta(rgb, graded)
    assert delta[1] > 0.05
    assert delta[1] > delta[0]
    assert delta[1] > delta[2]
    assert delta[0] == 0.0


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_highlights_zone_affects_bright_pixels_most(shape: str):
    rgb = _row([0.1, 0.5, 0.9], shape)
    graded = apply_color_grading(
        rgb,
        ColorGrading(highlights=ColorGradeZone(hue=45, saturation=100)),
    )

    delta = _zone_delta(rgb, graded)
    assert delta[2] > 0.05
    assert delta[2] > delta[1] >= delta[0]
    assert delta[0] == 0.0


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_blue_shadows_cool_and_warm_highlights_warm(shape: str):
    dark = _row([0.3], shape)
    bright = _row([0.7], shape)

    cooled = apply_color_grading(
        dark,
        ColorGrading(shadows=ColorGradeZone(hue=220, saturation=100)),
    )
    warmed = apply_color_grading(
        bright,
        ColorGrading(highlights=ColorGradeZone(hue=45, saturation=100)),
    )

    assert cooled[0, 0, 2] > dark[0, 0, 2]
    assert cooled[0, 0, 0] < dark[0, 0, 0]
    assert warmed[0, 0, 0] > bright[0, 0, 0]
    assert warmed[0, 0, 2] < bright[0, 0, 2]
    assert float(np.max(np.abs(_luma(cooled) - _luma(dark)))) <= 1e-6
    assert float(np.max(np.abs(_luma(warmed) - _luma(bright)))) <= 1e-6


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_grade_preserves_luminance_at_the_former_clip_boundaries(shape: str):
    values = [0.0, 0.02, 0.05, 0.5, 0.95, 1.0]
    rgb = _row(values, shape)

    graded = apply_color_grading(
        rgb,
        ColorGrading(
            shadows=ColorGradeZone(hue=240, saturation=100),
            highlights=ColorGradeZone(hue=30, saturation=100),
        ),
    )

    assert float(np.max(np.abs(_luma(graded) - _luma(rgb)))) <= 1e-6
    assert float(graded.min()) >= 0.0
    assert float(graded.max()) <= 1.0
    assert not np.array_equal(graded, rgb)


@pytest.mark.parametrize("shape", ["cool", "warm"])
def test_strength_scales_near_boundaries_instead_of_flipping_direction(shape: str):
    """A near-black pixel has no room to darken, so the blue shift shrinks to fit."""
    dark = _row([0.02], shape)
    reds: list[float] = []
    blues: list[float] = []
    for strength in (0, 25, 50, 75, 100):
        graded = apply_color_grading(
            dark,
            ColorGrading(shadows=ColorGradeZone(hue=240, saturation=strength)),
        )
        reds.append(float(graded[0, 0, 0]))
        blues.append(float(graded[0, 0, 2]))

    assert np.all(np.diff(reds) <= 0.0)
    assert np.all(np.diff(blues) >= 0.0)
    assert blues[-1] > blues[1]
    assert min(reds) >= 0.0
    assert max(blues) <= 1.0


def test_luminance_sweep_keeps_luma_exact_and_free_of_faults():
    values = np.linspace(0.0, 1.0, 1001, dtype=np.float32)
    step = float(values[1] - values[0])

    for shape in _SHAPES:
        rgb = _row([float(value) for value in values], shape)
        graded = apply_color_grading(
            rgb,
            ColorGrading(
                shadows=ColorGradeZone(hue=220, saturation=50),
                midtones=ColorGradeZone(hue=160, saturation=50),
                highlights=ColorGradeZone(hue=45, saturation=50),
            ),
        )

        # Steepest measured slope is 11x the sample step, where a tinted pixel
        # close to white releases the fitted scale. Refining the sweep fourfold
        # divides the worst step by four, so this guards against a real jump
        # rather than clipping the curve to pass.
        assert float(np.max(np.abs(np.diff(graded.astype(np.float64), axis=0)))) <= 15.0 * step
        assert float(np.max(np.abs(_luma(graded) - _luma(rgb)))) <= 1e-6
        assert float(graded.min()) >= 0.0
        assert float(graded.max()) <= 1.0


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_strength_changes_tint_monotonically(shape: str):
    rgb = _row([0.2], shape)
    blues: list[float] = []
    reds: list[float] = []
    graded_stack: list[np.ndarray] = []
    for strength in (0, 25, 50, 75, 100):
        graded = apply_color_grading(
            rgb,
            ColorGrading(shadows=ColorGradeZone(hue=220, saturation=strength)),
        )
        graded_stack.append(graded)
        blues.append(float(graded[0, 0, 2]))
        reds.append(float(graded[0, 0, 0]))

    assert np.all(np.diff(blues) > 0)
    assert np.all(np.diff(reds) < 0)
    assert all(float(np.max(np.abs(_luma(graded) - _luma(rgb)))) <= 1e-6 for graded in graded_stack)


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_balance_moves_influence_between_shadows_and_highlights(shape: str):
    rgb = _row([0.5], shape)
    grading = ColorGrading(
        shadows=ColorGradeZone(hue=220, saturation=60),
        highlights=ColorGradeZone(hue=45, saturation=60),
    )

    cold = apply_color_grading(rgb, grading.model_copy(update={"balance": -100}))
    warm = apply_color_grading(rgb, grading.model_copy(update={"balance": 100}))

    assert cold[0, 0, 2] > warm[0, 0, 2]
    assert cold[0, 0, 0] < warm[0, 0, 0]
    assert float(np.max(np.abs(_luma(cold) - _luma(rgb)))) <= 1e-6
    assert float(np.max(np.abs(_luma(warm) - _luma(rgb)))) <= 1e-6


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_blending_changes_output_continuously(shape: str):
    rgb = _row([float(value) for value in np.linspace(0.05, 0.95, 91, dtype=np.float32)], shape)
    base = ColorGrading(
        shadows=ColorGradeZone(hue=220, saturation=60),
        highlights=ColorGradeZone(hue=45, saturation=60),
    )

    outputs = [
        apply_color_grading(rgb, base.model_copy(update={"blending": blending}))
        for blending in range(0, 101, 5)
    ]
    stack = np.stack(outputs)

    assert np.all(np.isfinite(stack))
    assert float(np.max(np.abs(np.diff(stack, axis=0)))) < 0.05
    assert not np.array_equal(outputs[0], outputs[-1])


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_hue_360_matches_hue_zero(shape: str):
    rgb = _row([0.2, 0.5, 0.9], shape)
    zero = apply_color_grading(
        rgb,
        ColorGrading(highlights=ColorGradeZone(hue=0, saturation=80)),
    )
    wrapped = apply_color_grading(
        rgb,
        ColorGrading(highlights=ColorGradeZone(hue=360, saturation=80)),
    )
    other = apply_color_grading(
        rgb,
        ColorGrading(highlights=ColorGradeZone(hue=120, saturation=80)),
    )

    assert np.array_equal(zero, wrapped)
    assert not np.array_equal(zero, other)


def test_extreme_parameters_stay_finite_and_bounded():
    rgb = np.array(
        [
            [
                [0.0, 0.0, 0.0],
                [1.0, 1.0, 1.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [0.5, 0.5, 0.5],
            ]
        ],
        dtype=np.float32,
    )
    for balance in (-100.0, 0.0, 100.0):
        for blending in (0.0, 50.0, 100.0):
            grading = ColorGrading(
                shadows=ColorGradeZone(hue=0, saturation=100),
                midtones=ColorGradeZone(hue=120, saturation=100),
                highlights=ColorGradeZone(hue=240, saturation=100),
                balance=balance,
                blending=blending,
            )
            graded = apply_color_grading(rgb, grading)
            assert graded.dtype == np.float32
            assert np.all(np.isfinite(graded))
            assert float(graded.min()) >= 0.0
            assert float(graded.max()) <= 1.0
            # Fitting the shift to the available head room keeps every saturated
            # primary and pure black/white exactly where it was instead of lifting it.
            assert float(np.max(np.abs(_luma(graded) - _luma(rgb)))) <= 1e-6


def test_chunk_boundaries_do_not_change_pixels(monkeypatch):
    rng = np.random.default_rng(20261103)
    rgb = rng.random((37, 11, 3), dtype=np.float32)
    grading = ColorGrading(
        shadows=ColorGradeZone(hue=220, saturation=60),
        midtones=ColorGradeZone(hue=160, saturation=30),
        highlights=ColorGradeZone(hue=45, saturation=70),
        balance=20,
        blending=30,
    )

    whole = apply_color_grading(rgb, grading)
    monkeypatch.setattr(grading_imaging, "COLOR_GRADING_CHUNK_PIXELS", 7)
    chunked = apply_color_grading(rgb, grading)

    assert np.array_equal(whole, chunked)


def test_input_is_not_mutated():
    rgb = _grays([0.2, 0.5, 0.8])
    original = rgb.copy()

    apply_color_grading(
        rgb,
        ColorGrading(
            shadows=ColorGradeZone(hue=220, saturation=100),
            highlights=ColorGradeZone(hue=45, saturation=100),
        ),
    )

    assert np.array_equal(rgb, original)


def test_non_finite_input_does_not_raise():
    rgb = np.array([[[np.nan, 0.5, np.inf], [-np.inf, 0.2, 0.8]]], dtype=np.float32)

    result = apply_color_grading(
        rgb,
        ColorGrading(
            shadows=ColorGradeZone(hue=220, saturation=100),
            highlights=ColorGradeZone(hue=45, saturation=100),
        ),
    )

    assert result.shape == rgb.shape
    assert result.dtype == np.float32
