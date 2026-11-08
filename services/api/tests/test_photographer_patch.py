from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.providers.mock import MOCK_PLANNER_MASK_LIMITATION, MockPlannerProvider
from app.models.photographer import AdjustmentIntent, LocalAdjustmentIntent, PatchDraft
from app.models.recipe import (
    Adjustments,
    ColorGradeZone,
    ColorGrading,
    Crop,
    CurvePoint,
    CurveSet,
    EditRecipe,
    HslAdjustments,
    HslBand,
    LocalAdjustment,
    LocalAdjustments,
    OutputSettings,
    UserMask,
)
from app.photographer.patch import (
    INSTRUCTION_EVIDENCE_REF,
    PATCH_ADJUSTMENT_FIELDS,
    PATCH_LOCAL_FIELDS,
    allowed_patch_paths,
    apply_patch,
)
from app.photographer.validator import RecipeValidationError
from tests.photographer_support import patch_draft_payload, patch_request, recipe, report

MASK = UserMask(id="mask_person", shape="rectangle", x=0.2, y=0.1, width=0.5, height=0.8)


def _draft(**overrides: Any) -> PatchDraft:
    return PatchDraft.model_validate(patch_draft_payload(**overrides))


def _local_draft(mask_id: str, **adjustments: float) -> PatchDraft:
    return _draft(
        adjustments=None,
        localAdjustments=[
            LocalAdjustmentIntent(
                mask_id=mask_id,
                adjustments=AdjustmentIntent(**adjustments),
            )
        ],
    )


def _user_recipe(**overrides: Any) -> EditRecipe:
    defaults: dict[str, Any] = {
        "adjustments": Adjustments(
            contrast=18.0, crop=Crop(x=0.1, y=0.1, w=0.8, h=0.8), rotation_deg=-4.0
        ),
        "curve": CurveSet(
            master=(CurvePoint(x=0.25, y=0.2), CurvePoint(x=0.75, y=0.85)),
            blue=(CurvePoint(x=0.0, y=0.05), CurvePoint(x=1.0, y=0.9)),
        ),
        "hsl": HslAdjustments(orange=HslBand(hue=4.0, saturation=-10.0, luminance=6.0)),
        "color_grading": ColorGrading(
            shadows=ColorGradeZone(hue=210.0, saturation=20.0), balance=-8.0
        ),
        "masks": (MASK,),
        "output": OutputSettings(quality=80),
        "rationale": ["暗部偏蓝是创作选择。"],
        "warnings": ["保留原图锐度。"],
    }
    return EditRecipe(**{**defaults, **overrides})


def test_patch_moves_only_the_field_the_instruction_mentions():
    base = _user_recipe()

    patched = apply_patch(base, report(), _draft())

    assert [change.path for change in patched.changes] == ["adjustments.saturation"]
    assert patched.changes[0].previous == 0.0
    assert patched.changes[0].proposed == -8.0
    assert patched.recipe.adjustments.saturation == -8.0
    assert patched.recipe.adjustments.contrast == base.adjustments.contrast


def test_patch_never_resets_user_curves_hsl_grading_masks_crop_or_output():
    base = _user_recipe()
    draft = _draft(
        adjustments={
            "exposureEv": 0.3,
            "contrast": 10.0,
            "highlights": -15.0,
            "shadows": 15.0,
            "clarity": 10.0,
            "denoise": 20.0,
        }
    )

    patched = apply_patch(base, report(), draft)

    assert patched.recipe.curve == base.curve
    assert patched.recipe.hsl == base.hsl
    assert patched.recipe.color_grading == base.color_grading
    assert patched.recipe.masks == base.masks
    assert patched.recipe.output == base.output
    assert patched.recipe.adjustments.crop == base.adjustments.crop
    assert patched.recipe.adjustments.rotation_deg == base.adjustments.rotation_deg
    assert patched.recipe.rationale == base.rationale
    assert patched.recipe.warnings == base.warnings
    assert all(path.startswith("adjustments.") for path in _paths(patched))
    assert _paths(patched) <= allowed_patch_paths(base)


def test_allowed_patch_paths_only_cover_bright_fields_and_existing_masks():
    paths = allowed_patch_paths(_user_recipe())

    assert {f"adjustments.{field}" for field in PATCH_ADJUSTMENT_FIELDS} <= paths
    assert {
        f"localAdjustments.{mask_id}.{field}"
        for mask_id in ("full", "mask_person")
        for field in PATCH_LOCAL_FIELDS
    } <= paths
    assert not any(
        path.startswith(("curve", "hsl", "colorGrading", "masks", "output")) for path in paths
    )


