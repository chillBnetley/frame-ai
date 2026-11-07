from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai.contracts import IssueType, SceneLabel
from app.imaging.color_ops import apply_color
from app.models.photographer import (
    PhotographerPlanResponse,
    PhotographerPreferences,
    PlannerDraft,
    PlannerMode,
    ProviderInfo,
    StyleCategory,
    StyleDefinition,
)
from app.models.recipe import STYLE_IDS, EditRecipe, LocalAdjustment, LocalAdjustments, UserMask
from app.photographer.diagnosis import diagnose
from app.photographer.direction import determine_direction
from app.photographer.generator import generate_recipe
from app.photographer.styles import (
    STYLE_CATALOG,
    blend_factor,
    get_style,
    style_adjustment_intent,
    style_curve_points,
    style_grading,
    style_local_intent,
)
from tests.photographer_support import issue, recipe, report

MASK = UserMask(id="mask_001", x=0.1, y=0.1, width=0.3, height=0.3)
STRENGTHS = (0.0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0)
_PERMISSIVE = PhotographerPreferences(
    naturalness=0.0,
    adjustment_strength=1.0,
    allow_stylization=True,
    preserve_original_color=False,
)


def _draft(analysis, preferences: PhotographerPreferences | None = None) -> PlannerDraft:
    effective = preferences or PhotographerPreferences()
    diagnosis = diagnose(analysis)
    return PlannerDraft(
        diagnosis=diagnosis,
        direction=determine_direction(analysis, diagnosis, effective),
    )


def _masked_recipe() -> EditRecipe:
    return recipe().model_copy(update={"masks": (MASK,)})


def test_catalog_covers_the_required_style_matrix():
    names = {style.name for style in STYLE_CATALOG}

    assert names >= {
        "自然摄影",
        "自然人像",
        "清透人像",
        "风光",
        "街头",
        "电影叙事",
        "复古胶片",
        "黑白纪实",
        "鲜艳纪实",
        "暖调生活",
        "冷调城市",
    }
    assert len(STYLE_CATALOG) >= 10
    assert all(style.supported_scenes for style in STYLE_CATALOG)
    assert all(style.version for style in STYLE_CATALOG)


def test_monochrome_is_not_limited_by_the_engine_style_ids():
    engine_ids = set(STYLE_IDS)

    assert "monochrome" not in engine_ids
    assert {style.id for style in STYLE_CATALOG} - engine_ids
    assert {style.engine_style for style in STYLE_CATALOG} <= engine_ids


def test_generated_recipe_stores_the_engine_style_metadata():
    style = get_style("monochrome")
    assert style is not None

    result = generate_recipe(
        recipe(),
        report(scene=SceneLabel.STREET),
        _draft(report(scene=SceneLabel.STREET)),
        PhotographerPreferences(),
        style,
        0.7,
    )

    assert result.recipe.style_id == style.engine_style
    assert result.recipe.style_strength == 70.0


def test_strength_zero_applies_no_style_parameters():
    for style in STYLE_CATALOG:
        assert style_adjustment_intent(style, 0.0, _PERMISSIVE) == {}
        assert style_curve_points(style.id, 0.0) == ()
        assert style_grading(style.id, 0.0) is None
        assert style_local_intent(style.id, 0.0) == {}


def test_style_strength_is_monotonic_and_bounded_for_every_style():
    for style in STYLE_CATALOG:
        envelope = style.envelope.model_dump(by_alias=True)
        seen: dict[str, list[float]] = {}
        for strength in STRENGTHS:
            for field, value in style_adjustment_intent(style, strength, _PERMISSIVE).items():
                assert abs(value) <= float(envelope[field]) + 1e-9, (style.id, field, value)
                seen.setdefault(field, []).append(abs(value))
        for field, values in seen.items():
            assert values == sorted(values), (style.id, field, values)

        curve_distance = [
            sum(abs(point.y - point.x) for point in style_curve_points(style.id, strength))
            for strength in STRENGTHS
        ]
        assert curve_distance == sorted(curve_distance), style.id

        grading_totals: list[float] = []
        for strength in STRENGTHS:
            grading = style_grading(style.id, strength)
            grading_totals.append(
                0.0
                if grading is None
                else grading.shadows.saturation
                + grading.midtones.saturation
                + grading.highlights.saturation
            )
        assert grading_totals == sorted(grading_totals), style.id

        local_values: dict[str, list[float]] = {}
        for strength in STRENGTHS:
            for field, value in style_local_intent(style.id, strength).items():
                local_values.setdefault(field, []).append(abs(value))
        for field, values in local_values.items():
            assert values == sorted(values), (style.id, field, values)


