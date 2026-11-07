from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.ai.contracts import (
    ColorTemperature,
    ContrastLevel,
    IssueType,
    SaturationLevel,
    SceneLabel,
    Severity,
)
from app.ai.providers.mock import MockPlannerProvider
from app.models.analysis_report import AnalysisReport
from app.models.photographer import (
    MAX_CHANGES,
    AdjustmentIntent,
    CreativeChoiceType,
    DirectionConstraint,
    LocalAdjustmentIntent,
    PhotographerPreferences,
    PlannerDraft,
)
from app.models.recipe import (
    LOCAL_V1_UNSUPPORTED_FIELDS,
    Adjustments,
    Crop,
    CurvePoint,
    CurveSet,
    EditRecipe,
    LocalAdjustment,
    LocalAdjustments,
    OutputSettings,
    UserMask,
)
from app.photographer.generator import GeneratedRecipe, generate_recipe
from app.photographer.rules import available_mask_ids
from app.photographer.validator import (
    LOW_KEY_MAX_BLACK_DELTA,
    LOW_KEY_MAX_EXPOSURE_DELTA,
    LOW_KEY_MAX_SHADOW_DELTA,
    RecipeValidationError,
    clamp_adjustment,
    known_evidence_refs,
)
from tests.photographer_support import issue, planner_request, report

PHOTOGRAPHER_CATEGORY_KEYS = (
    "portrait_balanced",
    "portrait_backlit",
    "portrait_indoor",
    "landscape",
    "landscape_sunset",
    "night",
    "architecture",
    "street",
    "high_contrast",
    "low_saturation",
    "high_saturation",
    "mixed_light",
    "low_key",
    "already_edited",
)


@dataclass(frozen=True, slots=True)
class Scenario:
    """One entry of the 第五阶段任务书 15.1 test-image categories."""

    key: str
    category: str
    analysis: AnalysisReport
    current: EditRecipe = field(default_factory=EditRecipe)
    preferences: PhotographerPreferences = field(default_factory=PhotographerPreferences)