def test_patch_rejects_a_draft_that_carries_fields_outside_the_contract():
    with pytest.raises(ValidationError):
        _draft(curve={"master": [{"x": 0.5, "y": 0.4}]})
    with pytest.raises(ValidationError):
        _draft(adjustments={"crop": {"x": 0.2, "y": 0.2, "w": 0.6, "h": 0.6}})


def test_patch_rejects_a_local_intent_on_a_mask_the_recipe_does_not_have():
    with pytest.raises(RecipeValidationError, match="unknown maskId"):
        apply_patch(_user_recipe(), report(), _local_draft("mask_ghost", shadows=10.0))


def test_patch_rejects_a_local_field_the_engine_does_not_support():
    with pytest.raises(ValidationError):
        _local_draft("mask_person", sharpen=20.0)


def test_patch_clamps_a_value_that_would_leave_the_parameter_range():
    base = _user_recipe(adjustments=Adjustments(saturation=95.0))

    patched = apply_patch(base, report(), _draft(adjustments={"saturation": 8.0}))

    assert patched.recipe.adjustments.saturation == 100.0
    assert any("上下限" in warning for warning in patched.warnings)


def test_patch_caps_color_deltas_when_the_user_preserves_original_color():
    patched = apply_patch(
        recipe(),
        report(),
        _draft(adjustments={"temperature": 30.0}),
    )

    assert patched.recipe.adjustments.temperature == 8.0
    assert any("收紧" in warning for warning in patched.warnings)


def test_patch_drops_grain_when_stylization_is_not_allowed():
    patched = apply_patch(
        recipe(),
        report(),
        _draft(adjustments={"grain": 40.0}),
    )

    assert patched.recipe.adjustments.grain == 0.0
    assert patched.changes == ()
    assert any("收紧" in warning for warning in patched.warnings)


def test_unsupported_draft_returns_the_recipe_untouched():
    base = _user_recipe()
    draft = _draft(
        supported=False,
        adjustments=None,
        reason="当前版本不支持该项操作，配方保持不变。",
        unsupported=["删除或擦除画面中的物体"],
    )

    patched = apply_patch(base, report(), draft)

    assert patched.recipe == base
    assert patched.changes == ()
    assert patched.unsupported == ("删除或擦除画面中的物体",)


def test_conflicting_report_holds_the_value_and_reports_no_change():
    base = _user_recipe(adjustments=Adjustments(saturation=0.0))

    patched = apply_patch(
        base,
        report(saturation_mean=0.62),
        _draft(adjustments={"saturation": 8.0}),
    )

    assert patched.changes == ()
    assert patched.recipe.adjustments.saturation == 0.0
    assert "当前配方已满足该指令，未产生参数变化。" in patched.warnings


def test_every_change_cites_the_instruction_as_its_evidence():
    draft = _draft(adjustments={"saturation": -8.0, "contrast": 10.0, "clarity": 10.0})

    patched = apply_patch(recipe(), report(), draft)

    assert {change.evidence_refs for change in patched.changes} == {(INSTRUCTION_EVIDENCE_REF,)}
    assert {change.path for change in patched.changes} == {
        "adjustments.saturation",
        "adjustments.contrast",
        "adjustments.clarity",
    }
    assert all("按指令调整" in change.reason for change in patched.changes)


def test_local_patch_accumulates_on_an_existing_local_adjustment():
    existing = LocalAdjustment(
        id="local_user_1",
        mask_id="mask_person",
        adjustments=LocalAdjustments(shadows=5.0, exposure_ev=0.2),
    )
    base = _user_recipe(local_adjustments=(existing,))

    patched = apply_patch(base, report(), _local_draft("mask_person", shadows=10.0))

    assert len(patched.recipe.local_adjustments) == 1
    merged = patched.recipe.local_adjustments[0]
    assert merged.id == "local_user_1"
    assert merged.adjustments.shadows == 15.0
    assert merged.adjustments.exposure_ev == 0.2
    assert [change.path for change in patched.changes] == ["localAdjustments.mask_person.shadows"]
    assert patched.changes[0].previous == 5.0


def test_local_patch_adds_one_ai_local_per_mask_and_leaves_globals_alone():
    base = _user_recipe(
        masks=(MASK, UserMask(id="mask_sky", shape="ellipse", x=0.0, y=0.0, width=1.0, height=0.3)),
    )
    draft = _draft(
        adjustments=None,
        localAdjustments=[
            {"maskId": "mask_person", "adjustments": {"exposureEv": 0.3, "shadows": 10.0}},
            {"maskId": "mask_sky", "adjustments": {"temperature": -10.0}},
        ],
    )

    patched = apply_patch(base, report(), draft)

    assert [item.mask_id for item in patched.recipe.local_adjustments] == [
        "mask_person",
        "mask_sky",
    ]
    assert patched.recipe.local_adjustments[0].id == "local_ai_1"
    assert patched.recipe.adjustments == base.adjustments
    assert {change.path for change in patched.changes} == {
        "localAdjustments.mask_person.exposureEv",
        "localAdjustments.mask_person.shadows",
        "localAdjustments.mask_sky.temperature",
    }


