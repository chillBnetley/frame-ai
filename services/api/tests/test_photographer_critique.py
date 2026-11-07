from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.contracts import (
    ColorTemperature,
    ContrastLevel,
    ExposureQuality,
    IssueType,
    LightingDirection,
    LightingType,
    NoiseLevel,
    RecommendationCategory,
    SaturationLevel,
    SceneLabel,
    Severity,
    SharpnessQuality,
)
from app.models.analysis_report import (
    AnalysisReport,
    EngineInfo,
    LightingResult,
    TechnicalQualityResult,
)
from app.models.photographer import (
    CritiquePoint,
    CritiqueResponse,
    PhotographerPreferences,
)
from app.photographer.critique import build_critique
from app.photographer.validator import (
    RecipeValidationError,
    known_evidence_refs,
    validate_critique,
)
from tests.photographer_support import issue, measurements, report

_SUBJECT_NOUNS = ("人物", "建筑", "天空", "道路", "植物", "动物", "食物", "车辆")


def _all_points(critique: CritiqueResponse) -> tuple[CritiquePoint, ...]:
    return (
        *critique.strengths,
        *critique.technical.objective,
        *critique.technical.possible_issues,
        *critique.creative,
    )


def _spoken(critique: CritiqueResponse) -> str:
    """Every sentence the critique says out loud, in one searchable string."""
    return " ".join(
        [point.text for point in _all_points(critique)]
        + [item.text for item in critique.suggestions]
    )


def _clipped_report(**overrides: object) -> AnalysisReport:
    return report(
        issues=(
            issue(
                "issue_hl",
                issue_type=IssueType.HIGHLIGHT_CLIPPING,
                severity=Severity.HIGH,
                confidence=0.85,
                evidence="高光裁切占比 4.2%，集中在画面右上。",
            ),
        ),
        **overrides,  # type: ignore[arg-type]
    )


def test_critique_is_deterministic_for_the_same_report() -> None:
    subject = _clipped_report()
    first = build_critique(subject)
    second = build_critique(subject)
    assert first == second
    assert first.generated_by == "deterministic-rules"
    assert first.analysis_id == subject.analysis_id


@pytest.mark.parametrize(
    "scenario",
    (
        {},
        {"scene": SceneLabel.LANDSCAPE, "issues": ()},
        {"luminance_p50": 0.12, "luminance_std": 0.06, "sharpness": 0.05},
        {"saturation": SaturationLevel.HIGH, "saturation_mean": 0.78},
        {"temperature": ColorTemperature.WARM, "cast_temperature": 0.03},
        {"contrast": ContrastLevel.LOW},
        {"scene": SceneLabel.NIGHT, "noise_estimate": 0.62},
    ),
)
def test_every_conclusion_cites_evidence_present_in_the_report(scenario: dict) -> None:
    subject = report(**scenario)  # type: ignore[arg-type]
    critique = build_critique(subject)
    known = known_evidence_refs(subject)

    assert critique.technical.objective, "a completed report always yields technical facts"
    for point in _all_points(critique):
        assert point.evidence_refs, point.text
        for ref in point.evidence_refs:
            assert ref in known or ref.startswith("rule."), f"{point.text} cites {ref}"
    for suggestion in critique.suggestions:
        for ref in suggestion.evidence_refs:
            assert ref in known or ref.startswith("rule."), f"{suggestion.text} cites {ref}"


def test_critique_validates_against_its_own_report() -> None:
    subject = _clipped_report()
    validate_critique(subject, build_critique(subject))


def test_names_only_objects_the_report_actually_detects() -> None:
    landscape = report(scene=SceneLabel.LANDSCAPE).model_copy(
        update={"subjects": (), "regions": ()}
    )
    critique = build_critique(landscape)
    text = _spoken(critique)
    assert "人物" not in text
    assert all(noun not in text for noun in _SUBJECT_NOUNS)


def test_a_detected_person_may_be_named_and_is_cited_by_region() -> None:
    critique = build_critique(_clipped_report())
    strength = next(
        (point for point in critique.strengths if "人物" in point.text),
        None,
    )
    assert strength is not None
    assert "region_001" in strength.evidence_refs


def test_high_confidence_issue_is_reported_as_measurement_supported() -> None:
    critique = build_critique(_clipped_report())
    point = critique.technical.possible_issues[0]
    assert "高光溢出" in point.text
    assert "测量值支持该判断" in point.text
    assert "（高，置信度 85%）" in point.text