def _edited_recipe() -> EditRecipe:
    return EditRecipe(
        adjustments=Adjustments(
            exposure_ev=-0.3,
            contrast=12.0,
            highlights=-45.0,
            shadows=20.0,
            rotation_deg=1.5,
            crop=Crop(x=0.1, y=0.05, w=0.8, h=0.9),
        ),
        curve=CurveSet(master=(CurvePoint(x=0.0, y=0.0), CurvePoint(x=0.5, y=0.55))),
        masks=(UserMask(id="mask_person", shape="rectangle", x=0.2, y=0.1, width=0.5, height=0.8),),
        local_adjustments=(
            LocalAdjustment(
                id="local_user_1",
                mask_id="mask_person",
                adjustments=LocalAdjustments(exposure_ev=0.3, shadows=10.0),
            ),
        ),
        output=OutputSettings(format="png", quality=100),
    )


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="portrait_balanced",
        category="正常人像",
        analysis=report(scene=SceneLabel.PORTRAIT),
    ),
    Scenario(
        key="portrait_backlit",
        category="逆光人像",
        analysis=report(
            scene=SceneLabel.PORTRAIT,
            issues=(
                issue(
                    "issue_background",
                    issue_type=IssueType.BACKGROUND_OVEREXPOSURE,
                    severity=Severity.HIGH,
                    confidence=0.82,
                    evidence="背景高光裁切 4.5%。",
                ),
                issue(
                    "issue_subject",
                    issue_type=IssueType.SUBJECT_UNDEREXPOSURE,
                    severity=Severity.MEDIUM,
                    confidence=0.74,
                    evidence="人物面部中间调偏低。",
                ),
            ),
            highlights_pct=4.5,
            luminance_p50=0.38,
        ),
    ),
    Scenario(
        key="portrait_indoor",
        category="室内人像",
        analysis=report(
            scene=SceneLabel.INDOOR,
            issues=(
                issue(
                    "issue_cast",
                    issue_type=IssueType.COLOR_CAST,
                    confidence=0.78,
                    evidence="整体色温偏暖，白平衡偏离。",
                ),
            ),
            temperature=ColorTemperature.WARM,
            cast_temperature=0.15,
        ),
    ),
    Scenario(
        key="landscape",
        category="风光",
        analysis=report(
            scene=SceneLabel.LANDSCAPE,
            issues=(
                issue(
                    "issue_horizon",
                    issue_type=IssueType.HORIZON_TILT,
                    severity=Severity.LOW,
                    confidence=0.7,
                    evidence="地平线倾斜约 1.4°。",
                ),
            ),
        ),
    ),
    Scenario(
        key="landscape_sunset",
        category="日落",
        analysis=report(
            scene=SceneLabel.LANDSCAPE,
            issues=(
                issue(
                    "issue_sky",
                    issue_type=IssueType.HIGHLIGHT_CLIPPING,
                    confidence=0.8,
                    evidence="天空高光裁切 2.4%。",
                ),
            ),
            temperature=ColorTemperature.WARM,
            cast_temperature=0.04,
            highlights_pct=2.4,
        ),
    ),
    Scenario(
        key="night",
        category="夜景",
        analysis=report(
            scene=SceneLabel.NIGHT,
            issues=(
                issue(
                    "issue_noise",
                    issue_type=IssueType.HIGH_NOISE,
                    confidence=0.76,
                    evidence="暗部噪点估计 0.55。",
                ),
            ),
            contrast=ContrastLevel.HIGH,
            luminance_p50=0.14,
            luminance_std=0.3,
            noise_estimate=0.55,
        ),
    ),
    Scenario(
        key="architecture",
        category="建筑",
        analysis=report(
            scene=SceneLabel.ARCHITECTURE,
            issues=(
                issue(
                    "issue_focus",
                    issue_type=IssueType.FOCUS_ISSUE,
                    confidence=0.68,
                    evidence="边缘锐度 0.06，低于同场景基线。",
                ),
            ),
            sharpness=0.06,
        ),
    ),
    Scenario(
        key="street",
        category="街头",
        analysis=report(
            scene=SceneLabel.STREET,
            issues=(
                issue(
                    "issue_balance",
                    issue_type=IssueType.BALANCE_ISSUE,
                    severity=Severity.LOW,
                    confidence=0.66,
                    evidence="画面重心偏左。",
                ),
                issue(
                    "issue_placement",
                    issue_type=IssueType.SUBJECT_PLACEMENT,
                    severity=Severity.LOW,
                    confidence=0.62,
                    evidence="主体居中，缺乏呼吸空间。",
                ),
                issue(
                    "issue_negative",
                    issue_type=IssueType.NEGATIVE_SPACE_ISSUE,
                    severity=Severity.LOW,
                    confidence=0.6,
                    evidence="留白比例偏高。",
                ),
            ),
        ),
    ),
    Scenario(
        key="high_contrast",
        category="高反差",
        analysis=report(
            scene=SceneLabel.OTHER,
            issues=(
                issue(
                    "issue_contrast",
                    issue_type=IssueType.HARSH_CONTRAST,
                    confidence=0.72,
                    evidence="明暗标准差 0.34。",
                ),
            ),
            contrast=ContrastLevel.HIGH,
            luminance_std=0.34,
        ),
    ),
    Scenario(
        key="low_saturation",
        category="低饱和度",
        analysis=report(
            scene=SceneLabel.PORTRAIT,
            saturation=SaturationLevel.LOW,
            saturation_mean=0.12,
        ),
    ),
    Scenario(
        key="high_saturation",
        category="高饱和度",
        analysis=report(
            scene=SceneLabel.FOOD,
            issues=(
                issue(
                    "issue_saturation",
                    issue_type=IssueType.SATURATION_ISSUE,
                    confidence=0.7,
                    evidence="平均饱和度 0.68。",
                ),
            ),
            saturation=SaturationLevel.HIGH,
            saturation_mean=0.68,
        ),
    ),
    Scenario(
        key="mixed_light",
        category="混合光源",
        analysis=report(
            scene=SceneLabel.INDOOR,
            issues=(
                issue(
                    "issue_mixed",
                    issue_type=IssueType.TEMPERATURE_MISMATCH,
                    confidence=0.64,
                    evidence="窗口冷光与灯光暖光并存。",
                ),
            ),
            temperature=ColorTemperature.WARM,
            cast_temperature=0.05,
            cast_tint=0.04,
        ),
    ),
    Scenario(
        key="low_key",
        category="低调风格",
        analysis=report(
            scene=SceneLabel.PORTRAIT,
            issues=(
                issue(
                    "issue_shadow",
                    issue_type=IssueType.SHADOW_CLIPPING,
                    confidence=0.7,
                    evidence="暗部裁切 4.0%。",
                ),
            ),
            contrast=ContrastLevel.HIGH,
            luminance_p50=0.18,
            shadows_pct=4.0,
        ),
    ),
    Scenario(
        key="already_edited",
        category="已后期",
        analysis=report(
            scene=SceneLabel.PORTRAIT,
            issues=(
                issue(
                    "issue_highlight",
                    issue_type=IssueType.HIGHLIGHT_CLIPPING,
                    severity=Severity.HIGH,
                    confidence=0.85,
                    evidence="高光裁切 6.0%。",
                ),
            ),
            highlights_pct=6.0,
        ),
        current=_edited_recipe(),
    ),
)


