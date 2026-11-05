from __future__ import annotations

from dataclasses import dataclass

from app.ai.contracts import (
    DecisionResult,
    IssueCandidate,
    IssueSelection,
    IssueType,
    Priority,
    RecommendationCategory,
    RecommendationResult,
    Severity,
)

MAX_SEVERITY_STEP = 1
MAX_CONFIDENCE_BOOST = 0.10
MIN_RECOMMENDATION_LENGTH = 8
RECOMMENDATION_TEXT_LIMIT = 500
UNSELECTED_CANDIDATE_LIMIT = 500

_SEVERITY_RANK = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
_PRIORITY_BY_SEVERITY = {
    Severity.HIGH: Priority.HIGH,
    Severity.MEDIUM: Priority.MEDIUM,
    Severity.LOW: Priority.LOW,
}

BANNED_GENERIC_PHRASES = (
    "更通透",
    "更有层次",
    "提升质感",
    "更加完美",
    "注意构图",
    "优化画面",
    "改善画面",
)

ISSUE_GUIDANCE: dict[IssueType, tuple[RecommendationCategory, str]] = {
    IssueType.OVEREXPOSURE: (
        RecommendationCategory.EXPOSURE,
        "降低整体曝光，并在高光区域使用高光恢复，避免继续丢失亮部细节。",
    ),
    IssueType.UNDEREXPOSURE: (
        RecommendationCategory.EXPOSURE,
        "提高整体曝光或针对暗部做适度提亮，同时保留高光不过曝。",
    ),
    IssueType.HIGHLIGHT_CLIPPING: (
        RecommendationCategory.EXPOSURE,
        "降低曝光或使用高光恢复，优先保留亮部纹理与层次。",
    ),
    IssueType.SHADOW_CLIPPING: (
        RecommendationCategory.EXPOSURE,
        "提升阴影细节或适度补光，避免暗部继续压黑。",
    ),
    IssueType.SUBJECT_UNDEREXPOSURE: (
        RecommendationCategory.LIGHTING,
        "对主体区域进行局部提亮，保留背景高光并改善主体与背景的明暗平衡。",
    ),
    IssueType.BACKGROUND_OVEREXPOSURE: (
        RecommendationCategory.LIGHTING,
        "压暗背景或降低背景高光，突出主体并恢复背景细节。",
    ),
    IssueType.COLOR_CAST: (
        RecommendationCategory.COLOR,
        "根据色偏方向校正白平衡，恢复中性色彩后再调整整体色调。",
    ),
    IssueType.TEMPERATURE_MISMATCH: (
        RecommendationCategory.COLOR,
        "调整色温使其与场景光线一致，避免冷暖冲突。",
    ),
    IssueType.SATURATION_ISSUE: (
        RecommendationCategory.COLOR,
        "调整整体或局部饱和度，保留自然的色彩层次。",
    ),
    IssueType.COLOR_HIERARCHY_ISSUE: (
        RecommendationCategory.COLOR,
        "调整主色与辅色的明度关系，建立更清晰的色彩层次。",
    ),
    IssueType.SUBJECT_PLACEMENT: (
        RecommendationCategory.COMPOSITION,
        "重新取景或裁剪，将主体移离画面边缘并保留完整轮廓。",
    ),
    IssueType.BALANCE_ISSUE: (
        RecommendationCategory.COMPOSITION,
        "调整构图或裁剪，使画面视觉重心回到可控位置。",
    ),
    IssueType.NEGATIVE_SPACE_ISSUE: (
        RecommendationCategory.COMPOSITION,
        "简化背景或调整取景，为主体留出足够的呼吸空间。",
    ),
    IssueType.HORIZON_TILT: (
        RecommendationCategory.COMPOSITION,
        "旋转或裁剪校正地平线，使其保持水平。",
    ),
    IssueType.FOCUS_ISSUE: (
        RecommendationCategory.SHARPNESS,
        "重新对焦主体，必要时缩小光圈或使用三脚架稳定拍摄。",
    ),
    IssueType.MOTION_BLUR: (
        RecommendationCategory.SHARPNESS,
        "缩短快门时间或使用三脚架，减少主体或相机的运动模糊。",
    ),
    IssueType.HIGH_NOISE: (
        RecommendationCategory.SHARPNESS,
        "降低 ISO 或增加曝光时间，必要时在后期做适度降噪。",
    ),
    IssueType.LOW_DETAIL: (
        RecommendationCategory.SHARPNESS,
        "检查镜头与对焦，避免过度降噪，并在后期做适度锐化。",
    ),
    IssueType.HARSH_CONTRAST: (
        RecommendationCategory.LIGHTING,
        "平衡高光与阴影，降低过强反差并保留两端细节。",
    ),
    IssueType.FLAT_LIGHTING: (
        RecommendationCategory.LIGHTING,
        "引入方向光或增加局部对比，让主体与背景分离。",
    ),
}