def test_low_confidence_issue_stays_advisory_and_is_never_certainty() -> None:
    subject = report(
        issues=(
            issue(
                "issue_cast",
                issue_type=IssueType.COLOR_CAST,
                severity=Severity.LOW,
                confidence=0.3,
                evidence="整体色偏指数轻微超出中性范围。",
            ),
        )
    )
    critique = build_critique(subject)
    point = next(
        item for item in critique.technical.possible_issues if item.text.startswith("整体色偏")
    )
    assert "置信度较低，仅供参考" in point.text
    assert "测量值支持该判断" not in point.text
    assert "issue_cast" in point.evidence_refs


def test_issue_sentences_never_stack_sentence_punctuation() -> None:
    subject = report(
        issues=(
            issue(
                "issue_cast",
                issue_type=IssueType.COLOR_CAST,
                severity=Severity.MEDIUM,
                confidence=0.85,
                evidence="画面存在色彩偏移：色温偏差 +100.0（偏暖）。",
            ),
            issue(
                "issue_detail",
                issue_type=IssueType.LOW_DETAIL,
                severity=Severity.LOW,
                confidence=0.3,
                evidence="清晰度指标 0.000 偏低。",
            ),
        )
    )
    spoken = _spoken(build_critique(subject))
    for pair in ("。。", "。；", "；。", "；；"):
        assert pair not in spoken


def test_creative_notes_are_always_marked_subjective() -> None:
    critique = build_critique(_clipped_report())
    assert critique.creative
    assert all(point.subjective is True for point in critique.creative)
    assert all(point.evidence_refs for point in critique.creative)


def test_a_low_key_frame_surfaces_the_creative_choice_before_the_defect() -> None:
    subject = report(
        luminance_p50=0.1,
        luminance_std=0.05,
        luminance_p1=0.0,
        shadows_pct=6.0,
        issues=(
            issue(
                "issue_under",
                issue_type=IssueType.UNDEREXPOSURE,
                severity=Severity.MEDIUM,
                confidence=0.9,
                evidence="中位亮度 0.10，整体偏暗。",
            ),
        ),
    )
    critique = build_critique(subject)
    assert any("暗" in point.text for point in critique.creative)
    problem = next(
        point for point in critique.technical.possible_issues if point.text.startswith("整体偏暗")
    )
    assert "可能是刻意的创作选择" in problem.text


def test_suggestions_carry_a_patch_only_when_parameters_are_involved() -> None:
    critique = build_critique(_clipped_report())
    highlight = next(
        item for item in critique.suggestions if item.category is RecommendationCategory.EXPOSURE
    )
    assert highlight.recipe_patch is not None
    assert highlight.recipe_patch.highlights is not None
    assert highlight.recipe_patch.highlights < 0
    assert highlight.recipe_patch.shadows in (None, 0)

    composition = build_critique(
        report(
            issues=(
                issue(
                    "issue_place",
                    issue_type=IssueType.SUBJECT_PLACEMENT,
                    severity=Severity.MEDIUM,
                    confidence=0.8,
                    evidence="主体位于画面右下边缘，视线空间不足。",
                ),
            )
        )
    )
    placement = next(
        item
        for item in composition.suggestions
        if item.category is RecommendationCategory.COMPOSITION
    )
    assert placement.recipe_patch is None
    assert "issue_place" in placement.evidence_refs


def test_preferences_shrink_the_suggested_patch() -> None:
    subject = _clipped_report()
    default = build_critique(subject).suggestions[0]
    gentle = build_critique(
        subject,
        PhotographerPreferences(naturalness=1.0, adjustment_strength=0.2),
    ).suggestions[0]
    assert default.recipe_patch is not None and gentle.recipe_patch is not None
    assert abs(gentle.recipe_patch.highlights or 0.0) <= abs(default.recipe_patch.highlights or 0.0)
    assert abs(gentle.recipe_patch.highlights or 0.0) < abs(default.recipe_patch.highlights or 0.0)


def test_zero_strength_produces_advice_without_a_patch() -> None:
    critique = build_critique(
        _clipped_report(),
        PhotographerPreferences(adjustment_strength=0.0),
    )
    assert critique.suggestions
    assert all(item.recipe_patch is None for item in critique.suggestions)


def test_mock_reports_are_labelled_and_real_reports_are_not() -> None:
    subject = _clipped_report()
    mock_critique = build_critique(subject)
    assert mock_critique.is_mock is True
    assert any("模拟视觉引擎" in note for note in mock_critique.limitations)

    real_engine = EngineInfo(
        vision_provider="openai",
        vision_model="gpt-vision",
        decision_provider="openai",
        decision_model="gpt-decision",
        prompt_version="stage3/2",
        analyzer_version="frame-analyzer/1",
        is_mock=False,
    )
    real_critique = build_critique(subject.model_copy(update={"engine": real_engine}))
    assert real_critique.is_mock is False
    assert not any("模拟视觉引擎" in note for note in real_critique.limitations)


