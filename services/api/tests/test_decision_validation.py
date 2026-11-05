from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.contracts import (
    DecisionResult,
    IssueSelection,
    IssueType,
    RecommendationCategory,
    Severity,
)
from app.analysis.decision_validation import (
    DecisionValidationError,
    validate_decision,
)
from tests.ai_support import decision_payload, issue_candidate

VISION_REGIONS = ("region_001", "region_002")


def _candidate(
    candidate_id: str = "c1",
    *,
    severity: Severity = Severity.MEDIUM,
    confidence: float = 0.7,
    region_ids: tuple[str, ...] = ("region_001",),
) -> object:
    return issue_candidate(
        id=candidate_id,
        severity=severity,
        confidence=confidence,
        region_ids=region_ids,
    )


def _selection(
    candidate_id: str = "c1",
    *,
    severity: Severity = Severity.MEDIUM,
    confidence: float = 0.7,
    region_ids: tuple[str, ...] = ("region_001",),
    evidence: str = "中位亮度 0.12，低于阈值 0.18。",
) -> IssueSelection:
    return IssueSelection(
        candidate_id=candidate_id,
        severity=severity,
        confidence=confidence,
        evidence=evidence,
        region_ids=region_ids,
    )


def _decision(
    *,
    issues: tuple[IssueSelection, ...] = (),
    recommendations: tuple[dict[str, object], ...] = (),
    limitations: tuple[str, ...] = (),
) -> DecisionResult:
    payload = decision_payload()
    payload["issues"] = [
        {
            "candidateId": item.candidate_id,
            "severity": item.severity.value,
            "confidence": item.confidence,
            "evidence": item.evidence,
            "regionIds": list(item.region_ids),
        }
        for item in issues
    ]
    payload["recommendations"] = list(recommendations)
    payload["limitations"] = list(limitations)
    return DecisionResult.model_validate(payload)


def _recommendation(
    *,
    category: str = "exposure",
    description: str = "提高曝光补偿，并检查暗部细节。",
    target_regions: tuple[str, ...] = ("region_001",),
    priority: str = "medium",
) -> dict[str, object]:
    return {
        "category": category,
        "priority": priority,
        "description": description,
        "targetRegions": list(target_regions),
    }


def test_valid_decision_is_accepted_and_omitted_candidates_are_reported():
    candidates = (_candidate("c1"), _candidate("c2", region_ids=("region_002",)))
    decision = _decision(
        issues=(_selection("c1"),),
        recommendations=(_recommendation(),),
        limitations=("仅依据给定测量。",),
    )

    validated = validate_decision(decision, candidates, VISION_REGIONS)

    assert len(validated.selections) == 1
    assert validated.recommendations[0].target_regions == ("region_001",)
    assert "仅依据给定测量。" in validated.limitations
    assert any(
        "未纳入主要问题" in limitation and "c2" in limitation
        for limitation in validated.limitations
    )


def test_unknown_candidate_is_rejected():
    with pytest.raises(DecisionValidationError):
        validate_decision(
            _decision(issues=(_selection("missing"),)),
            (_candidate("c1"),),
            VISION_REGIONS,
        )


def test_duplicate_candidate_selection_is_rejected():
    decision = _decision(issues=(_selection("c1"), _selection("c1")))
    with pytest.raises(DecisionValidationError):
        validate_decision(decision, (_candidate("c1"),), VISION_REGIONS)


def test_severity_can_only_change_one_step():
    candidates = (_candidate("c1", severity=Severity.LOW),)
    with pytest.raises(DecisionValidationError):
        validate_decision(
            _decision(issues=(_selection("c1", severity=Severity.HIGH),)),
            candidates,
            VISION_REGIONS,
        )

    validated = validate_decision(
        _decision(issues=(_selection("c1", severity=Severity.MEDIUM),)),
        candidates,
        VISION_REGIONS,
    )
    assert validated.selections[0].severity is Severity.MEDIUM


def test_confidence_cannot_exceed_candidate_evidence():
    candidates = (_candidate("c1", confidence=0.6),)
    with pytest.raises(DecisionValidationError):
        validate_decision(
            _decision(issues=(_selection("c1", confidence=0.75),)),
            candidates,
            VISION_REGIONS,
        )


def test_dangling_region_in_issue_is_rejected():
    with pytest.raises(DecisionValidationError):
        validate_decision(
            _decision(issues=(_selection("c1", region_ids=("region_999",)),)),
            (_candidate("c1"),),
            VISION_REGIONS,
        )


def test_issue_region_must_have_candidate_evidence():
    candidates = (_candidate("c1", region_ids=("region_001",)),)
    with pytest.raises(DecisionValidationError):
        validate_decision(
            _decision(issues=(_selection("c1", region_ids=("region_002",)),)),
            candidates,
            VISION_REGIONS,
        )


def test_dangling_region_in_recommendation_is_rejected():
    decision = _decision(
        issues=(_selection("c1"),),
        recommendations=(_recommendation(target_regions=("region_999",)),),
    )
    with pytest.raises(DecisionValidationError):
        validate_decision(decision, (_candidate("c1"),), VISION_REGIONS)


def test_blank_issue_evidence_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        _selection("c1", evidence="   ")


def test_generic_recommendation_falls_back_to_deterministic_template():
    decision = _decision(
        issues=(_selection("c1"),),
        recommendations=(_recommendation(description="让画面更通透。"),),
    )

    validated = validate_decision(decision, (_candidate("c1"),), VISION_REGIONS)

    description = validated.recommendations[0].description
    assert "更通透" not in description
    assert "提高整体曝光" in description or "提亮" in description
    assert validated.recommendations[0].category is RecommendationCategory.EXPOSURE
    assert validated.recommendations[0].priority.value == "medium"


def test_wrong_category_recommendation_falls_back():
    decision = _decision(
        issues=(_selection("c1"),),
        recommendations=(
            _recommendation(category="composition", description="裁剪主体周围区域。"),
        ),
    )

    validated = validate_decision(decision, (_candidate("c1"),), VISION_REGIONS)

    assert validated.recommendations[0].category is RecommendationCategory.EXPOSURE


def test_missing_recommendations_fall_back_for_each_issue():
    decision = _decision(issues=(_selection("c1"),))

    validated = validate_decision(decision, (_candidate("c1"),), VISION_REGIONS)

    assert len(validated.recommendations) == 1
    assert validated.recommendations[0].category is RecommendationCategory.EXPOSURE


def test_unrelated_extra_recommendation_triggers_fallback():
    decision = _decision(
        issues=(_selection("c1"),),
        recommendations=(
            _recommendation(),
            _recommendation(
                category="sharpness",
                description="使用三脚架稳定相机并重新对焦。",
            ),
        ),
    )

    validated = validate_decision(decision, (_candidate("c1"),), VISION_REGIONS)

    assert len(validated.recommendations) == 1


def test_fallback_uses_issue_specific_guidance():
    candidates = (
        issue_candidate(
            id="c_noise",
            type=IssueType.HIGH_NOISE,
            severity=Severity.HIGH,
            confidence=0.8,
            region_ids=(),
        ),
    )
    decision = _decision(
        issues=(_selection("c_noise", severity=Severity.HIGH, confidence=0.8, region_ids=()),)
    )

    validated = validate_decision(decision, candidates, ())

    recommendation = validated.recommendations[0]
    assert recommendation.category is RecommendationCategory.SHARPNESS
    assert recommendation.priority.value == "high"
    assert "ISO" in recommendation.description
