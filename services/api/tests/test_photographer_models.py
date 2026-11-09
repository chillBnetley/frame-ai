from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.contracts import IssueType, SceneLabel, Severity
from app.models.photographer import (
    AdjustmentIntent,
    CreativeDirection,
    DiagnosisItem,
    DiagnosisResult,
    DirectionConstraint,
    FeedbackRubric,
    LocalAdjustmentIntent,
    ParameterChange,
    PatchDraft,
    PhotographerFeedbackRequest,
    PhotographerPatchRequest,
    PhotographerPlanRequest,
    PhotographerPlanResponse,
    PhotographerPreferences,
    PlannerDraft,
    PlannerMode,
    ProviderInfo,
    StyleCategory,
    StyleDefinition,
)
from tests.photographer_support import issue, recipe


def _item(issue_id: str = "issue_001") -> DiagnosisItem:
    return DiagnosisItem(
        issue_id=issue_id,
        type=IssueType.HIGHLIGHT_CLIPPING,
        severity=Severity.MEDIUM,
        confidence=0.8,
        evidence="高光裁切占比 1.5%。",
        evidence_refs=("issue_001",),
    )


def _direction() -> CreativeDirection:
    return CreativeDirection(
        id="natural_portrait",
        name="自然人像",
        category=StyleCategory.SCENE,
        description="保留自然肤色。",
    )


def test_preferences_have_safe_defaults_and_camel_case_aliases():
    preferences = PhotographerPreferences()

    assert preferences.naturalness == 0.7
    assert preferences.adjustment_strength == 0.5
    assert preferences.allow_stylization is False
    assert preferences.preserve_original_color is True
    assert preferences.model_dump(mode="json", by_alias=True) == {
        "naturalness": 0.7,
        "adjustmentStrength": 0.5,
        "allowStylization": False,
        "preserveOriginalColor": True,
    }


@pytest.mark.parametrize(
    "values",
    [
        {"naturalness": -0.1},
        {"naturalness": 1.1},
        {"adjustmentStrength": 2.0},
        {"naturalness": 0.5, "extra": True},
    ],
)
def test_preferences_reject_out_of_range_or_unknown_values(values):
    with pytest.raises(ValidationError):
        PhotographerPreferences(**values)


def test_diagnosis_rejects_duplicate_issue_ids_across_groups():
    with pytest.raises(ValidationError, match="diagnosis issue ids must be unique"):
        DiagnosisResult(confirmed=(_item(),), possible=(_item(),))


def test_diagnosis_item_requires_evidence_references():
    with pytest.raises(ValidationError):
        DiagnosisItem(
            issue_id="issue_001",
            type=IssueType.HIGHLIGHT_CLIPPING,
            severity=Severity.MEDIUM,
            confidence=0.8,
            evidence="高光裁切。",
            evidence_refs=(),
        )


def test_style_definition_rejects_duplicate_scenes_and_bad_versions():
    with pytest.raises(ValidationError, match="supportedScenes must be unique"):
        StyleDefinition(
            id="natural",
            name="自然",
            category=StyleCategory.CREATIVE,
            description="自然风格。",
            supported_scenes=(SceneLabel.PORTRAIT, SceneLabel.PORTRAIT),
        )

    with pytest.raises(ValidationError):
        StyleDefinition(
            id="natural",
            version="1",
            name="自然",
            category=StyleCategory.CREATIVE,
            description="自然风格。",
            supported_scenes=(SceneLabel.PORTRAIT,),
        )


def test_local_adjustment_intent_rejects_v1_unsupported_fields():
    with pytest.raises(ValidationError, match="sharpen is not supported"):
        LocalAdjustmentIntent(
            mask_id="mask_001",
            adjustments=AdjustmentIntent(sharpen=10.0),
        )


def test_patch_draft_rejects_changes_when_unsupported():
    with pytest.raises(ValidationError, match="unsupported patch must not propose changes"):
        PatchDraft(
            supported=False,
            adjustments=AdjustmentIntent(exposure_ev=0.2),
            reason="不支持。",
        )


def test_planner_draft_rejects_duplicate_local_masks():
    with pytest.raises(ValidationError, match="maskIds must be unique"):
        PlannerDraft(
            diagnosis=DiagnosisResult(),
            direction=_direction(),
            local_adjustments=(
                LocalAdjustmentIntent(mask_id="mask_001", adjustments=AdjustmentIntent()),
                LocalAdjustmentIntent(mask_id="mask_001", adjustments=AdjustmentIntent()),
            ),
        )


