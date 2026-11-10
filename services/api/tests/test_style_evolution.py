from __future__ import annotations

from app.models.personal_style import (
    PersonalAvoidEffect,
    PersonalStyleDefinition,
    PersonalStyleProfile,
    PersonalStyleSource,
    build_default_personal_profile,
)
from app.models.photographer import DirectionConstraint
from app.models.style_evolution import StyleFeedbackType
from app.styles.evolution import evolve_profile


def _base(
    *,
    targets: dict[str, float] | None = None,
    protected: tuple[DirectionConstraint, ...] = (),
    avoid: tuple[PersonalAvoidEffect, ...] = (),
    confidence: float = 0.5,
    strength: float = 0.5,
) -> PersonalStyleProfile:
    profile = build_default_personal_profile(
        style_id="personal_evolve1",
        name="演变测试",
        description="用于演变引擎测试的个人风格。",
        source=PersonalStyleSource.PHOTOS,
        targets=targets or {},
        avoid=avoid,
    )
    personal = profile.personal.model_copy(
        update={"protected": protected, "confidence": confidence}
    )
    return profile.model_copy(update={"personal": personal, "default_strength": strength})


def _evolve(
    base: PersonalStyleProfile,
    feedbacks: list[StyleFeedbackType],
    *,
    note: str | None = None,
):
    return evolve_profile(
        base,
        PersonalStyleDefinition(),
        feedbacks,
        note=note,
        version="1.1",
    )


def test_color_too_strong_lowers_saturation_and_protects() -> None:
    base = _base(targets={"saturation": 20.0, "vibrance": 6.0})
    outcome = _evolve(base, [StyleFeedbackType.COLOR_TOO_STRONG])
    assert outcome.profile.personal.targets["saturation"] == 16.0
    assert outcome.profile.personal.targets["vibrance"] == 4.0
    assert PersonalAvoidEffect.OVERSATURATED in outcome.profile.personal.avoid
    assert DirectionConstraint.AVOID_EXTREME_SATURATION in outcome.profile.personal.protected
    assert outcome.feedback_count == 1


def test_color_too_strong_delta_is_capped() -> None:
    base = _base(targets={"saturation": 40.0})
    outcome = _evolve(base, [StyleFeedbackType.COLOR_TOO_STRONG] * 10)
    # Cap is -16 regardless of how many feedbacks accumulate.
    assert outcome.profile.personal.targets["saturation"] == 24.0


def test_repeated_feedback_aggregates_by_count() -> None:
    base = _base(targets={"saturation": 20.0})
    outcome = _evolve(base, [StyleFeedbackType.COLOR_TOO_STRONG] * 2)
    assert outcome.profile.personal.targets["saturation"] == 12.0
    assert outcome.feedback_count == 2


def test_shadows_too_dark_lifts_shadows_and_protects_detail() -> None:
    base = _base(targets={"shadows": -12.0})
    outcome = _evolve(base, [StyleFeedbackType.SHADOWS_TOO_DARK])
    assert outcome.profile.personal.targets["shadows"] == -8.0
    assert PersonalAvoidEffect.CRUSHED_BLACKS in outcome.profile.personal.avoid
    assert DirectionConstraint.PRESERVE_SHADOW_DETAIL in outcome.profile.personal.protected


def test_contrast_too_strong_lowers_contrast() -> None:
    base = _base(targets={"contrast": 18.0})
    outcome = _evolve(base, [StyleFeedbackType.CONTRAST_TOO_STRONG])
    assert outcome.profile.personal.targets["contrast"] == 14.0
    assert DirectionConstraint.AVOID_EXTREME_CONTRAST in outcome.profile.personal.protected


def test_skin_unnatural_protects_skin_and_neutralizes_color() -> None:
    base = _base(targets={"temperature": 10.0, "tint": -8.0})
    outcome = _evolve(base, [StyleFeedbackType.SKIN_UNNATURAL])
    assert outcome.profile.personal.targets["temperature"] == 8.0
    assert outcome.profile.personal.targets["tint"] == -6.0
    assert DirectionConstraint.PRESERVE_SKIN_TONE in outcome.profile.personal.protected
    assert PersonalAvoidEffect.UNNATURAL_SKIN in outcome.profile.personal.avoid


def test_style_subtle_strengthens_existing_direction() -> None:
    base = _base(targets={"saturation": 10.0, "contrast": -8.0}, strength=0.5)
    outcome = _evolve(base, [StyleFeedbackType.STYLE_SUBTLE])
    assert outcome.profile.personal.targets["saturation"] == 12.0
    assert outcome.profile.personal.targets["contrast"] == -10.0
    assert outcome.profile.default_strength > 0.5