ISSUE_CATEGORIES: dict[IssueType, frozenset[RecommendationCategory]] = {
    IssueType.OVEREXPOSURE: frozenset(
        {RecommendationCategory.EXPOSURE, RecommendationCategory.LIGHTING}
    ),
    IssueType.UNDEREXPOSURE: frozenset(
        {RecommendationCategory.EXPOSURE, RecommendationCategory.LIGHTING}
    ),
    IssueType.HIGHLIGHT_CLIPPING: frozenset(
        {RecommendationCategory.EXPOSURE, RecommendationCategory.LIGHTING}
    ),
    IssueType.SHADOW_CLIPPING: frozenset(
        {RecommendationCategory.EXPOSURE, RecommendationCategory.LIGHTING}
    ),
    IssueType.SUBJECT_UNDEREXPOSURE: frozenset(
        {RecommendationCategory.EXPOSURE, RecommendationCategory.LIGHTING}
    ),
    IssueType.BACKGROUND_OVEREXPOSURE: frozenset(
        {RecommendationCategory.EXPOSURE, RecommendationCategory.LIGHTING}
    ),
    IssueType.COLOR_CAST: frozenset({RecommendationCategory.COLOR}),
    IssueType.TEMPERATURE_MISMATCH: frozenset({RecommendationCategory.COLOR}),
    IssueType.SATURATION_ISSUE: frozenset({RecommendationCategory.COLOR}),
    IssueType.COLOR_HIERARCHY_ISSUE: frozenset({RecommendationCategory.COLOR}),
    IssueType.SUBJECT_PLACEMENT: frozenset({RecommendationCategory.COMPOSITION}),
    IssueType.BALANCE_ISSUE: frozenset({RecommendationCategory.COMPOSITION}),
    IssueType.NEGATIVE_SPACE_ISSUE: frozenset({RecommendationCategory.COMPOSITION}),
    IssueType.HORIZON_TILT: frozenset({RecommendationCategory.COMPOSITION}),
    IssueType.FOCUS_ISSUE: frozenset({RecommendationCategory.SHARPNESS}),
    IssueType.MOTION_BLUR: frozenset({RecommendationCategory.SHARPNESS}),
    IssueType.HIGH_NOISE: frozenset({RecommendationCategory.SHARPNESS}),
    IssueType.LOW_DETAIL: frozenset({RecommendationCategory.SHARPNESS}),
    IssueType.HARSH_CONTRAST: frozenset(
        {RecommendationCategory.LIGHTING, RecommendationCategory.EXPOSURE}
    ),
    IssueType.FLAT_LIGHTING: frozenset(
        {RecommendationCategory.LIGHTING, RecommendationCategory.EXPOSURE}
    ),
}


class DecisionValidationError(ValueError):
    """Raised when a decision provider exceeds its authority."""


@dataclass(frozen=True, slots=True)
class ValidatedDecision:
    selections: tuple[IssueSelection, ...]
    recommendations: tuple[RecommendationResult, ...]
    limitations: tuple[str, ...]


def validate_decision(
    decision: DecisionResult,
    candidates: tuple[IssueCandidate, ...],
    region_ids: tuple[str, ...],
) -> ValidatedDecision:
    by_id = {candidate.id: candidate for candidate in candidates}
    known_regions = set(region_ids)
    selections = _validate_selections(decision.issues, by_id, known_regions)

    for recommendation in decision.recommendations:
        if not set(recommendation.target_regions) <= known_regions:
            raise DecisionValidationError("The decision referenced a region that does not exist.")

    if _recommendations_are_valid(
        decision.recommendations,
        selections,
        by_id,
        known_regions,
    ):
        recommendations = decision.recommendations
    else:
        recommendations = fallback_recommendations(selections, by_id)

    limitations = list(decision.limitations)
    unselected = unselected_candidates_limitation(candidates, selections)
    if unselected:
        limitations.append(unselected)

    return ValidatedDecision(
        selections=selections,
        recommendations=recommendations,
        limitations=tuple(_dedupe(limitations)),
    )


