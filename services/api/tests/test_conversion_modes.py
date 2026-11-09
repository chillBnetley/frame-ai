from __future__ import annotations

import pytest

from app.models.conversion import ConversionMode
from app.models.photographer import (
    PhotographerPreferences,
    PlannerMode,
    StyleDefinition,
)
from app.models.recipe import ColorGrading
from app.photographer.modes import (
    ALLOWED_ADJUSTMENTS,
    CREATIVE_PROFILE,
    NATURAL_PROFILE,
    STYLE_PROFILE,
    conversion_mode_infos,
    conversion_profile,
    interpolate_intent,
    mode_curve_points,
    mode_grading,
    mode_local_intent,
    mode_style_intent,
    resolve_conversion_mode,
)
from app.photographer.styles import (
    STYLE_CATALOG,
    get_style,
    style_identity_fields,
)

STRENGTHS = (0.2, 0.35, 0.5, 0.65, 0.8, 0.95)
MODES = (ConversionMode.NATURAL, ConversionMode.STYLE, ConversionMode.CREATIVE)
_PERMISSIVE = PhotographerPreferences(
    naturalness=0.0,
    adjustment_strength=1.0,
    allow_stylization=True,
    preserve_original_color=False,
)
_ENGINE_BOUNDS = {
    "exposureEv": (-5.0, 5.0),
    "sharpen": (0.0, 100.0),
    "denoise": (0.0, 100.0),
    "grain": (0.0, 100.0),
}


def _style(style_id: str) -> StyleDefinition:
    style = get_style(style_id)
    assert style is not None
    return style


def _grading_total(style_id: str, strength: float, mode: ConversionMode) -> float:
    grading: ColorGrading | None = mode_grading(style_id, strength, mode)
    if grading is None:
        return 0.0
    return grading.shadows.saturation + grading.midtones.saturation + grading.highlights.saturation


def _engine_limit(field: str, value: float) -> bool:
    low, high = _ENGINE_BOUNDS.get(field, (-100.0, 100.0))
    return low - 1e-9 <= value <= high + 1e-9


def test_profiles_publish_complete_and_consistent_constraints():
    infos = conversion_mode_infos()

    assert [info.mode for info in infos] == list(MODES)
    for info in infos:
        assert info.allowed_adjustments == ALLOWED_ADJUSTMENTS
        assert info.recommended_strength_min <= info.recommended_strength_default
        assert info.recommended_strength_default <= info.recommended_strength_max
        assert info.preservation_constraints
        assert info.forbidden_operations
        assert any("生成式" in item for item in info.forbidden_operations)
        assert conversion_profile(info.mode).info() == info


def test_mode_envelopes_and_strength_guidance_increase_with_intensity():
    assert (
        NATURAL_PROFILE.envelope_scale
        < STYLE_PROFILE.envelope_scale
        < CREATIVE_PROFILE.envelope_scale
    )
    assert NATURAL_PROFILE.recommended_strength_default < (
        STYLE_PROFILE.recommended_strength_default
    )
    assert STYLE_PROFILE.recommended_strength_default < (
        CREATIVE_PROFILE.recommended_strength_default
    )
    assert NATURAL_PROFILE.local_scale < STYLE_PROFILE.local_scale
    assert STYLE_PROFILE.local_scale < CREATIVE_PROFILE.local_scale


def test_mode_strength_is_ordered_and_bounded_for_every_style():
    for style in STYLE_CATALOG:
        envelope = style.envelope.model_dump(by_alias=True)
        for strength in STRENGTHS:
            values = {mode: mode_style_intent(style, strength, _PERMISSIVE, mode) for mode in MODES}
            fields = {field for item in values.values() for field in item}
            for field in fields:
                natural = abs(values[ConversionMode.NATURAL].get(field, 0.0))
                neutral = abs(values[ConversionMode.STYLE].get(field, 0.0))
                creative = abs(values[ConversionMode.CREATIVE].get(field, 0.0))
                assert natural <= neutral + 1e-9, (style.id, strength, field)
                assert neutral <= creative + 1e-9, (style.id, strength, field)
                assert natural <= float(envelope[field]) * NATURAL_PROFILE.envelope_scale + 1e-9
                assert creative <= float(envelope[field]) * CREATIVE_PROFILE.envelope_scale + 1e-9
                assert _engine_limit(field, values[ConversionMode.CREATIVE][field])


