from __future__ import annotations

from uuid import uuid4

from app.ai.base import PlannerRequest
from app.ai.contracts import ContrastLevel, SceneLabel
from app.ai.prompts import PLANNER_PROMPT_VERSION, build_planner_messages
from app.ai.providers.mock import MockPlannerProvider
from app.models.conversion import ConversionMode
from app.models.photographer import PhotographerPreferences, PlannerMode
from app.photographer.generator import generate_recipe
from app.photographer.style_generation import (
    build_style_context,
    dynamic_style_adjustments,
)
from app.styles.library import BW_DOCUMENTARY, ENVIRONMENTAL_PORTRAIT, FAN_HO
from tests.photographer_support import recipe, report

_PREFS = PhotographerPreferences(naturalness=0.3, adjustment_strength=1.0)
_MODES = (ConversionMode.NATURAL, ConversionMode.STYLE, ConversionMode.CREATIVE)


def _flat_street():
    return report(
        scene=SceneLabel.STREET,
        contrast=ContrastLevel.LOW,
        luminance_std=0.10,
    )


def _dramatic_street():
    return report(
        scene=SceneLabel.STREET,
        contrast=ContrastLevel.HIGH,
        luminance_std=0.32,
    )


def _context(profile=FAN_HO, *, mode: ConversionMode = ConversionMode.STYLE, strength: float = 0.7):
    return build_style_context(
        profile,
        _dramatic_street(),
        mode=mode,
        strength=strength,
        image_id="11111111-1111-1111-1111-111111111111",
        image_sha256="A" * 64,
    )


def _request(analysis, *, profile=FAN_HO, ctx=None) -> PlannerRequest:
    return PlannerRequest(
        analysis=analysis,
        recipe=recipe(),
        preferences=_PREFS,
        mode=PlannerMode.STYLE,
        style=profile.to_style_definition(),
        style_strength=0.7,
        style_context=ctx,
    )


def test_dynamic_style_changes_with_the_photo_under_the_same_archive():
    flat = dynamic_style_adjustments(
        FAN_HO,
        _flat_street(),
        mode=ConversionMode.STYLE,
        strength=0.7,
        preferences=_PREFS,
    )
    dramatic = dynamic_style_adjustments(
        FAN_HO,
        _dramatic_street(),
        mode=ConversionMode.STYLE,
        strength=0.7,
        preferences=_PREFS,
    )

    assert flat != dramatic
    assert abs(flat["contrast"]) > abs(dramatic["contrast"])
    assert flat["saturation"] == -100.0
    assert dramatic["saturation"] == -100.0


def test_dynamic_style_tracks_mode_and_strength_continuously():
    values = {
        mode: dynamic_style_adjustments(
            FAN_HO,
            _dramatic_street(),
            mode=mode,
            strength=0.8,
            preferences=_PREFS,
        )
        for mode in _MODES
    }
    totals = {mode: sum(abs(value) for value in intent.values()) for mode, intent in values.items()}

    assert totals[ConversionMode.NATURAL] < totals[ConversionMode.STYLE]
    assert totals[ConversionMode.STYLE] <= totals[ConversionMode.CREATIVE]
    assert (
        dynamic_style_adjustments(
            FAN_HO,
            _dramatic_street(),
            mode=ConversionMode.STYLE,
            strength=0.0,
            preferences=_PREFS,
        )
        == {}
    )

    previous: dict[str, float] = {}
    for step in range(0, 101):
        current = dynamic_style_adjustments(
            FAN_HO,
            _dramatic_street(),
            mode=ConversionMode.STYLE,
            strength=step / 100.0,
            preferences=_PREFS,
        )
        for field, value in current.items():
            assert abs(value) + 1e-9 >= abs(previous.get(field, 0.0)), (field, step)
        previous = current


