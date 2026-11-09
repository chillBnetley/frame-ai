from __future__ import annotations

from app.ai.contracts import (
    ColorTemperature,
    ContrastLevel,
    IssueType,
    SaturationLevel,
    SceneLabel,
    Severity,
)
from app.ai.prompts import PLANNER_PROMPT_VERSION
from app.ai.providers.mock import MockPlannerProvider
from app.models.photographer import CreativeChoiceType, PhotographerPreferences
from app.models.recipe import UserMask
from app.photographer.rules import available_mask_ids
from tests.photographer_support import (
    issue,
    patch_request,
    planner_request,
    recipe,
    report,
)


def test_mock_planner_is_deterministic():
    provider = MockPlannerProvider()
    request = planner_request(analysis=report(issues=(issue(),)))

    first = provider.plan(request)
    second = provider.plan(request)

    assert first == second
    assert provider.name == "mock"
    assert provider.model == "mock-planner"
    assert provider.is_mock is True
    assert provider.prompt_version == PLANNER_PROMPT_VERSION


def test_mock_planner_uses_scene_direction_and_issue_evidence():
    draft = MockPlannerProvider().plan(
        planner_request(analysis=report(scene=SceneLabel.PORTRAIT, issues=(issue(),)))
    )

    assert draft.direction.id == "natural_portrait"
    assert draft.diagnosis.confirmed[0].issue_id == "issue_001"
    assert draft.diagnosis.confirmed[0].evidence_refs[0] == "issue_001"
    assert draft.adjustments.highlights is not None
    assert draft.adjustments.highlights < 0
    assert draft.local_adjustments == ()
    assert any("模拟数据" in limitation for limitation in draft.limitations)


def test_low_key_night_is_treated_as_a_creative_choice_not_underexposure():
    analysis = report(
        scene=SceneLabel.NIGHT,
        luminance_p50=0.12,
        contrast=ContrastLevel.HIGH,
    )

    draft = MockPlannerProvider().plan(planner_request(analysis=analysis))

    choice_types = {choice.type for choice in draft.diagnosis.creative_choices}
    assert CreativeChoiceType.LOW_KEY_INTENT in choice_types
    assert draft.adjustments.exposure_ev is None
    assert draft.direction.id == "night_ambience"


def test_high_saturation_is_not_pushed_higher():
    analysis = report(saturation=SaturationLevel.HIGH, saturation_mean=0.68)

    draft = MockPlannerProvider().plan(planner_request(analysis=analysis))

    assert draft.adjustments.saturation is None
    assert draft.adjustments.vibrance is None
    assert CreativeChoiceType.HIGH_SATURATION_INTENT in {
        choice.type for choice in draft.diagnosis.creative_choices
    }


def test_preserve_original_color_caps_white_balance_changes():
    analysis = report(temperature=ColorTemperature.WARM, cast_temperature=0.2)
    analysis = analysis.model_copy(update={"issues": (issue(issue_type=IssueType.COLOR_CAST),)})
    draft = MockPlannerProvider().plan(
        planner_request(
            analysis=analysis,
            preferences=PhotographerPreferences(
                naturalness=0.0,
                adjustment_strength=1.0,
                preserve_original_color=True,
            ),
        )
    )

    assert draft.adjustments.temperature is not None
    assert abs(draft.adjustments.temperature) <= 8.0


def test_zero_adjustment_strength_produces_no_parameter_changes():
    draft = MockPlannerProvider().plan(
        planner_request(
            analysis=report(issues=(issue(),)),
            preferences=PhotographerPreferences(adjustment_strength=0.0),
        )
    )

    assert draft.adjustments.model_dump(exclude_none=True) == {}


def test_mock_patch_adjusts_only_the_requested_parameter():
    draft = MockPlannerProvider().adjust(patch_request("把高光压低一点"))

    assert draft.supported is True
    assert draft.adjustments is not None
    assert draft.adjustments.highlights == -15.0
    assert draft.adjustments.model_dump(exclude_none=True) == {"highlights": -15.0}
    assert "高光" in draft.reason


def test_mock_patch_interprets_temperature_complaints_in_the_right_direction():
    warm_complaint = MockPlannerProvider().adjust(patch_request("画面偏暖，稍微冷一点"))
    cool_complaint = MockPlannerProvider().adjust(patch_request("画面偏冷，稍微暖一点"))

    assert warm_complaint.adjustments is not None
    assert warm_complaint.adjustments.temperature == -10.0
    assert cool_complaint.adjustments is not None
    assert cool_complaint.adjustments.temperature == 10.0


def test_mock_patch_rejects_unsupported_capabilities():
    draft = MockPlannerProvider().adjust(patch_request("删除画面里的路人"))

    assert draft.supported is False
    assert draft.adjustments is None
    assert draft.unsupported
    assert "删除" in draft.unsupported[0]


def test_mock_patch_falls_back_to_global_edits_and_says_so_without_masks():
    draft = MockPlannerProvider().adjust(patch_request("只提亮人物面部"))

    assert draft.supported is True
    assert draft.local_adjustments == ()
    assert draft.adjustments is not None
    assert draft.adjustments.exposure_ev == 0.3
    assert any("蒙版" in item for item in draft.limitations)
    assert any("没有蒙版" in item for item in draft.warnings)


def test_mock_patch_uses_an_existing_user_mask_for_region_instructions():
    current = recipe().model_copy(
        update={
            "masks": (
                UserMask(id="mask_person", shape="rectangle", x=0.2, y=0.1, width=0.5, height=0.8),
            )
        }
    )

    draft = MockPlannerProvider().adjust(patch_request("让人物更突出", current_recipe=current))

    assert draft.supported is True
    assert draft.adjustments is None
    assert [item.mask_id for item in draft.local_adjustments] == ["mask_person"]
    assert draft.local_adjustments[0].adjustments.exposure_ev == 0.3
    assert "已有的蒙版" in draft.reason


def test_mock_patch_returns_no_change_for_unrecognized_text():
    draft = MockPlannerProvider().adjust(patch_request("让画面更有故事感"))

    assert draft.supported is True
    assert draft.adjustments is None
    assert draft.warnings
    assert "保持不变" in draft.reason


def test_mock_patch_does_not_invent_mask_ids():
    current = recipe()
    draft = MockPlannerProvider().adjust(
        patch_request(
            "降低背景亮度",
            current_recipe=current,
        )
    )

    mask_ids = available_mask_ids(current)
    assert mask_ids == {"full"}
    assert all(item.mask_id in mask_ids for item in draft.local_adjustments)


def test_severity_ordering_is_stable_for_equal_confidence():
    high = issue("issue_high", severity=Severity.HIGH, confidence=0.6)
    medium = issue("issue_medium", severity=Severity.MEDIUM, confidence=0.6)

    draft = MockPlannerProvider().plan(planner_request(analysis=report(issues=(medium, high))))

    assert [item.issue_id for item in draft.diagnosis.confirmed] == [
        "issue_high",
        "issue_medium",
    ]