def scenario_by_key(key: str) -> Scenario:
    return next(item for item in SCENARIOS if item.key == key)


def plan_for(scenario: Scenario) -> tuple[PlannerDraft, GeneratedRecipe]:
    draft = MockPlannerProvider().plan(
        planner_request(
            analysis=scenario.analysis,
            current_recipe=scenario.current,
            preferences=scenario.preferences,
        )
    )
    return draft, generate_recipe(
        scenario.current,
        scenario.analysis,
        draft,
        scenario.preferences,
    )


def run(key: str) -> tuple[Scenario, PlannerDraft, GeneratedRecipe]:
    scenario = scenario_by_key(key)
    draft, generated = plan_for(scenario)
    return scenario, draft, generated


def changed_paths(generated: GeneratedRecipe) -> set[str]:
    return {change.path for change in generated.changes}


def adjustment_value(recipe: EditRecipe, field_name: str) -> float:
    return float(recipe.adjustments.model_dump(by_alias=True)[field_name])


def test_regression_suite_covers_every_task_book_category():
    assert [item.key for item in SCENARIOS] == list(PHOTOGRAPHER_CATEGORY_KEYS)
    assert len({item.category for item in SCENARIOS}) == 14


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[item.key for item in SCENARIOS])
def test_scenario_plan_stays_inside_the_shared_contract(scenario: Scenario):
    draft, generated = plan_for(scenario)
    recipe = generated.recipe

    # 结构化：产物始终是可通过校验的 2.0 recipe，并带诊断与方向。
    assert recipe.schema_version == "2.0"
    assert draft.diagnosis.confidence_note
    assert draft.direction.id
    assert len(generated.changes) <= MAX_CHANGES

    # 范围：每个参数都落在引擎允许区间内，且最多两位小数。
    values = recipe.adjustments.model_dump(by_alias=True)
    for name, value in values.items():
        if name == "crop":
            assert value == (
                None
                if scenario.current.adjustments.crop is None
                else scenario.current.adjustments.crop.model_dump(by_alias=True)
            )
            continue
        assert value == round(value, 2)
        assert clamp_adjustment(name, value) == value

    # 蒙版：只引用用户已有的蒙版，且从不新增、删除或改写蒙版本身。
    allowed = available_mask_ids(recipe)
    assert {item.mask_id for item in recipe.local_adjustments} <= allowed
    assert recipe.masks == scenario.current.masks
    assert recipe.local_adjustments == scenario.current.local_adjustments
    for item in recipe.local_adjustments:
        local_values = item.adjustments.model_dump(by_alias=True)
        for unsupported in LOCAL_V1_UNSUPPORTED_FIELDS:
            assert local_values[unsupported] == 0.0

    # 不执行像素操作：几何、输出与风格基线由用户掌握。
    assert recipe.adjustments.rotation_deg == scenario.current.adjustments.rotation_deg
    assert recipe.output == scenario.current.output
    assert recipe.style_id == scenario.current.style_id

    # 无编造：每条变更的证据都能在同一次分析里找到，诊断只引用真实 issue。
    known = known_evidence_refs(scenario.analysis)
    issue_ids = {item.id for item in scenario.analysis.issues}
    for change in generated.changes:
        for ref in change.evidence_refs:
            assert ref in known or ref.startswith("rule."), ref
    for item in (*draft.diagnosis.confirmed, *draft.diagnosis.possible):
        assert item.issue_id in issue_ids
        for ref in item.evidence_refs:
            assert ref in known, ref

    # 如实标注：mock provider 的局限必须出现在方案里。
    assert any("模拟" in item for item in draft.limitations)