def test_style_context_carries_the_archive_fit_mode_and_image_version():
    context = build_style_context(
        ENVIRONMENTAL_PORTRAIT,
        report(scene=SceneLabel.PORTRAIT),
        mode=ConversionMode.CREATIVE,
        strength=0.8,
        image_id="22222222-2222-2222-2222-222222222222",
        image_sha256="B" * 64,
    )
    payload = context.to_prompt_payload()

    assert payload["imageId"] == "22222222-2222-2222-2222-222222222222"
    assert payload["imageSha256"] == "b" * 64
    assert payload["conversionMode"] == "creative"
    assert payload["styleStrength"] == 0.8
    assert payload["styleProfile"]["id"] == "environmental_portrait"
    assert payload["styleProfile"]["sceneFit"]["suitable"]
    assert "sources" not in payload["styleProfile"]
    assert payload["conversionModeConstraints"]["forbiddenOperations"]
    assert payload["conversionModeConstraints"]["preservationConstraints"]
    assert payload["conversionModeConstraints"]["envelopeScale"] > 1.0
    fit = payload["fit"]
    assert 0.0 <= fit["overallScore"] <= 92.0
    assert len(fit["dimensions"]) == 5
    assert fit["recommendedMode"] in {"natural", "style", "creative"}
    assert fit["summary"]


def test_mock_planner_uses_the_style_context_for_different_photos():
    flat_context = build_style_context(
        FAN_HO,
        _flat_street(),
        mode=ConversionMode.STYLE,
        strength=0.7,
        image_id=str(uuid4()),
        image_sha256="c" * 64,
    )
    dramatic_context = build_style_context(
        FAN_HO,
        _dramatic_street(),
        mode=ConversionMode.STYLE,
        strength=0.7,
        image_id=str(uuid4()),
        image_sha256="d" * 64,
    )
    planner = MockPlannerProvider()

    flat = planner.plan(_request(_flat_street(), ctx=flat_context))
    dramatic = planner.plan(_request(_dramatic_street(), ctx=dramatic_context))

    assert flat.adjustments.model_dump(exclude_none=True)
    assert dramatic.adjustments.model_dump(exclude_none=True)
    assert flat.adjustments != dramatic.adjustments
    assert any("fan_ho" in item.lower() or "Fan Ho" in item for item in flat.rationale)
    assert any("模拟" in item for item in flat.limitations)


def test_dynamic_style_recipe_applies_without_reported_issues():
    analysis = _dramatic_street()
    context = _context()
    draft = MockPlannerProvider().plan(_request(analysis, ctx=context))
    style = FAN_HO.to_style_definition()

    generated = generate_recipe(
        recipe(),
        analysis,
        draft,
        _PREFS,
        style,
        0.7,
        conversion_mode=ConversionMode.STYLE,
        dynamic_style=True,
    )
    ignored = generate_recipe(
        recipe(),
        analysis,
        draft,
        _PREFS,
        style,
        0.7,
        conversion_mode=ConversionMode.STYLE,
        dynamic_style=False,
    )

    assert generated.changes
    assert generated.recipe.adjustments.saturation < 0.0
    assert ignored.changes == ()


def test_prompt_carries_the_full_style_context_and_mode_boundaries():
    messages = build_planner_messages(_request(_dramatic_street(), ctx=_context()))

    system = messages[0]["content"]
    user = messages[1]["content"]
    assert PLANNER_PROMPT_VERSION == "stage5-planner/3"
    assert "Style context" in system
    assert "descriptive research" in system
    assert "Only adjustments and localAdjustments" in system
    assert "Style context (verified archive" in user
    assert '"sources"' not in user
    assert user.count('"id":"fan_ho"') == 1
    assert '"styleProfile"' in user
    assert '"id":"fan_ho"' in user
    assert '"conversionMode":"style"' in user
    assert '"styleStrength":0.7' in user
    assert '"forbiddenOperations"' in user
    assert '"dimensions"' in user


def test_mock_plan_without_context_still_uses_the_default_style_rules():
    draft = MockPlannerProvider().plan(_request(_dramatic_street(), profile=BW_DOCUMENTARY))

    assert draft.adjustments.model_dump(exclude_none=True)
    assert "模拟" in draft.limitations[0]
