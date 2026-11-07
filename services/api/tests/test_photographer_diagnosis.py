from __future__ import annotations

from app.ai.contracts import (
    ColorTemperature,
    ContrastLevel,
    IssueType,
    SaturationLevel,
    SceneLabel,
    Severity,
)
from app.ai.providers.mock import MockPlannerProvider
from app.models.photographer import (
    CreativeChoiceType,
    DirectionConstraint,
    PhotographerPreferences,
)
from app.photographer.diagnosis import diagnose
from app.photographer.direction import determine_direction
from app.photographer.service import PhotographerService
from app.photographer.styles import get_style
from tests.photographer_support import issue, report


def _direction_type_names(analysis, preferences=None, style=None, style_strength=None):
    preferences = preferences or PhotographerPreferences()
    diagnosis = diagnose(analysis)
    direction = determine_direction(
        analysis,
        diagnosis,
        preferences,
        style,
        style_strength=style_strength,
    )
    return diagnosis, direction


def test_portrait_clipping_is_confirmed_with_grounded_evidence():
    analysis = report(
        scene=SceneLabel.PORTRAIT,
        issues=(
            issue(
                "issue_clip",
                issue_type=IssueType.HIGHLIGHT_CLIPPING,
                confidence=0.8,
                evidence="高光裁切占比 8.0%。",
            ),
        ),
        highlights_pct=8.0,
    )

    diagnosis = diagnose(analysis)

    assert [item.issue_id for item in diagnosis.confirmed] == ["issue_clip"]
    assert diagnosis.possible == ()
    item = diagnosis.confirmed[0]
    assert {"issue_clip", "region_001", "measurement.clipping.highlightsPct"} <= set(
        item.evidence_refs
    )
    assert diagnosis.confidence >= 0.55
    assert direction_has(analysis, DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL)