def test_report_limitations_travel_with_the_critique() -> None:
    subject = _clipped_report().model_copy(
        update={"limitations": ("逆光场景的高光判定阈值已放宽。",)}
    )
    critique = build_critique(subject)
    assert "分析限制：逆光场景的高光判定阈值已放宽。" in critique.limitations
    assert any("deterministic-rules" in note for note in critique.limitations)


def test_collections_stay_inside_the_documented_limits() -> None:
    subject = report(
        issues=tuple(
            issue(
                f"issue_{index:03d}",
                issue_type=IssueType.HIGHLIGHT_CLIPPING,
                severity=Severity.HIGH,
                confidence=0.9,
            )
            for index in range(20)
        )
    )
    critique = build_critique(subject)
    assert len(critique.strengths) <= 8
    assert len(critique.technical.objective) <= 8
    assert len(critique.technical.possible_issues) <= 8
    assert len(critique.creative) <= 8
    assert len(critique.suggestions) <= 8
    assert len(critique.limitations) <= 8


def test_lighting_and_colour_characteristics_come_from_the_report() -> None:
    critique = build_critique(
        report(
            scene=SceneLabel.STREET,
            temperature=ColorTemperature.COOL,
            contrast=ContrastLevel.HIGH,
        )
    )
    text = " ".join(point.text for point in critique.technical.objective)
    assert "光线特点" in text
    assert "侧面光" in text
    assert "色彩特点" in text
    assert "偏冷" in text
    assert "街拍" in text


def test_validator_rejects_a_point_that_invents_evidence() -> None:
    subject = _clipped_report()
    critique = build_critique(subject)
    poisoned = critique.model_copy(
        update={"strengths": (CritiquePoint(text="凭空结论。", evidence_refs=("region_ghost",)),)}
    )
    with pytest.raises(RecipeValidationError) as excinfo:
        validate_critique(subject, poisoned)
    assert "unknown evidence" in str(excinfo.value)


def test_validator_rejects_an_objective_creative_claim() -> None:
    subject = _clipped_report()
    critique = build_critique(subject)
    objectified = critique.model_copy(
        update={
            "creative": (
                *(point for point in critique.creative if point is not critique.creative[0]),
                critique.creative[0].model_copy(update={"subjective": False}),
            )
        }
    )
    with pytest.raises(RecipeValidationError) as excinfo:
        validate_critique(subject, objectified)
    assert "must be marked subjective" in str(excinfo.value)


def test_validator_rejects_an_empty_recipe_patch() -> None:
    subject = _clipped_report()
    critique = build_critique(subject)
    suggestion = next(item for item in critique.suggestions if item.recipe_patch is not None)
    emptied = critique.model_copy(
        update={
            "suggestions": (
                *(item for item in critique.suggestions if item is not suggestion),
                suggestion.model_copy(update={"recipe_patch": suggestion.recipe_patch.__class__()}),
            )
        }
    )
    with pytest.raises(RecipeValidationError) as excinfo:
        validate_critique(subject, emptied)
    assert "empty recipePatch" in str(excinfo.value)


def test_critique_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CritiqueResponse.model_validate(
            {
                "analysisId": "11111111-1111-4111-8111-111111111111",
                "isMock": True,
                "strengths": [],
                "unexpected": True,
            }
        )


def test_backlight_direction_is_named_only_when_the_report_says_so() -> None:
    subject = _clipped_report().model_copy(
        update={
            "lighting": LightingResult(
                direction=LightingDirection.BACK,
                type=LightingType.NATURAL,
                contrast=ContrastLevel.MODERATE,
                confidence=0.6,
            )
        }
    )
    critique = build_critique(subject)
    backlit = [point for point in critique.creative if "逆光" in point.text]
    assert backlit
    assert all("lighting.direction" in point.evidence_refs for point in backlit)

    neutral = build_critique(_clipped_report())
    assert not any("逆光" in point.text for point in neutral.creative)


def test_noise_level_facts_use_the_measured_value() -> None:
    subject = _clipped_report().model_copy(
        update={
            "technical_quality": TechnicalQualityResult(
                exposure=ExposureQuality.BALANCED,
                sharpness=SharpnessQuality.SOFT,
                noise=NoiseLevel.HIGH,
                confidence=0.6,
            )
        }
    )
    loud = subject.model_copy(
        update={
            "measurements": measurements(noise_estimate=0.62, sharpness=0.04),
        }
    )
    text = " ".join(point.text for point in build_critique(loud).technical.objective)
    assert "噪声估计 0.62" in text
    assert "偏高" in text
    assert "偏软" in text
