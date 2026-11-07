from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.contracts import (
    ColorTemperature,
    IssueType,
    SaturationLevel,
    SceneLabel,
    Severity,
)
from app.imaging.loader import load_image
from app.imaging.pipeline import render
from app.models.photographer import (
    AdjustmentIntent,
    LocalAdjustmentIntent,
    ParameterChange,
    PhotographerPreferences,
    PlannerDraft,
    StyleEnvelope,
)
from app.models.recipe import (
    Adjustments,
    Crop,
    CurvePoint,
    CurveSet,
    HslAdjustments,
    HslBand,
    LocalAdjustment,
    LocalAdjustments,
    OutputSettings,
    UserMask,
)
from app.photographer.diagnosis import diagnose
from app.photographer.direction import determine_direction
from app.photographer.generator import generate_recipe
from app.photographer.styles import (
    get_style,
    style_curve_points,
    style_grading,
)
from app.photographer.validator import (
    RecipeValidationError,
    validate_recipe,
)
from tests.golden_support import source_bytes
from tests.photographer_support import issue, recipe, report

MASK = UserMask(id="mask_001", x=0.1, y=0.1, width=0.3, height=0.3)


def _draft(
    analysis,
    adjustments: AdjustmentIntent | None = None,
    local_adjustments: tuple[LocalAdjustmentIntent, ...] = (),
) -> PlannerDraft:
    preferences = PhotographerPreferences()
    diagnosis = diagnose(analysis)
    direction = determine_direction(analysis, diagnosis, preferences)
    return PlannerDraft(
        diagnosis=diagnosis,
        direction=direction,
        adjustments=adjustments or AdjustmentIntent(),
        local_adjustments=local_adjustments,
    )


def _clipped_report(**overrides):
    return report(
        scene=overrides.pop("scene", SceneLabel.PORTRAIT),
        issues=(
            issue(
                "issue_clip",
                issue_type=IssueType.HIGHLIGHT_CLIPPING,
                confidence=0.85,
            ),
        ),
        highlights_pct=8.0,
        **overrides,
    )


def _two_places(value: float) -> bool:
    exponent = Decimal(repr(float(value))).as_tuple().exponent
    return not isinstance(exponent, int) or exponent >= -2


def test_generator_applies_intent_on_top_of_current_recipe():
    analysis = _clipped_report()
    base = recipe().model_copy(
        update={
            "adjustments": recipe().adjustments.model_copy(
                update={
                    "exposure_ev": 0.5,
                    "contrast": 10.0,
                    "rotation_deg": 3.0,
                    "crop": Crop(x=0.1, y=0.1, w=0.5, h=0.5),
                }
            ),
            "output": OutputSettings(format="png", quality=80),
        }
    )
    draft = _draft(analysis, AdjustmentIntent(highlights=-20.0))

    result = generate_recipe(base, analysis, draft)

    assert result.recipe.adjustments.highlights == -20.0
    assert result.recipe.adjustments.exposure_ev == 0.5
    assert result.recipe.adjustments.contrast == 10.0
    assert result.recipe.adjustments.rotation_deg == 3.0
    assert result.recipe.adjustments.crop == base.adjustments.crop
    assert result.recipe.output == base.output
    change = next(change for change in result.changes if change.path == "adjustments.highlights")
    assert change.previous == 0.0
    assert change.proposed == -20.0
    assert "issue_clip" in change.evidence_refs
    assert "measurement.clipping.highlightsPct" in change.evidence_refs
    validate_recipe(result.recipe, current=base, report=analysis, changes=result.changes)


def test_generator_preserves_unplanned_fields_curves_masks_and_output():
    base = recipe().model_copy(
        update={
            "curve": CurveSet(master=(CurvePoint(x=0.0, y=0.0), CurvePoint(x=1.0, y=0.9))),
            "hsl": HslAdjustments(orange=HslBand(saturation=12.0)),
            "masks": (MASK,),
            "local_adjustments": (
                LocalAdjustment(
                    id="local_user",
                    mask_id="mask_001",
                    adjustments=LocalAdjustments(exposure_ev=1.0),
                ),
            ),
            "output": OutputSettings(format="png"),
        }
    )
    analysis = _clipped_report()
    draft = _draft(analysis, AdjustmentIntent(highlights=-10.0))

    result = generate_recipe(base, analysis, draft)

    assert result.recipe.curve == base.curve
    assert result.recipe.hsl == base.hsl
    assert result.recipe.masks == base.masks
    assert result.recipe.local_adjustments == base.local_adjustments
    assert result.recipe.output == base.output


def test_model_values_are_used_as_fallbacks_when_absent():
    analysis = _clipped_report()
    draft = _draft(analysis)

    result = generate_recipe(recipe(), analysis, draft)

    assert result.recipe.adjustments.highlights < 0
    assert result.changes
    assert all(change.evidence_refs for change in result.changes)