def test_backlit_portrait_confirms_subject_and_background_problems():
    analysis = report(
        scene=SceneLabel.PORTRAIT,
        contrast=ContrastLevel.HIGH,
        issues=(
            issue(
                "issue_bg",
                issue_type=IssueType.BACKGROUND_OVEREXPOSURE,
                confidence=0.82,
                evidence="背景高光占比 12.0%。",
            ),
            issue(
                "issue_subject",
                issue_type=IssueType.SUBJECT_UNDEREXPOSURE,
                confidence=0.78,
                evidence="人物区域比背景低约 2.3 EV。",
            ),
        ),
        highlights_pct=12.0,
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert {item.issue_id for item in diagnosis.confirmed} == {"issue_bg", "issue_subject"}
    constraints = set(direction.constraints)
    assert DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL in constraints
    assert DirectionConstraint.PRESERVE_SKIN_TONE in constraints


def test_indoor_strong_cast_is_confirmed_not_a_creative_choice():
    analysis = report(
        scene=SceneLabel.INDOOR,
        temperature=ColorTemperature.COOL,
        cast_temperature=0.12,
        issues=(
            issue(
                "issue_cast",
                issue_type=IssueType.TEMPERATURE_MISMATCH,
                confidence=0.8,
                evidence="冷暖混合光源导致主体偏冷。",
            ),
        ),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert [item.issue_id for item in diagnosis.confirmed] == ["issue_cast"]
    assert CreativeChoiceType.COOL_AMBIENT not in {
        choice.type for choice in diagnosis.creative_choices
    }
    assert DirectionConstraint.AVOID_COLOR_CAST in direction.constraints


def test_landscape_highlights_drive_direction_strength():
    analysis = report(
        scene=SceneLabel.LANDSCAPE,
        issues=(issue("issue_clip", issue_type=IssueType.HIGHLIGHT_CLIPPING, confidence=0.85),),
        highlights_pct=9.0,
        luminance_p99=0.998,
    )

    _, direction = _direction_type_names(analysis)

    assert direction.id == "natural_landscape"
    assert DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL in direction.constraints
    assert direction.strength > 0.35


def test_sunset_warmth_is_a_creative_choice_not_a_mismatch():
    analysis = report(
        scene=SceneLabel.LANDSCAPE,
        temperature=ColorTemperature.WARM,
        cast_temperature=0.04,
        issues=(
            issue(
                "issue_temp",
                issue_type=IssueType.TEMPERATURE_MISMATCH,
                confidence=0.8,
                evidence="整体色温偏暖。",
            ),
        ),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert diagnosis.confirmed == ()
    assert [item.issue_id for item in diagnosis.possible] == ["issue_temp"]
    assert CreativeChoiceType.WARM_AMBIENT in {choice.type for choice in diagnosis.creative_choices}
    constraints = set(direction.constraints)
    assert DirectionConstraint.KEEP_WARM_TONES in constraints
    assert DirectionConstraint.KEEP_AMBIENT_COLOR in constraints


def test_night_low_key_is_not_confirmed_as_underexposure():
    analysis = report(
        scene=SceneLabel.NIGHT,
        luminance_p50=0.12,
        issues=(
            issue(
                "issue_dark",
                issue_type=IssueType.UNDEREXPOSURE,
                severity=Severity.HIGH,
                confidence=0.9,
                evidence="画面整体较暗。",
            ),
        ),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert diagnosis.confirmed == ()
    assert [item.issue_id for item in diagnosis.possible] == ["issue_dark"]
    assert CreativeChoiceType.LOW_KEY_INTENT in {c.type for c in diagnosis.creative_choices}
    assert DirectionConstraint.KEEP_LOW_KEY in direction.constraints
    assert direction.strength <= 0.3


def test_architecture_cast_is_confirmed_and_neutrality_is_preserved():
    analysis = report(
        scene=SceneLabel.ARCHITECTURE,
        cast_temperature=0.12,
        issues=(issue("issue_cast", issue_type=IssueType.COLOR_CAST, confidence=0.9),),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert [item.issue_id for item in diagnosis.confirmed] == ["issue_cast"]
    assert DirectionConstraint.AVOID_COLOR_CAST in direction.constraints
    assert DirectionConstraint.MAINTAIN_NEUTRALITY in direction.constraints


def test_balanced_street_frame_reports_already_edited():
    analysis = report(scene=SceneLabel.STREET)

    diagnosis, direction = _direction_type_names(analysis)

    assert diagnosis.confirmed == ()
    assert diagnosis.possible == ()
    assert CreativeChoiceType.ALREADY_EDITED in {c.type for c in diagnosis.creative_choices}
    assert diagnosis.confidence == 0.55
    assert DirectionConstraint.NATURAL_LOOK in direction.constraints
    assert direction.strength <= 0.35


def test_intentional_high_contrast_stays_possible():
    analysis = report(
        scene=SceneLabel.OTHER,
        contrast=ContrastLevel.HIGH,
        luminance_std=0.32,
        issues=(
            issue(
                "issue_contrast",
                issue_type=IssueType.HARSH_CONTRAST,
                confidence=0.85,
                evidence="明暗反差较强。",
            ),
        ),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert diagnosis.confirmed == ()
    assert [item.issue_id for item in diagnosis.possible] == ["issue_contrast"]
    assert CreativeChoiceType.HIGH_CONTRAST_INTENT in {
        choice.type for choice in diagnosis.creative_choices
    }
    assert DirectionConstraint.AVOID_EXTREME_CONTRAST in direction.constraints


def test_intentional_low_saturation_stays_possible():
    analysis = report(
        scene=SceneLabel.OTHER,
        saturation=SaturationLevel.LOW,
        saturation_mean=0.12,
        issues=(
            issue(
                "issue_sat",
                issue_type=IssueType.SATURATION_ISSUE,
                confidence=0.8,
                evidence="整体饱和度偏低。",
            ),
        ),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert diagnosis.confirmed == ()
    assert [item.issue_id for item in diagnosis.possible] == ["issue_sat"]
    assert CreativeChoiceType.LOW_SATURATION_INTENT in {
        choice.type for choice in diagnosis.creative_choices
    }
    assert DirectionConstraint.NATURAL_LOOK in direction.constraints


def test_high_saturation_is_possible_and_avoids_more_saturation():
    analysis = report(
        scene=SceneLabel.OTHER,
        saturation=SaturationLevel.HIGH,
        saturation_mean=0.62,
        issues=(
            issue(
                "issue_sat",
                issue_type=IssueType.SATURATION_ISSUE,
                confidence=0.8,
                evidence="整体饱和度过高。",
            ),
        ),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert diagnosis.confirmed == ()
    assert CreativeChoiceType.HIGH_SATURATION_INTENT in {
        choice.type for choice in diagnosis.creative_choices
    }
    assert DirectionConstraint.AVOID_EXTREME_SATURATION in direction.constraints


def test_mixed_light_confirms_cast_and_does_not_keep_warm_tone():
    analysis = report(
        scene=SceneLabel.INDOOR,
        temperature=ColorTemperature.WARM,
        cast_temperature=0.12,
        issues=(
            issue(
                "issue_temp",
                issue_type=IssueType.TEMPERATURE_MISMATCH,
                confidence=0.82,
                evidence="主体与背景冷暖不一致。",
            ),
            issue("issue_cast", issue_type=IssueType.COLOR_CAST, confidence=0.72),
        ),
    )

    diagnosis, direction = _direction_type_names(analysis)

    assert {item.issue_id for item in diagnosis.confirmed} == {"issue_temp", "issue_cast"}
    assert DirectionConstraint.KEEP_WARM_TONES not in direction.constraints
    assert CreativeChoiceType.WARM_AMBIENT not in {
        choice.type for choice in diagnosis.creative_choices
    }


def test_conflicting_exposure_issues_are_deferred_to_possible():
    analysis = report(
        issues=(
            issue("issue_dark", issue_type=IssueType.UNDEREXPOSURE, confidence=0.9),
            issue("issue_bright", issue_type=IssueType.OVEREXPOSURE, confidence=0.9),
        ),
    )

    diagnosis, _ = _direction_type_names(analysis)

    assert diagnosis.confirmed == ()
    assert {item.issue_id for item in diagnosis.possible} == {"issue_dark", "issue_bright"}


def test_diagnosis_and_direction_are_deterministic():
    analysis = report(
        scene=SceneLabel.PORTRAIT,
        temperature=ColorTemperature.WARM,
        issues=(
            issue("issue_clip", issue_type=IssueType.HIGHLIGHT_CLIPPING, confidence=0.8),
            issue(
                "issue_cast",
                issue_type=IssueType.COLOR_CAST,
                confidence=0.3,
                evidence="轻微偏色。",
            ),
        ),
    )

    first = _direction_type_names(analysis)
    second = _direction_type_names(analysis)
    assert first == second


def test_service_analyze_uses_deterministic_rules_without_provider_call():
    service = PhotographerService(MockPlannerProvider())
    analysis = report(
        scene=SceneLabel.ARCHITECTURE,
        issues=(issue("issue_clip", issue_type=IssueType.HIGHLIGHT_CLIPPING),),
    )

    advice = service.analyze(analysis)

    assert advice.diagnosis == diagnose(analysis)
    assert advice.direction.id == "clean_architecture"
    assert advice.direction.constraints


def test_service_analyze_preserves_style_strength():
    style = get_style("film")
    assert style is not None
    service = PhotographerService(MockPlannerProvider())

    advice = service.analyze(
        report(scene=SceneLabel.PORTRAIT),
        style=style,
        style_strength=0.75,
    )

    assert advice.direction.id == "film_direction"
    assert advice.direction.strength == 0.75


def direction_has(analysis, constraint: DirectionConstraint) -> bool:
    _, direction = _direction_type_names(analysis)
    return constraint in direction.constraints