def fallback_recommendations(
    selections: tuple[IssueSelection, ...],
    by_id: dict[str, IssueCandidate],
) -> tuple[RecommendationResult, ...]:
    recommendations: list[RecommendationResult] = []
    for selection in selections:
        candidate = by_id[selection.candidate_id]
        category, action = ISSUE_GUIDANCE[candidate.type]
        target_regions = selection.region_ids or candidate.region_ids
        text = f"{action}依据：{candidate.evidence}"
        recommendations.append(
            RecommendationResult(
                category=category,
                priority=_PRIORITY_BY_SEVERITY[selection.severity],
                description=text[:RECOMMENDATION_TEXT_LIMIT],
                target_regions=target_regions,
            )
        )
    return tuple(recommendations)


def unselected_candidates_limitation(
    candidates: tuple[IssueCandidate, ...],
    selections: tuple[IssueSelection, ...],
) -> str:
    selected = {selection.candidate_id for selection in selections}
    missing = [candidate for candidate in candidates if candidate.id not in selected]
    if not missing:
        return ""
    labels = "、".join(f"{candidate.type.value}({candidate.id})" for candidate in missing)
    text = f"以下候选问题未纳入主要问题：{labels}。"
    if len(text) > UNSELECTED_CANDIDATE_LIMIT:
        text = text[: UNSELECTED_CANDIDATE_LIMIT - 1] + "…"
    return text


def _validate_selections(
    issues: tuple[IssueSelection, ...],
    by_id: dict[str, IssueCandidate],
    known_regions: set[str],
) -> tuple[IssueSelection, ...]:
    seen: set[str] = set()
    validated: list[IssueSelection] = []
    for selection in issues:
        candidate = by_id.get(selection.candidate_id)
        if candidate is None:
            raise DecisionValidationError("The decision referenced an unknown issue candidate.")
        if selection.candidate_id in seen:
            raise DecisionValidationError(
                "The decision selected the same issue candidate more than once."
            )
        seen.add(selection.candidate_id)

        step = abs(_SEVERITY_RANK[selection.severity] - _SEVERITY_RANK[candidate.severity])
        if step > MAX_SEVERITY_STEP:
            raise DecisionValidationError(
                "The decision changed the issue severity beyond the allowed range."
            )
        if selection.confidence > candidate.confidence + MAX_CONFIDENCE_BOOST + 1e-9:
            raise DecisionValidationError("The decision confidence exceeds the candidate evidence.")

        region_ids = _unique(selection.region_ids)
        if not set(region_ids) <= known_regions:
            raise DecisionValidationError("The decision referenced a region that does not exist.")
        if not set(region_ids) <= set(candidate.region_ids):
            raise DecisionValidationError(
                "The decision attached an issue to a region without candidate evidence."
            )

        validated.append(
            IssueSelection(
                candidate_id=selection.candidate_id,
                severity=selection.severity,
                confidence=selection.confidence,
                evidence=selection.evidence,
                region_ids=region_ids,
            )
        )
    return tuple(validated)


def _recommendations_are_valid(
    recommendations: tuple[RecommendationResult, ...],
    selections: tuple[IssueSelection, ...],
    by_id: dict[str, IssueCandidate],
    known_regions: set[str],
) -> bool:
    if selections and not recommendations:
        return False
    for recommendation in recommendations:
        if not _recommendation_text_ok(recommendation.description):
            return False
        if not set(recommendation.target_regions) <= known_regions:
            return False
        if len(set(recommendation.target_regions)) != len(recommendation.target_regions):
            return False
        if not any(
            _recommendation_matches(recommendation, selection, by_id[selection.candidate_id])
            for selection in selections
        ):
            return False
    return all(
        any(
            _recommendation_matches(rec, selection, by_id[selection.candidate_id])
            for rec in recommendations
        )
        for selection in selections
    )


def _recommendation_text_ok(description: str) -> bool:
    text = description.strip()
    if len(text) < MIN_RECOMMENDATION_LENGTH:
        return False
    return not any(phrase in text for phrase in BANNED_GENERIC_PHRASES)


def _recommendation_matches(
    recommendation: RecommendationResult,
    selection: IssueSelection,
    candidate: IssueCandidate,
) -> bool:
    if recommendation.category not in ISSUE_CATEGORIES[candidate.type]:
        return False
    if not selection.region_ids:
        return True
    if not recommendation.target_regions:
        return True
    return bool(set(recommendation.target_regions) & set(selection.region_ids))


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


__all__ = [
    "BANNED_GENERIC_PHRASES",
    "DecisionValidationError",
    "ISSUE_CATEGORIES",
    "ISSUE_GUIDANCE",
    "ValidatedDecision",
    "fallback_recommendations",
    "unselected_candidates_limitation",
    "validate_decision",
]