def test_blend_factor_is_non_linear():
    assert blend_factor("exposureEv", 0.25) == pytest.approx(0.5)
    assert blend_factor("contrast", 0.1) == 0.0
    assert blend_factor("contrast", 0.15) == 0.0
    assert 0.0 < blend_factor("contrast", 0.5) < 0.5
    assert blend_factor("contrast", 1.0) == pytest.approx(1.0)
    assert blend_factor("saturation", 0.5) == pytest.approx(0.5)


def test_same_style_produces_different_parameters_on_different_photos():
    style = get_style("film")
    assert style is not None
    first_analysis = report(
        scene=SceneLabel.PORTRAIT,
        issues=(issue("issue_subject", issue_type=IssueType.SUBJECT_UNDEREXPOSURE),),
        luminance_p50=0.2,
    )
    second_analysis = report(
        scene=SceneLabel.LANDSCAPE,
        issues=(issue("issue_sky", issue_type=IssueType.HIGHLIGHT_CLIPPING),),
        highlights_pct=9.0,
        saturation_mean=0.62,
    )

    first = generate_recipe(
        recipe(),
        first_analysis,
        _draft(first_analysis),
        PhotographerPreferences(),
        style,
        0.6,
    )
    second = generate_recipe(
        recipe(),
        second_analysis,
        _draft(second_analysis),
        PhotographerPreferences(),
        style,
        0.6,
    )

    assert first.recipe.adjustments != second.recipe.adjustments
    assert first.recipe.style_id == second.recipe.style_id
    assert first.recipe.curve.master == second.recipe.curve.master


def test_monochrome_style_desaturates_without_collapsing_tonal_range():
    style = get_style("monochrome")
    assert style is not None
    analysis = report(scene=SceneLabel.STREET)

    result = generate_recipe(
        recipe(),
        analysis,
        _draft(analysis),
        PhotographerPreferences(),
        style,
        style.default_strength,
    )
    adjustments = result.recipe.adjustments.model_dump(by_alias=True)

    assert adjustments["saturation"] == -100.0
    assert abs(adjustments["highlights"]) <= style.envelope.highlights
    assert abs(adjustments["shadows"]) <= style.envelope.shadows
    assert abs(adjustments["whites"]) <= style.envelope.whites
    assert abs(adjustments["blacks"]) <= style.envelope.blacks

    pixels = np.array(
        [
            [[0.92, 0.31, 0.12], [0.05, 0.62, 0.75]],
            [[0.44, 0.02, 0.55], [0.78, 0.80, 0.82]],
        ],
        dtype=np.float32,
    )
    mono = apply_color(pixels, saturation=-100.0, vibrance=0.0)

    np.testing.assert_allclose(mono[..., 0], mono[..., 1], atol=1e-6)
    np.testing.assert_allclose(mono[..., 0], mono[..., 2], atol=1e-6)
    luminance = pixels @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    np.testing.assert_allclose(mono[..., 0], luminance, atol=1e-6)
    assert mono[..., 0].max() - mono[..., 0].min() == pytest.approx(
        luminance.max() - luminance.min(),
        abs=1e-6,
    )


def test_style_local_strategy_uses_existing_user_masks():
    style = get_style("portrait")
    assert style is not None
    analysis = report(scene=SceneLabel.PORTRAIT)

    result = generate_recipe(
        _masked_recipe(),
        analysis,
        _draft(analysis),
        PhotographerPreferences(),
        style,
        0.6,
    )
    expected = style_local_intent(style.id, 0.6)

    assert [item.mask_id for item in result.recipe.local_adjustments] == [MASK.id]
    applied = result.recipe.local_adjustments[0].adjustments.model_dump(by_alias=True)
    for field, delta in expected.items():
        assert applied[field] == pytest.approx(delta)
    assert {change.path for change in result.changes} >= {
        f"localAdjustments.{MASK.id}.{field}" for field in expected
    }


def test_style_local_strategy_keeps_existing_local_edits():
    style = get_style("portrait")
    assert style is not None
    analysis = report(scene=SceneLabel.PORTRAIT)
    existing = LocalAdjustment(
        id="local_user_1",
        mask_id=MASK.id,
        adjustments=LocalAdjustments(shadows=5.0),
    )
    base = recipe().model_copy(update={"masks": (MASK,), "local_adjustments": (existing,)})

    result = generate_recipe(
        base,
        analysis,
        _draft(analysis),
        PhotographerPreferences(),
        style,
        0.6,
    )
    expected = style_local_intent(style.id, 0.6)

    assert len(result.recipe.local_adjustments) == 1
    assert result.recipe.local_adjustments[0].id == existing.id
    assert result.recipe.local_adjustments[0].adjustments.shadows == pytest.approx(
        5.0 + expected["shadows"]
    )
    assert result.recipe.masks == base.masks


