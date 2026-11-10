from __future__ import annotations

import pytest

from app.ai.contracts import SceneLabel
from app.models.personal_style import (
    PersonalAvoidEffect,
    PersonalStyleProfile,
    PersonalStyleSource,
    build_default_personal_profile,
)
from app.models.photographer import DirectionConstraint
from app.styles.library import FAN_HO, SAUL_LEITER
from app.styles.mixing import derive_direction, mix_styles


def _personal(
    style_id: str,
    name: str,
    *,
    targets: dict[str, float] | None = None,
    protected: tuple[DirectionConstraint, ...] = (),
    avoid: tuple[PersonalAvoidEffect, ...] = (),
    scenes: tuple[SceneLabel, ...] = (SceneLabel.STREET,),
    engine_style: str = "natural",
) -> PersonalStyleProfile:
    profile = build_default_personal_profile(
        style_id=style_id,
        name=name,
        description="测试个人风格。",
        source=PersonalStyleSource.PHOTOS,
        suitable_scenes=scenes,
        targets=targets or {},
    )
    personal = profile.personal.model_copy(update={"protected": protected, "avoid": avoid})
    return profile.model_copy(update={"personal": personal, "engine_style": engine_style})


def test_derive_direction_reads_master_traits() -> None:
    fan = derive_direction(FAN_HO)
    assert fan.monochrome is True
    assert fan.targets["saturation"] == -100.0
    assert fan.targets["contrast"] > 0.0
    assert not fan.is_personal

    leiter = derive_direction(SAUL_LEITER)
    assert leiter.monochrome is False
    assert leiter.targets["saturation"] < 0.0
    assert leiter.targets["temperature"] > 0.0
    assert leiter.targets["contrast"] < 0.0


def test_derive_direction_reads_personal_targets() -> None:
    profile = _personal("personal_alpha1", "冷调", targets={"temperature": -10.0})
    direction = derive_direction(profile)
    assert direction.is_personal
    assert direction.targets["temperature"] == -10.0
    assert direction.targets["saturation"] == 0.0


def test_monochrome_conflict_is_not_averaged() -> None:
    outcome = mix_styles(FAN_HO, SAUL_LEITER, weight=50)
    dimensions = {conflict.dimension for conflict in outcome.conflicts}
    assert "color.saturation" in dimensions
    # Neutral fallback, never the -50 arithmetic mean of -100 and a colour style.
    assert outcome.profile.personal.targets.get("saturation", 0.0) == 0.0
    assert "避免极端饱和度" in outcome.protections
    saturation_conflict = next(
        item for item in outcome.conflicts if item.dimension == "color.saturation"
    )
    assert saturation_conflict.resolved_by == "protection"


def test_weight_interpolates_non_conflicting_targets() -> None:
    a = _personal("personal_alpha1", "A", targets={"saturation": 10.0})
    b = _personal("personal_beta11", "B", targets={"saturation": 20.0})
    outcome = mix_styles(a, b, weight=25)
    assert not outcome.conflicts
    assert outcome.profile.personal.targets["saturation"] == pytest.approx(17.5)


def test_weight_extremes_pick_engine_style() -> None:
    a = _personal("personal_alpha1", "A", engine_style="street")
    b = _personal("personal_beta11", "B", engine_style="portrait")
    assert mix_styles(a, b, weight=100).profile.engine_style == "street"
    assert mix_styles(a, b, weight=0).profile.engine_style == "portrait"
    assert mix_styles(a, b, weight=50).profile.engine_style == "street"


def test_temperature_conflict_respects_source_and_user_resolution() -> None:
    a = _personal("personal_alpha1", "暖", targets={"temperature": 10.0})
    b = _personal("personal_beta11", "冷", targets={"temperature": -10.0})

    by_source = mix_styles(a, b, weight=50, sources={"color": "a"})
    assert by_source.profile.personal.targets["temperature"] == 10.0
    conflict = next(item for item in by_source.conflicts if item.dimension == "color.temperature")
    assert conflict.resolved_by == "source"

    by_user = mix_styles(a, b, weight=50, resolutions={"color.temperature": "b"})
    assert by_user.profile.personal.targets["temperature"] == -10.0
    conflict = next(item for item in by_user.conflicts if item.dimension == "color.temperature")
    assert conflict.resolved_by == "user"
    assert conflict.resolution == "b"

    neutral = mix_styles(a, b, weight=80)
    assert neutral.profile.personal.targets.get("temperature", 0.0) == 0.0
    assert "避免明显偏色" in neutral.protections