def test_style_curve_and_grading_are_applied_when_strength_is_positive():
    style = get_style("film")
    assert style is not None
    analysis = report(scene=SceneLabel.PORTRAIT)
    draft = _draft(analysis)
    preferences = PhotographerPreferences(
        naturalness=0.0, allow_stylization=True, preserve_original_color=False
    )

    result = generate_recipe(recipe(), analysis, draft, preferences, style, 0.75)

    assert result.recipe.style_id == "film"
    assert result.recipe.style_strength == 75.0
    assert result.recipe.curve.master == style_curve_points("film", 0.75)
    assert result.recipe.color_grading == style_grading("film", 0.75)
    assert {change.path for change in result.changes} >= {"curve.master", "colorGrading"}


def test_style_strength_zero_applies_no_style_parameters():
    style = get_style("film")
    assert style is not None
    analysis = report(scene=SceneLabel.PORTRAIT)
    draft = _draft(analysis)

    result = generate_recipe(recipe(), analysis, draft, style=style, style_strength=0.0)

    assert result.recipe.adjustments == recipe().adjustments
    assert result.recipe.curve == recipe().curve
    assert result.recipe.color_grading == recipe().color_grading
    assert result.recipe.style_id == "film"
    assert result.recipe.style_strength == 0.0
    assert result.changes == ()


def test_style_strength_is_monotonic():
    style = get_style("cinematic")
    assert style is not None
    analysis = report(scene=SceneLabel.PORTRAIT)
    draft = _draft(analysis)
    preferences = PhotographerPreferences(
        naturalness=0.0, allow_stylization=True, preserve_original_color=False
    )

    contrast_values: list[float] = []
    grading_values: list[float] = []
    for strength in (0.0, 0.25, 0.5, 0.75, 1.0):
        result = generate_recipe(recipe(), analysis, draft, preferences, style, strength)
        contrast_values.append(abs(result.recipe.adjustments.contrast))
        grading_values.append(result.recipe.color_grading.highlights.saturation)

    assert contrast_values[0] == 0.0
    assert contrast_values == sorted(contrast_values)
    assert grading_values[0] == 0.0
    assert grading_values == sorted(grading_values)


def test_style_envelope_caps_style_parameters():
    style = get_style("cinematic")
    assert style is not None
    capped = style.model_copy(update={"envelope": StyleEnvelope(contrast=5.0)})
    analysis = report(scene=SceneLabel.PORTRAIT)
    draft = _draft(analysis)
    preferences = PhotographerPreferences(
        naturalness=0.0, allow_stylization=True, preserve_original_color=False
    )

    result = generate_recipe(recipe(), analysis, draft, preferences, capped, 1.0)

    assert abs(result.recipe.adjustments.contrast) <= 5.0


def test_user_curve_is_not_overwritten_by_a_style():
    style = get_style("film")
    assert style is not None
    user_curve = CurveSet(master=(CurvePoint(x=0.0, y=0.0), CurvePoint(x=1.0, y=0.8)))
    base = recipe().model_copy(update={"curve": user_curve})
    analysis = report(scene=SceneLabel.PORTRAIT)
    draft = _draft(analysis)

    result = generate_recipe(base, analysis, draft, style=style, style_strength=0.8)

    assert result.recipe.curve == user_curve
    assert any("主曲线" in warning for warning in result.warnings)


def test_style_curve_keeps_user_color_channels():
    style = get_style("film")
    assert style is not None
    user_curve = CurveSet(
        red=(CurvePoint(x=0.0, y=0.0), CurvePoint(x=1.0, y=0.95)),
    )
    base = recipe().model_copy(update={"curve": user_curve})
    analysis = report(scene=SceneLabel.PORTRAIT)
    draft = _draft(analysis)

    result = generate_recipe(base, analysis, draft, style=style, style_strength=0.5)

    assert result.recipe.curve.red == user_curve.red
    assert result.recipe.curve.master


def test_high_saturation_is_not_boosted():
    analysis = report(
        scene=SceneLabel.OTHER,
        saturation=SaturationLevel.HIGH,
        saturation_mean=0.62,
        issues=(
            issue(
                "issue_sat",
                issue_type=IssueType.SATURATION_ISSUE,
                confidence=0.8,
            ),
        ),
    )

    result = generate_recipe(
        recipe(),
        analysis,
        _draft(analysis, AdjustmentIntent(saturation=20.0, vibrance=20.0)),
    )

    assert result.recipe.adjustments.saturation <= 0.0
    assert result.recipe.adjustments.vibrance <= 0.0
    assert any("饱和度" in warning for warning in result.warnings)


