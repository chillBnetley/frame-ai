from __future__ import annotations

from app.ai.contracts import ContrastLevel, SaturationLevel, SceneLabel
from app.models.photographer import (
    AdjustmentIntent,
    CreativeChoiceType,
    PhotographerPreferences,
)
from app.models.recipe import UserMask
from app.photographer.diagnosis import diagnose
from app.photographer.rules import (
    apply_preferences_and_style,
    available_mask_ids,
    clamp,
    creative_choices,
    is_high_contrast,
    is_high_saturation,
    is_low_key,
    round2,
)
from app.photographer.styles import STYLE_CATALOG, direction_for_scene, get_style
from tests.photographer_support import issue, recipe, report


def test_clamp_and_rounding_helpers():
    assert clamp(12.0, -10.0, 10.0) == 10.0
    assert clamp(-12.0, -10.0, 10.0) == -10.0
    assert round2(0.1234) == 0.12
    assert round2(-0.126) == -0.13


def test_available_mask_ids_only_returns_real_user_masks():
    current = recipe()
    assert available_mask_ids(current) == {"full"}

    masked = current.model_copy(
        update={"masks": (UserMask(id="mask_001", x=0.1, y=0.1, width=0.3, height=0.3),)}
    )
    assert available_mask_ids(masked) == {"full", "mask_001"}


def test_creative_detection_uses_measurements_and_semantics():
    low_key = report(luminance_p50=0.15)
    assert is_low_key(low_key) is True

    bright = report(luminance_p50=0.55)
    assert is_low_key(bright) is False

    saturated = report(saturation=SaturationLevel.HIGH, saturation_mean=0.6)
    assert is_high_saturation(saturated) is True

    flat = report(contrast=ContrastLevel.HIGH, luminance_std=0.3)
    assert is_high_contrast(flat) is True


def test_creative_choices_include_low_key_and_warm_ambient():
    from app.ai.contracts import ColorTemperature

    analysis = report(
        luminance_p50=0.14,
        temperature=ColorTemperature.WARM,
    )
    types = {choice.type for choice in creative_choices(analysis)}
    assert CreativeChoiceType.LOW_KEY_INTENT in types
    assert CreativeChoiceType.WARM_AMBIENT in types


def test_diagnosis_splits_confirmed_and_possible_by_confidence():
    confirmed = issue("issue_high", confidence=0.9)
    possible = issue("issue_low", confidence=0.3)

    diagnosis = diagnose(report(issues=(confirmed, possible)))

    assert [item.issue_id for item in diagnosis.confirmed] == ["issue_high"]
    assert [item.issue_id for item in diagnosis.possible] == ["issue_low"]
    assert 0.0 <= diagnosis.confidence <= 1.0


def test_preferences_cap_color_and_stylization():
    intent = apply_preferences_and_style(
        {
            "saturation": 60.0,
            "temperature": 60.0,
            "grain": 40.0,
            "vignette": 40.0,
        },
        PhotographerPreferences(
            naturalness=0.0,
            adjustment_strength=1.0,
            allow_stylization=False,
            preserve_original_color=True,
        ),
    )

    assert intent.saturation == 8.0
    assert intent.temperature == 8.0
    assert intent.grain is None
    assert intent.vignette == 8.0


def test_style_envelope_caps_parameters():
    style = get_style("natural")
    assert style is not None

    intent = apply_preferences_and_style(
        {"contrast": 80.0, "highlights": 80.0},
        PhotographerPreferences(
            naturalness=0.0,
            adjustment_strength=1.0,
            allow_stylization=True,
            preserve_original_color=False,
        ),
        style,
    )

    assert intent.contrast == style.envelope.contrast
    assert intent.highlights == style.envelope.highlights


def test_zero_strength_returns_an_empty_intent():
    intent = apply_preferences_and_style(
        {"exposureEv": 1.0},
        PhotographerPreferences(adjustment_strength=0.0),
    )
    assert intent == AdjustmentIntent()


def test_scene_and_style_directions_are_deterministic():
    first = direction_for_scene(SceneLabel.LANDSCAPE, PhotographerPreferences())
    second = direction_for_scene(SceneLabel.LANDSCAPE, PhotographerPreferences())
    assert first == second
    assert first.id == "natural_landscape"

    style = get_style("film")
    assert style is not None
    styled = direction_for_scene(
        SceneLabel.PORTRAIT,
        PhotographerPreferences(),
        style,
        style_strength=0.75,
    )
    assert styled.id == "film_direction"
    assert styled.strength == 0.75
    assert styled.category.value == "creative"


def test_style_catalog_is_independent_of_engine_style_ids():
    from app.models.recipe import STYLE_IDS

    ids = [style.id for style in STYLE_CATALOG]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 10
    assert {style.engine_style for style in STYLE_CATALOG} <= set(STYLE_IDS)
    assert set(ids) - set(STYLE_IDS) == {
        "clear_portrait",
        "monochrome",
        "vivid",
        "warm_life",
        "cool_urban",
    }
    assert all(style.enabled for style in STYLE_CATALOG)