def test_balanced_portrait_barely_moves():
    _, draft, generated = run("portrait_balanced")

    assert generated.changes == ()
    assert generated.recipe == scenario_by_key("portrait_balanced").current
    assert any("已忽略模型提出的额外参数调整" in item for item in generated.warnings)
    assert CreativeChoiceType.ALREADY_EDITED in {
        item.type for item in draft.diagnosis.creative_choices
    }
    assert draft.direction.strength <= 0.3
    assert any("阶段三未提供明确问题" in item for item in draft.warnings)


def test_backlit_portrait_protects_background_and_lifts_subject():
    _, draft, generated = run("portrait_backlit")

    assert adjustment_value(generated.recipe, "highlights") < 0.0
    assert adjustment_value(generated.recipe, "shadows") > 0.0
    assert abs(generated.recipe.adjustments.exposure_ev) <= 0.5
    assert {item.issue_id for item in draft.diagnosis.confirmed} == {
        "issue_background",
        "issue_subject",
    }
    assert DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL in draft.direction.constraints


def test_indoor_portrait_corrects_a_measured_cast_within_the_color_guard():
    _, draft, generated = run("portrait_indoor")

    temperature = generated.recipe.adjustments.temperature
    assert temperature < 0.0
    assert abs(temperature) <= 8.0
    assert DirectionConstraint.AVOID_COLOR_CAST in draft.direction.constraints
    assert IssueType.COLOR_CAST in {item.type for item in draft.diagnosis.confirmed}


def test_landscape_leaves_the_tilted_horizon_to_the_photographer():
    _, _, generated = run("landscape")

    assert changed_paths(generated) <= {
        "adjustments.vibrance",
        "adjustments.clarity",
        "adjustments.highlights",
    }
    assert generated.recipe.adjustments.rotation_deg == 0.0
    assert adjustment_value(generated.recipe, "highlights") < 0.0
    assert adjustment_value(generated.recipe, "clarity") > 0.0


def test_sunset_keeps_the_warm_light_and_recovers_the_sky():
    _, draft, generated = run("landscape_sunset")

    assert generated.recipe.adjustments.temperature == 0.0
    assert "adjustments.temperature" not in changed_paths(generated)
    assert adjustment_value(generated.recipe, "highlights") < 0.0
    assert CreativeChoiceType.WARM_AMBIENT in {
        item.type for item in draft.diagnosis.creative_choices
    }
    assert {
        DirectionConstraint.KEEP_AMBIENT_COLOR,
        DirectionConstraint.KEEP_WARM_TONES,
    } <= set(draft.direction.constraints)


def test_night_keeps_low_key_and_only_reduces_noise():
    _, draft, generated = run("night")
    recipe = generated.recipe

    assert adjustment_value(recipe, "denoise") > 0.0
    assert recipe.adjustments.exposure_ev <= LOW_KEY_MAX_EXPOSURE_DELTA
    assert recipe.adjustments.shadows <= LOW_KEY_MAX_SHADOW_DELTA
    assert recipe.adjustments.blacks == 0.0
    assert CreativeChoiceType.LOW_KEY_INTENT in {
        item.type for item in draft.diagnosis.creative_choices
    }
    assert DirectionConstraint.KEEP_LOW_KEY in draft.direction.constraints


def test_architecture_recovers_detail_without_cropping():
    _, _, generated = run("architecture")
    recipe = generated.recipe

    assert adjustment_value(recipe, "sharpen") > 0.0
    assert adjustment_value(recipe, "clarity") > 0.0
    assert recipe.adjustments.sharpen <= 100.0
    assert recipe.adjustments.crop is None


def test_street_composition_notes_never_become_a_crop():
    _, draft, generated = run("street")

    assert {item.issue_id for item in draft.diagnosis.confirmed} == {
        "issue_balance",
        "issue_placement",
        "issue_negative",
    }
    assert changed_paths(generated) <= {"adjustments.contrast", "adjustments.clarity"}
    assert generated.recipe.adjustments.crop is None
    assert generated.recipe.adjustments.rotation_deg == 0.0


def test_high_contrast_is_read_as_an_intentional_look():
    _, draft, generated = run("high_contrast")

    assert generated.changes == ()
    assert generated.recipe.adjustments.contrast == 0.0
    assert CreativeChoiceType.HIGH_CONTRAST_INTENT in {
        item.type for item in draft.diagnosis.creative_choices
    }
    assert any("未生成参数调整" in item for item in draft.warnings)