def test_low_saturation_is_not_boosted():
    analysis = report(
        scene=SceneLabel.OTHER,
        saturation=SaturationLevel.LOW,
        saturation_mean=0.12,
        issues=(issue("issue_sat", issue_type=IssueType.SATURATION_ISSUE),),
    )

    result = generate_recipe(
        recipe(), analysis, _draft(analysis, AdjustmentIntent(saturation=15.0))
    )

    assert result.recipe.adjustments.saturation <= 0.0


def test_low_key_is_not_mechanically_brightened():
    analysis = report(
        scene=SceneLabel.NIGHT,
        luminance_p50=0.12,
        issues=(
            issue(
                "issue_dark",
                issue_type=IssueType.UNDEREXPOSURE,
                severity=Severity.HIGH,
                confidence=0.9,
            ),
        ),
    )

    result = generate_recipe(
        recipe(),
        analysis,
        _draft(
            analysis,
            AdjustmentIntent(exposure_ev=2.0, shadows=40.0, blacks=20.0),
        ),
    )

    assert result.recipe.adjustments.exposure_ev <= 0.2
    assert result.recipe.adjustments.shadows <= 6.0
    assert result.recipe.adjustments.blacks <= 4.0
    assert result.warnings


def test_sunset_is_not_forced_cooler():
    analysis = report(
        scene=SceneLabel.LANDSCAPE,
        temperature=ColorTemperature.WARM,
        cast_temperature=0.03,
        issues=(issue("issue_temp", issue_type=IssueType.TEMPERATURE_MISMATCH),),
    )

    result = generate_recipe(
        recipe(), analysis, _draft(analysis, AdjustmentIntent(temperature=-20.0))
    )

    assert result.recipe.adjustments.temperature >= 0.0
    assert any("冷化" in warning for warning in result.warnings)


def test_cool_ambient_is_not_forced_warmer():
    analysis = report(
        scene=SceneLabel.OTHER,
        temperature=ColorTemperature.COOL,
        cast_temperature=0.03,
        issues=(issue("issue_temp", issue_type=IssueType.TEMPERATURE_MISMATCH),),
    )

    result = generate_recipe(
        recipe(), analysis, _draft(analysis, AdjustmentIntent(temperature=20.0))
    )

    assert result.recipe.adjustments.temperature <= 0.0
    assert any("暖化" in warning for warning in result.warnings)


def test_forged_mask_id_is_rejected():
    analysis = _clipped_report()
    intent = LocalAdjustmentIntent(
        mask_id="mask_999",
        adjustments=AdjustmentIntent(exposure_ev=1.0),
    )

    with pytest.raises(RecipeValidationError) as excinfo:
        generate_recipe(recipe(), analysis, _draft(analysis, local_adjustments=(intent,)))
    assert "maskId mask_999" in str(excinfo.value)


def test_full_mask_local_adjustment_is_allowed_without_masks():
    analysis = _clipped_report()
    intent = LocalAdjustmentIntent(
        mask_id="full",
        adjustments=AdjustmentIntent(exposure_ev=0.5),
    )

    result = generate_recipe(recipe(), analysis, _draft(analysis, local_adjustments=(intent,)))

    assert len(result.recipe.local_adjustments) == 1
    local = result.recipe.local_adjustments[0]
    assert local.mask_id == "full"
    assert local.id == "local_ai_1"
    assert local.adjustments.exposure_ev == 0.5
    assert any(change.path.startswith("localAdjustments.full.") for change in result.changes)


def test_local_adjustment_merges_into_the_existing_mask_adjustment():
    base = recipe().model_copy(
        update={
            "masks": (MASK,),
            "local_adjustments": (
                LocalAdjustment(
                    id="local_user",
                    mask_id="mask_001",
                    adjustments=LocalAdjustments(exposure_ev=1.0),
                ),
            ),
        }
    )
    analysis = _clipped_report()
    intent = LocalAdjustmentIntent(
        mask_id="mask_001",
        adjustments=AdjustmentIntent(exposure_ev=0.5, contrast=10.0),
    )

    result = generate_recipe(base, analysis, _draft(analysis, local_adjustments=(intent,)))

    assert len(result.recipe.local_adjustments) == 1
    local = result.recipe.local_adjustments[0]
    assert local.id == "local_user"
    assert local.adjustments.exposure_ev == 1.5
    assert local.adjustments.contrast == 10.0
    assert result.recipe.masks == base.masks


def test_validator_rejects_unsupported_local_fields():
    bad_local = LocalAdjustment.model_construct(
        id="local_bad",
        mask_id="full",
        enabled=True,
        adjustments=LocalAdjustments.model_construct(sharpen=10.0),
    )
    bad = recipe().model_copy(update={"local_adjustments": (bad_local,)})

    with pytest.raises(RecipeValidationError) as excinfo:
        validate_recipe(bad, current=recipe())
    assert "unsupported field sharpen" in str(excinfo.value)