def test_plan_response_serializes_with_camel_case_and_validates_recipe():
    plan = PhotographerPlanResponse(
        plan_id=uuid4(),
        analysis_id=uuid4(),
        session_id=uuid4(),
        image_id=uuid4(),
        mode=PlannerMode.AUTO,
        is_mock=True,
        provider=ProviderInfo(name="mock", model="mock-planner", prompt_version="stage5-planner/1"),
        diagnosis=DiagnosisResult(confirmed=(_item(),)),
        direction=_direction(),
        recipe=recipe(),
        changes=(
            ParameterChange(
                path="adjustments.highlights",
                previous=0.0,
                proposed=-20.0,
                reason="压低高光以保留层次。",
                evidence_refs=("issue_001",),
            ),
        ),
    )

    payload = plan.model_dump(mode="json", by_alias=True)

    assert payload["schemaVersion"] == "stage5/1"
    assert payload["planId"]
    assert payload["isMock"] is True
    assert payload["degraded"] is False
    assert payload["provider"]["promptVersion"] == "stage5-planner/1"
    assert payload["recipe"]["schemaVersion"] == "2.0"
    assert payload["changes"][0]["path"] == "adjustments.highlights"
    assert payload["direction"]["category"] == "scene"


def test_plan_response_rejects_duplicate_change_paths():
    change = ParameterChange(
        path="adjustments.highlights",
        previous=0.0,
        proposed=-20.0,
        reason="压低高光。",
        evidence_refs=("issue_001",),
    )
    with pytest.raises(ValidationError, match="change paths must be unique"):
        PhotographerPlanResponse(
            plan_id=uuid4(),
            analysis_id=uuid4(),
            session_id=uuid4(),
            image_id=uuid4(),
            mode=PlannerMode.AUTO,
            is_mock=False,
            provider=ProviderInfo(name="openai-compatible", model="m", prompt_version="v"),
            diagnosis=DiagnosisResult(),
            direction=_direction(),
            recipe=recipe(),
            changes=(change, change),
        )


def test_plan_request_requires_a_style_only_in_style_mode():
    base = {
        "analysis_id": uuid4(),
        "session_id": uuid4(),
    }

    with pytest.raises(ValidationError, match="styleId is required"):
        PhotographerPlanRequest(mode="style", **base)

    with pytest.raises(ValidationError, match="styleId is only accepted"):
        PhotographerPlanRequest(mode="auto", style_id="natural", **base)

    with pytest.raises(ValidationError, match="styleStrength is only accepted"):
        PhotographerPlanRequest(mode="auto", style_strength=0.5, **base)

    request = PhotographerPlanRequest(mode="style", style_id="film", **base)
    assert request.mode is PlannerMode.STYLE


def test_plan_request_limits_conversion_mode_to_style_plans():
    base = {
        "analysis_id": uuid4(),
        "session_id": uuid4(),
    }

    with pytest.raises(ValidationError, match="conversionMode is only accepted"):
        PhotographerPlanRequest(mode="auto", conversion_mode="creative", **base)

    with pytest.raises(ValidationError):
        PhotographerPlanRequest(
            mode="style",
            style_id="film",
            conversion_mode="bold",
            **base,
        )

    request = PhotographerPlanRequest(
        mode="style",
        style_id="film",
        conversion_mode="creative",
        **base,
    )
    assert request.conversion_mode.value == "creative"
    assert request.model_dump(by_alias=True)["conversionMode"] == "creative"


def test_patch_request_keeps_instruction_within_bounds():
    with pytest.raises(ValidationError):
        PhotographerPatchRequest(plan_id=uuid4(), instruction="")

    with pytest.raises(ValidationError):
        PhotographerPatchRequest(plan_id=uuid4(), instruction="x" * 501)


def test_feedback_rubric_scores_are_optional_but_bounded():
    assert FeedbackRubric().model_dump(exclude_none=True) == {}
    with pytest.raises(ValidationError):
        FeedbackRubric(exposure=0)
    with pytest.raises(ValidationError):
        FeedbackRubric(skin_tone=6)

    request = PhotographerFeedbackRequest(
        session_id=uuid4(),
        plan_id=uuid4(),
        action="accepted",
        rubric=FeedbackRubric(exposure=4, skin_tone=5),
    )
    assert request.action.value == "accepted"


def test_feedback_carries_no_free_text_and_no_derived_actions():
    with pytest.raises(ValidationError):
        PhotographerFeedbackRequest(
            session_id=uuid4(),
            plan_id=uuid4(),
            action="rejected",
            notes="x" * 501,
        )

    with pytest.raises(ValidationError):
        PhotographerFeedbackRequest(session_id=uuid4(), action="modified")

    with pytest.raises(ValidationError):
        PhotographerFeedbackRequest(session_id=uuid4(), action="rejected", revision_id=uuid4())

    assert PhotographerFeedbackRequest(session_id=uuid4(), action="reset").plan_id is None


def test_direction_constraints_use_the_closed_enum():
    direction = CreativeDirection(
        id="film_look",
        name="胶片",
        category=StyleCategory.CREATIVE,
        description="柔和高光。",
        constraints=(DirectionConstraint.PRESERVE_SKIN_TONE,),
    )
    assert direction.constraints == (DirectionConstraint.PRESERVE_SKIN_TONE,)


def test_issue_reports_can_feed_a_plan_with_existing_region_ids():
    from tests.photographer_support import report

    analysis = report(issues=(issue(),))
    assert analysis.issues[0].region_ids == ("region_001",)