def test_protection_constraints_are_unioned_not_averaged() -> None:
    a = _personal(
        "personal_alpha1",
        "护肤",
        protected=(DirectionConstraint.PRESERVE_SKIN_TONE,),
        avoid=(PersonalAvoidEffect.UNNATURAL_SKIN,),
    )
    b = _personal(
        "personal_beta11",
        "护高光",
        protected=(DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,),
    )
    # Even at weight 0 (all B), A's protection survives as a hard floor.
    outcome = mix_styles(a, b, weight=0)
    assert DirectionConstraint.PRESERVE_SKIN_TONE in outcome.profile.personal.protected
    assert DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL in outcome.profile.personal.protected
    assert DirectionConstraint.PRESERVE_SKIN_TONE in outcome.profile.constraints
    assert PersonalAvoidEffect.UNNATURAL_SKIN in outcome.profile.personal.avoid


def test_dimension_source_isolates_features() -> None:
    a = _personal("personal_alpha1", "色彩方", targets={"saturation": 15.0, "contrast": -10.0})
    b = _personal("personal_beta11", "影调方", targets={"saturation": -5.0, "contrast": 18.0})
    outcome = mix_styles(a, b, weight=50, sources={"color": "a", "tone": "b"})
    assert outcome.profile.personal.targets["saturation"] == 15.0
    assert outcome.profile.personal.targets["contrast"] == 18.0
    color_plan = next(item for item in outcome.dimensions if item.dimension == "color")
    assert color_plan.source == "a"


def test_scene_conflict_unions_suitable_scenes() -> None:
    a = _personal("personal_alpha1", "人像", scenes=(SceneLabel.PORTRAIT,))
    b = _personal("personal_beta11", "风景", scenes=(SceneLabel.LANDSCAPE,))
    outcome = mix_styles(a, b, weight=50)
    assert "scene" in {item.dimension for item in outcome.conflicts}
    assert set(outcome.profile.scene_fit.suitable) == {SceneLabel.PORTRAIT, SceneLabel.LANDSCAPE}


def test_user_overrides_win_and_are_recorded() -> None:
    a = _personal("personal_alpha1", "A", targets={"saturation": 10.0})
    b = _personal("personal_beta11", "B", targets={"saturation": 20.0})
    outcome = mix_styles(
        a,
        b,
        weight=50,
        name="我的混合",
        target_overrides={"saturation": 33.0},
        avoid_overrides=(PersonalAvoidEffect.OVERSATURATED,),
        note="手动确认",
    )
    assert outcome.profile.name == "我的混合"
    assert outcome.profile.personal.targets["saturation"] == 33.0
    assert outcome.profile.personal.avoid == (PersonalAvoidEffect.OVERSATURATED,)
    assert "personal.targets" in outcome.profile.personal.user_overrides
    assert outcome.definition.note == "手动确认"
    assert outcome.definition.user_overrides["personal.targets"] == {"saturation": 33.0}


def test_provenance_records_sources_weights_and_rules() -> None:
    a = _personal("personal_alpha1", "A")
    b = _personal("personal_beta11", "B")
    outcome = mix_styles(a, b, weight=30, sources={"color": "a"})
    provenance = outcome.provenance
    assert provenance.style_a_id == "personal_alpha1"
    assert provenance.style_b_id == "personal_beta11"
    assert provenance.style_a_version == "1.0"
    assert provenance.weight == 30
    assert provenance.sources["color"] == "a"
    assert provenance.sources["tone"] == "blend"
    assert provenance.combination_rules
    assert outcome.profile.personal.source is PersonalStyleSource.MIXED
    assert outcome.profile.id.startswith("personal_")
    assert "mix" in outcome.definition.user_overrides


def test_mixed_envelope_covers_targets_and_monochrome() -> None:
    a = _personal("personal_alpha1", "A", targets={"saturation": -100.0, "contrast": 25.0})
    b = _personal("personal_beta11", "B", targets={"saturation": -100.0})
    outcome = mix_styles(a, b, weight=50, sources={"color": "a", "tone": "a"})
    assert outcome.profile.personal.targets["saturation"] == -100.0
    assert outcome.profile.envelope.saturation == 100.0
    assert outcome.profile.envelope.contrast >= 30.0


def test_same_style_rejected_at_model_layer() -> None:
    from app.models.style_mix import StyleMixRequest, StyleMixSourceRef

    with pytest.raises(ValueError):
        StyleMixRequest(
            style_a=StyleMixSourceRef(style_id="fan_ho"),
            style_b=StyleMixSourceRef(style_id="fan_ho"),
        )