def test_validator_rejects_geometry_output_and_mask_changes():
    base = recipe()
    geometry = base.model_copy(
        update={
            "adjustments": base.adjustments.model_copy(
                update={"rotation_deg": 2.0, "crop": Crop(x=0.1, y=0.1, w=0.5, h=0.5)}
            )
        }
    )
    with pytest.raises(RecipeValidationError) as geometry_error:
        validate_recipe(geometry, current=base)
    assert "crop" in str(geometry_error.value)
    assert "rotationDeg" in str(geometry_error.value)

    output = base.model_copy(update={"output": OutputSettings(format="png")})
    with pytest.raises(RecipeValidationError) as output_error:
        validate_recipe(output, current=base)
    assert "output" in str(output_error.value)

    masks = base.model_copy(update={"masks": (MASK,)})
    with pytest.raises(RecipeValidationError) as mask_error:
        validate_recipe(masks, current=base)
    assert "masks" in str(mask_error.value)


def test_validator_rejects_out_of_range_and_precision_issues():
    values = recipe().adjustments.model_dump()
    values["contrast"] = 150.0
    out_of_range = recipe().model_copy(
        update={"adjustments": Adjustments.model_construct(**values)}
    )
    with pytest.raises(RecipeValidationError) as range_error:
        validate_recipe(out_of_range, current=recipe())
    assert "contrast" in str(range_error.value)

    values = recipe().adjustments.model_dump()
    values["contrast"] = 1.234
    too_precise = recipe().model_copy(update={"adjustments": Adjustments.model_construct(**values)})
    with pytest.raises(RecipeValidationError) as precision_error:
        validate_recipe(too_precise, current=recipe())
    assert "two decimal" in str(precision_error.value)


def test_validator_rejects_unknown_evidence_refs():
    change = ParameterChange(
        path="adjustments.exposureEv",
        previous=0.0,
        proposed=0.1,
        reason="测试证据校验。",
        evidence_refs=("issue_missing",),
    )

    with pytest.raises(RecipeValidationError) as excinfo:
        validate_recipe(recipe(), current=recipe(), report=report(), changes=(change,))
    assert "unknown evidence" in str(excinfo.value)


def test_generator_rounds_to_two_decimals_and_keeps_change_paths_unique():
    style = get_style("cinematic")
    assert style is not None
    analysis = _clipped_report()
    draft = _draft(analysis, AdjustmentIntent(exposure_ev=0.333))
    preferences = PhotographerPreferences(
        naturalness=0.0, allow_stylization=True, preserve_original_color=False
    )

    result = generate_recipe(recipe(), analysis, draft, preferences, style, 0.5)

    payload = result.recipe.adjustments.model_dump()
    assert all(_two_places(value) for value in payload.values() if isinstance(value, float))
    paths = [change.path for change in result.changes]
    assert len(paths) == len(set(paths))
    assert len(result.changes) <= 10


def test_generated_recipe_is_accepted_by_pydantic_and_the_renderer():
    style = get_style("film")
    assert style is not None
    analysis = _clipped_report()
    draft = _draft(analysis, AdjustmentIntent(highlights=-12.0))
    result = generate_recipe(recipe(), analysis, draft, style=style, style_strength=0.5)

    reloaded = result.recipe.__class__.model_validate(result.recipe.model_dump(by_alias=True))
    assert reloaded == result.recipe
    rendered = render(
        load_image(source_bytes("ramp")),
        reloaded.adjustments,
        image_sha256="a" * 64,
        curve=reloaded.curve,
        hsl=reloaded.hsl,
        color_grading=reloaded.color_grading,
        masks=reloaded.masks,
        local_adjustments=reloaded.local_adjustments,
        quality="draft",
    )
    assert rendered.rgb.dtype.name == "uint8"
    assert rendered.width > 0 and rendered.height > 0


def test_style_curve_points_stay_ordered_and_inside_the_unit_interval():
    for style_id in ("landscape", "street", "film", "cinematic"):
        for strength in (0.25, 0.5, 1.0):
            points = style_curve_points(style_id, strength)
            xs = [point.x for point in points]
            assert xs == sorted(xs)
            assert len(xs) == len(set(xs))
            assert all(0.0 <= point.y <= 1.0 for point in points)
    assert style_curve_points("film", 0.0) == ()


def test_style_grading_waits_for_the_minimum_strength():
    assert style_grading("film", 0.24) is None
    assert style_grading("film", 0.25) is not None
    assert style_grading("natural", 1.0) is None


def test_already_balanced_frame_produces_no_change():
    analysis = report(scene=SceneLabel.STREET)
    draft = _draft(analysis)

    result = generate_recipe(recipe(), analysis, draft)

    assert result.changes == ()
    assert result.recipe.adjustments == recipe().adjustments
    assert any("未生成新的像素调整" in warning for warning in result.warnings)