def test_style_mode_matches_the_legacy_style_intent_exactly():
    from app.photographer.styles import style_adjustment_intent

    for style in STYLE_CATALOG:
        for strength in STRENGTHS:
            assert mode_style_intent(style, strength, _PERMISSIVE, ConversionMode.STYLE) == (
                style_adjustment_intent(style, strength, _PERMISSIVE)
            )


def test_natural_mode_protects_colour_and_limits_the_monochrome_identity():
    style = _style("monochrome")

    natural = mode_style_intent(style, 0.8, _PERMISSIVE, ConversionMode.NATURAL)
    neutral = mode_style_intent(style, 0.8, _PERMISSIVE, ConversionMode.STYLE)
    creative = mode_style_intent(style, 0.8, _PERMISSIVE, ConversionMode.CREATIVE)

    assert -30.0 < natural["saturation"] < 0.0
    assert neutral["saturation"] == -100.0
    assert creative["saturation"] == -100.0


def test_film_render_layers_become_stronger_with_the_mode():
    style = _style("film")
    curves = {
        mode: sum(abs(point.y - point.x) for point in mode_curve_points(style.id, 0.8, mode))
        for mode in MODES
    }
    grading = {mode: _grading_total(style.id, 0.8, mode) for mode in MODES}
    local = {
        mode: sum(abs(value) for value in mode_local_intent(style.id, 0.8, mode).values())
        for mode in MODES
    }

    assert (
        curves[ConversionMode.NATURAL]
        < curves[ConversionMode.STYLE]
        < (curves[ConversionMode.CREATIVE])
    )
    assert (
        grading[ConversionMode.NATURAL]
        < grading[ConversionMode.STYLE]
        < (grading[ConversionMode.CREATIVE])
    )
    assert (
        local[ConversionMode.NATURAL]
        < local[ConversionMode.STYLE]
        < (local[ConversionMode.CREATIVE])
    )


def test_same_style_and_strength_produce_distinguishable_intents():
    style = _style("film")
    intents = {mode: mode_style_intent(style, 0.8, _PERMISSIVE, mode) for mode in MODES}

    assert intents[ConversionMode.NATURAL] != intents[ConversionMode.STYLE]
    assert intents[ConversionMode.STYLE] != intents[ConversionMode.CREATIVE]
    assert intents[ConversionMode.NATURAL]["grain"] < intents[ConversionMode.STYLE]["grain"]
    assert intents[ConversionMode.STYLE]["grain"] < intents[ConversionMode.CREATIVE]["grain"]


@pytest.mark.parametrize("mode", MODES)
def test_full_strength_intent_interpolates_to_the_same_values(mode: ConversionMode):
    style = _style("film")
    full = mode_style_intent(style, 1.0, _PERMISSIVE, mode)
    identity = style_identity_fields(style.id)

    for strength in (0.3, 0.5, 0.8):
        rescaled = interpolate_intent(full, strength, identity_fields=identity)
        direct = mode_style_intent(style, strength, _PERMISSIVE, mode)
        assert rescaled.keys() == direct.keys()
        for field, value in direct.items():
            # The stored full-strength intent is already rounded once, so
            # post-hoc rescaling may differ from a fresh pass by rounding only.
            assert rescaled[field] == pytest.approx(value, abs=0.02), (mode, strength, field)


@pytest.mark.parametrize("mode", MODES)
def test_strength_is_continuous_and_monotonic(mode: ConversionMode):
    style = _style("vivid")
    previous: dict[str, float] = {}
    for step in range(0, 101):
        values = mode_style_intent(style, step / 100.0, _PERMISSIVE, mode)
        for field, value in values.items():
            assert abs(value) + 1e-9 >= abs(previous.get(field, 0.0)), (field, step)
        previous = values

    assert interpolate_intent(full_intent={}, strength=0.5) == {}
    assert mode_style_intent(style, 0.0, _PERMISSIVE, mode) == {}


def test_conversion_mode_resolution_keeps_auto_plans_mode_free():
    assert resolve_conversion_mode(PlannerMode.AUTO, None) is None
    assert resolve_conversion_mode(PlannerMode.AUTO, ConversionMode.CREATIVE) is None
    assert resolve_conversion_mode(PlannerMode.STYLE, None) is ConversionMode.STYLE
    assert (
        resolve_conversion_mode(PlannerMode.STYLE, ConversionMode.NATURAL) is ConversionMode.NATURAL
    )