def test_style_local_strategy_reports_a_limitation_without_masks():
    style = get_style("portrait")
    assert style is not None
    analysis = report(scene=SceneLabel.PORTRAIT)

    result = generate_recipe(
        recipe(),
        analysis,
        _draft(analysis),
        PhotographerPreferences(),
        style,
        0.6,
    )

    assert result.recipe.local_adjustments == ()
    assert any("蒙版" in warning for warning in result.warnings)


def test_style_definition_defaults_the_engine_style():
    style = StyleDefinition(
        id="custom_look",
        name="自定义",
        category=StyleCategory.CREATIVE,
        description="测试风格。",
        supported_scenes=(SceneLabel.OTHER,),
    )

    assert style.id == "custom_look"
    assert style.engine_style == "natural"
    assert style.enabled is True


def test_style_ids_follow_the_photographer_pattern():
    with pytest.raises(ValidationError):
        StyleDefinition(
            id="Custom Look",
            name="自定义",
            category=StyleCategory.CREATIVE,
            description="测试风格。",
            supported_scenes=(SceneLabel.OTHER,),
        )


def test_old_plan_payloads_still_parse_without_style_fields():
    style = get_style("cinematic")
    assert style is not None
    analysis = report(scene=SceneLabel.NIGHT)
    draft = _draft(analysis)
    generated = generate_recipe(
        recipe(),
        analysis,
        draft,
        PhotographerPreferences(),
        style,
        0.5,
    )
    response = PhotographerPlanResponse(
        plan_id=uuid4(),
        analysis_id=analysis.analysis_id,
        session_id=uuid4(),
        image_id=analysis.image.id,
        mode=PlannerMode.STYLE,
        is_mock=True,
        provider=ProviderInfo(
            name="mock",
            model="mock-planner",
            prompt_version="stage5/1",
        ),
        diagnosis=_draft(analysis).diagnosis,
        direction=_draft(analysis).direction,
        style_id=style.id,
        style_version=style.version,
        style_strength=0.5,
        recipe=generated.recipe,
        changes=generated.changes,
    )

    dumped = response.model_dump(mode="json", by_alias=True)
    assert dumped["styleId"] == "cinematic"
    assert dumped["styleVersion"] == "1.0"
    assert dumped["styleStrength"] == 0.5

    legacy = PhotographerPlanResponse.model_validate(dumped)
    assert legacy.style_id == "cinematic"
    assert legacy.style_strength == 0.5

    del dumped["styleId"], dumped["styleVersion"], dumped["styleStrength"]
    stored_before_styles = PhotographerPlanResponse.model_validate(dumped)

    assert stored_before_styles.style_id is None
    assert stored_before_styles.style_version is None
    assert stored_before_styles.style_strength is None
    assert stored_before_styles.recipe == response.recipe


def test_styles_route_lists_every_enabled_style(client: TestClient):
    response = client.get("/api/v1/ai/photographer/styles")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["styles"]) == len(STYLE_CATALOG)
    first = payload["styles"][0]
    assert set(first) == {
        "id",
        "version",
        "name",
        "category",
        "description",
        "supportedScenes",
        "defaultStrength",
        "envelope",
        "constraints",
        "engineStyle",
        "enabled",
    }


def test_styles_route_filters_by_category_and_scene(client: TestClient):
    creative = client.get("/api/v1/ai/photographer/styles", params={"category": "creative"})
    nature = client.get("/api/v1/ai/photographer/styles", params={"scene": "nature"})

    assert creative.status_code == 200
    assert creative.json()["styles"]
    assert all(style["category"] == "creative" for style in creative.json()["styles"])
    assert nature.status_code == 200
    assert all("nature" in style["supportedScenes"] for style in nature.json()["styles"])


def test_style_detail_route_returns_one_style(client: TestClient):
    response = client.get("/api/v1/ai/photographer/styles/monochrome")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "monochrome"
    assert response.json()["engineStyle"] == "documentary"


def test_style_detail_route_returns_404_for_unknown_style(client: TestClient):
    response = client.get("/api/v1/ai/photographer/styles/not_a_style")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "style_not_found"


def test_disabled_styles_are_hidden_unless_requested(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    enabled = get_style("film")
    assert enabled is not None
    disabled = enabled.model_copy(update={"enabled": False})
    catalog = tuple(disabled if style.id == enabled.id else style for style in STYLE_CATALOG)
    monkeypatch.setattr("app.photographer.service.STYLE_CATALOG", catalog)
    monkeypatch.setattr(
        "app.photographer.service.get_style",
        lambda style_id: disabled if style_id == "film" else get_style(style_id),
    )

    listed = client.get("/api/v1/ai/photographer/styles")
    with_disabled = client.get(
        "/api/v1/ai/photographer/styles",
        params={"include_disabled": "true"},
    )
    detail = client.get("/api/v1/ai/photographer/styles/film")

    assert "film" not in [style["id"] for style in listed.json()["styles"]]
    assert "film" in [style["id"] for style in with_disabled.json()["styles"]]
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "style_not_found"