def _paths(patched: Any) -> set[str]:
    return {change.path for change in patched.changes}


def _run(
    instruction: str,
    *,
    current: EditRecipe | None = None,
    analysis: Any = None,
):
    base = current or _user_recipe()
    draft = MockPlannerProvider().adjust(
        patch_request(instruction, analysis=analysis, current_recipe=base)
    )
    return base, draft, apply_patch(base, analysis or report(), draft)


def test_make_the_subject_stand_out_uses_an_existing_mask():
    base, draft, patched = _run("让人物更突出")

    assert draft.supported is True
    assert draft.adjustments is None
    assert [change.path for change in patched.changes] == [
        "localAdjustments.mask_person.exposureEv",
        "localAdjustments.mask_person.shadows",
        "localAdjustments.mask_person.clarity",
    ]
    assert patched.recipe.adjustments == base.adjustments
    assert MOCK_PLANNER_MASK_LIMITATION not in patched.limitations


def test_make_the_subject_stand_out_falls_back_globally_and_says_so_without_masks():
    base = recipe()
    _, draft, patched = _run("让人物更突出", current=base)

    assert draft.adjustments is not None
    assert patched.recipe.local_adjustments == ()
    assert patched.recipe.adjustments.exposure_ev == 0.3
    assert MOCK_PLANNER_MASK_LIMITATION in patched.limitations
    assert any("没有蒙版" in warning for warning in patched.warnings)


def test_lower_the_saturation_moves_only_saturation():
    _, _, patched = _run("降低饱和度")

    assert _paths(patched) == {"adjustments.saturation"}
    assert patched.changes[0].proposed == -8.0


def test_preserving_skin_tone_caps_the_warmth_delta():
    _, _, patched = _run("整体更暖一点，保留肤色")

    assert _paths(patched) == {"adjustments.temperature"}
    assert patched.changes[0].proposed == 6.0
    assert any("肤色保护" in warning for warning in patched.warnings)


def test_cinematic_look_stays_inside_the_sliders_and_keeps_user_grading():
    base, _, patched = _run("电影感")

    assert _paths(patched) == {
        "adjustments.contrast",
        "adjustments.highlights",
        "adjustments.shadows",
        "adjustments.saturation",
    }
    assert patched.recipe.curve == base.curve
    assert patched.recipe.color_grading == base.color_grading
    assert all(-100.0 <= change.proposed <= 100.0 for change in patched.changes)
    assert any("曲线与色彩分级" in warning for warning in patched.warnings)


@pytest.mark.parametrize(
    "instruction",
    ["删除画面里的人物", "扩图补齐边缘", "帮我换天空", "给她瘦脸"],
)
def test_capability_boundaries_are_refused_without_touching_the_recipe(instruction: str):
    base, draft, patched = _run(instruction)

    assert draft.supported is False
    assert patched.recipe == base
    assert patched.changes == ()
    assert patched.unsupported


def _layered_recipe(orders: tuple[int, ...]) -> EditRecipe:
    masks = (
        MASK,
        UserMask(id="mask_sky", shape="ellipse", x=0.0, y=0.0, width=1.0, height=0.3),
    )
    locals_ = tuple(
        LocalAdjustment(
            id=f"local_base_{index}",
            mask_id="mask_person",
            order=order,
            adjustments=LocalAdjustments(shadows=1.0),
        )
        for index, order in enumerate(orders)
    )
    return _user_recipe(masks=masks, local_adjustments=locals_)


def test_patch_rejects_the_21st_local_adjustment_with_a_recipe_error():
    base = _layered_recipe(tuple(range(20)))

    with pytest.raises(RecipeValidationError, match="at most 20"):
        apply_patch(base, report(), _local_draft("mask_sky", shadows=10.0))


def test_patch_renumbers_sparse_orders_when_appending():
    base = _layered_recipe((1, 2))

    patched = apply_patch(base, report(), _local_draft("mask_sky", shadows=10.0))

    orders = [item.order for item in patched.recipe.local_adjustments]
    assert orders == [0, 1, 2]
    assert len(set(orders)) == len(orders)
    EditRecipe.model_validate(patched.recipe.model_dump())