def test_low_saturation_is_not_pumped_up():
    _, draft, generated = run("low_saturation")

    assert generated.changes == ()
    assert generated.recipe.adjustments.saturation == 0.0
    assert generated.recipe.adjustments.vibrance == 0.0
    assert CreativeChoiceType.LOW_SATURATION_INTENT in {
        item.type for item in draft.diagnosis.creative_choices
    }
    assert DirectionConstraint.AVOID_EXTREME_SATURATION in draft.direction.constraints


def test_high_saturation_is_never_pushed_further():
    _, draft, generated = run("high_saturation")

    assert adjustment_value(generated.recipe, "saturation") < 0.0
    assert adjustment_value(generated.recipe, "vibrance") <= 0.0
    assert CreativeChoiceType.HIGH_SATURATION_INTENT in {
        item.type for item in draft.diagnosis.creative_choices
    }
    assert "adjustments.temperature" not in changed_paths(generated)


def test_mixed_light_is_recorded_but_not_force_neutralized():
    _, draft, generated = run("mixed_light")

    assert generated.recipe.adjustments.temperature == 0.0
    assert generated.recipe.adjustments.tint == 0.0
    assert {item.issue_id for item in draft.diagnosis.possible} == {"issue_mixed"}
    assert draft.diagnosis.confirmed == ()
    assert DirectionConstraint.KEEP_AMBIENT_COLOR in draft.direction.constraints


def test_low_key_keeps_its_shadow_structure():
    _, draft, generated = run("low_key")
    recipe = generated.recipe

    assert recipe.adjustments.exposure_ev == 0.0
    assert 0.0 < recipe.adjustments.shadows <= LOW_KEY_MAX_SHADOW_DELTA
    assert 0.0 < recipe.adjustments.blacks <= LOW_KEY_MAX_BLACK_DELTA
    assert CreativeChoiceType.LOW_KEY_INTENT in {
        item.type for item in draft.diagnosis.creative_choices
    }


def test_already_edited_recipe_is_extended_instead_of_rewritten():
    scenario, _, generated = run("already_edited")
    base = scenario.current
    recipe = generated.recipe

    assert recipe.adjustments.highlights < base.adjustments.highlights
    assert recipe.adjustments.shadows == base.adjustments.shadows
    assert recipe.adjustments.contrast == base.adjustments.contrast
    assert recipe.adjustments.exposure_ev == base.adjustments.exposure_ev
    assert recipe.curve == base.curve
    assert recipe.masks == base.masks
    assert recipe.local_adjustments == base.local_adjustments
    for change in generated.changes:
        if change.path.startswith("adjustments."):
            name = change.path.removeprefix("adjustments.")
            assert change.previous == adjustment_value(base, name)


def test_plans_are_reproducible_for_the_same_analysis():
    for scenario in SCENARIOS:
        first = plan_for(scenario)[1].recipe.model_dump(by_alias=True, mode="json")
        second = plan_for(scenario)[1].recipe.model_dump(by_alias=True, mode="json")
        assert first == second, scenario.key


def test_fabricated_mask_id_is_rejected():
    scenario, draft, _ = run("portrait_backlit")
    tampered = draft.model_copy(
        update={
            "local_adjustments": (
                LocalAdjustmentIntent(
                    mask_id="mask_ghost",
                    adjustments=AdjustmentIntent(exposure_ev=0.4),
                ),
            )
        }
    )

    with pytest.raises(RecipeValidationError, match="unknown maskId"):
        generate_recipe(scenario.current, scenario.analysis, tampered, scenario.preferences)


def test_fabricated_evidence_reference_is_rejected():
    scenario, draft, _ = run("portrait_backlit")
    diagnosis = draft.diagnosis.model_copy(
        update={
            "confirmed": tuple(
                item.model_copy(update={"evidence_refs": ("issue_ghost", "region_ghost")})
                for item in draft.diagnosis.confirmed
            )
        }
    )

    with pytest.raises(RecipeValidationError, match="cites unknown evidence"):
        generate_recipe(
            scenario.current,
            scenario.analysis,
            draft.model_copy(update={"diagnosis": diagnosis}),
            scenario.preferences,
        )


def test_out_of_range_draft_values_are_clamped_instead_of_rejected():
    scenario, draft, _ = run("portrait_backlit")
    tampered = draft.model_copy(
        update={"adjustments": draft.adjustments.model_copy(update={"highlights": -500.0})}
    )

    generated = generate_recipe(
        scenario.current,
        scenario.analysis,
        tampered,
        scenario.preferences,
    )

    assert generated.recipe.adjustments.highlights == -100.0