def test_style_subtle_without_targets_only_raises_strength() -> None:
    base = _base(targets={}, strength=0.5)
    outcome = _evolve(base, [StyleFeedbackType.STYLE_SUBTLE])
    assert outcome.profile.personal.targets == {}
    assert outcome.profile.default_strength > 0.5
    assert any("没有明确数值方向" in item for item in outcome.limitations)


def test_style_overdone_converges_targets_to_neutral() -> None:
    base = _base(targets={"saturation": 20.0, "contrast": 10.0}, strength=0.6)
    outcome = _evolve(base, [StyleFeedbackType.STYLE_OVERDONE])
    assert outcome.profile.personal.targets["saturation"] == 17.0
    assert outcome.profile.personal.targets["contrast"] == 8.5
    assert outcome.profile.default_strength < 0.6
    assert DirectionConstraint.NATURAL_LOOK in outcome.profile.personal.protected
    assert PersonalAvoidEffect.HEAVY_FILTER in outcome.profile.personal.avoid


def test_keep_original_reduces_texture_targets() -> None:
    base = _base(targets={"clarity": 12.0, "sharpen": 9.0, "grain": 6.0})
    outcome = _evolve(base, [StyleFeedbackType.KEEP_ORIGINAL])
    assert outcome.profile.personal.targets["clarity"] == 9.0
    assert outcome.profile.personal.targets["sharpen"] == 6.0
    assert outcome.profile.personal.targets["grain"] == 3.0
    assert DirectionConstraint.NATURAL_LOOK in outcome.profile.personal.protected


def test_like_result_raises_confidence_without_changing_targets() -> None:
    base = _base(targets={"saturation": 10.0}, confidence=0.5)
    outcome = _evolve(base, [StyleFeedbackType.LIKE_RESULT])
    assert outcome.profile.personal.targets == {"saturation": 10.0}
    assert outcome.profile.personal.confidence > 0.5


def test_like_result_confidence_is_capped() -> None:
    base = _base(confidence=0.9)
    outcome = _evolve(base, [StyleFeedbackType.LIKE_RESULT] * 5)
    assert outcome.profile.personal.confidence <= 0.95


def test_dislike_result_lowers_strength_and_confidence() -> None:
    base = _base(strength=0.6, confidence=0.6)
    outcome = _evolve(base, [StyleFeedbackType.DISLIKE_RESULT])
    assert outcome.profile.default_strength < 0.6
    assert outcome.profile.personal.confidence < 0.6


def test_existing_protections_are_never_removed() -> None:
    base = _base(
        targets={"saturation": 20.0},
        protected=(DirectionConstraint.PRESERVE_SKIN_TONE,),
        avoid=(PersonalAvoidEffect.UNNATURAL_SKIN,),
    )
    outcome = _evolve(base, [StyleFeedbackType.COLOR_TOO_STRONG])
    assert DirectionConstraint.PRESERVE_SKIN_TONE in outcome.profile.personal.protected
    assert PersonalAvoidEffect.UNNATURAL_SKIN in outcome.profile.personal.avoid
    assert DirectionConstraint.AVOID_EXTREME_SATURATION in outcome.profile.personal.protected


def test_targets_and_strength_stay_bounded() -> None:
    base = _base(targets={"saturation": 100.0, "contrast": -100.0}, strength=0.9)
    outcome = _evolve(
        base,
        [StyleFeedbackType.STYLE_SUBTLE] * 10 + [StyleFeedbackType.DISLIKE_RESULT] * 10,
    )
    for value in outcome.profile.personal.targets.values():
        assert -100.0 <= value <= 100.0
    assert 0.0 <= outcome.profile.personal.confidence <= 1.0
    assert 0.0 <= outcome.profile.default_strength <= 1.0


def test_source_and_version_are_preserved() -> None:
    base = _base(targets={"saturation": 10.0})
    outcome = _evolve(base, [StyleFeedbackType.COLOR_TOO_STRONG], note="希望更克制")
    assert outcome.profile.personal.source is PersonalStyleSource.PHOTOS
    assert outcome.profile.version == "1.1"
    assert outcome.profile.id == base.id
    assert "用户意见" in outcome.reason
    assert outcome.summary


def test_adjustments_capture_before_and_after() -> None:
    base = _base(targets={"saturation": 20.0}, confidence=0.5)
    outcome = _evolve(base, [StyleFeedbackType.COLOR_TOO_STRONG])
    saturation = next(
        item for item in outcome.adjustments if item.field == "personal.targets.saturation"
    )
    assert saturation.before == 20.0
    assert saturation.after == 16.0


def test_empty_feedback_produces_neutral_candidate() -> None:
    base = _base(targets={"saturation": 10.0})
    outcome = _evolve(base, [])
    assert outcome.feedback_count == 0
    assert outcome.profile.personal.targets == {"saturation": 10.0}
    assert outcome.reason
