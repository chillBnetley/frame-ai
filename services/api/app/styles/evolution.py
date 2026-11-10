"""Deterministic personal-style evolution from confirmed feedback.

The engine aggregates explicit personal-style feedback into bounded, capped
adjustments instead of treating a single click as a stable preference. Numeric
targets move only within fixed caps, protection constraints are unioned (never
removed), and confidence/strength shift conservatively. No provider call is
involved, so the candidate preview is instant and reproducible; free-text
modification opinions are recorded as context and handled by the existing
natural-language refine path.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

from app.models.personal_style import (
    PERSONAL_TARGET_FIELDS,
    PersonalAvoidEffect,
    PersonalStyleDefinition,
    PersonalStyleProfile,
)
from app.models.photographer import DirectionConstraint
from app.models.style_evolution import (
    FEEDBACK_TYPE_LABELS,
    StyleEvolutionAdjustment,
    StyleFeedbackType,
)

_T = TypeVar("_T")

_AVOID_TO_CONSTRAINT: dict[PersonalAvoidEffect, DirectionConstraint] = {
    PersonalAvoidEffect.OVERSATURATED: DirectionConstraint.AVOID_EXTREME_SATURATION,
    PersonalAvoidEffect.CRUSHED_BLACKS: DirectionConstraint.PRESERVE_SHADOW_DETAIL,
    PersonalAvoidEffect.CLIPPED_HIGHLIGHTS: DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
    PersonalAvoidEffect.COLOR_CAST: DirectionConstraint.AVOID_COLOR_CAST,
    PersonalAvoidEffect.UNNATURAL_SKIN: DirectionConstraint.PRESERVE_SKIN_TONE,
    PersonalAvoidEffect.HEAVY_FILTER: DirectionConstraint.NATURAL_LOOK,
    PersonalAvoidEffect.OVER_SHARPENED: DirectionConstraint.NATURAL_LOOK,
    PersonalAvoidEffect.FLAT_CONTRAST: DirectionConstraint.AVOID_EXTREME_CONTRAST,
}

_TARGET_LABELS: dict[str, str] = {
    "exposureEv": "曝光",
    "contrast": "对比度",
    "highlights": "高光",
    "shadows": "暗部",
    "whites": "白色",
    "blacks": "黑色",
    "temperature": "色温",
    "tint": "色调",
    "saturation": "饱和度",
    "vibrance": "自然饱和度",
    "clarity": "清晰度",
    "sharpen": "锐化",
    "denoise": "降噪",
    "vignette": "暗角",
    "grain": "颗粒",
}

_CONSTRAINT_LABELS: dict[DirectionConstraint, str] = {
    DirectionConstraint.PRESERVE_SKIN_TONE: "保护肤色",
    DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL: "保护高光细节",
    DirectionConstraint.PRESERVE_SHADOW_DETAIL: "保护暗部细节",
    DirectionConstraint.AVOID_EXTREME_SATURATION: "避免极端饱和度",
    DirectionConstraint.AVOID_EXTREME_CONTRAST: "避免极端反差",
    DirectionConstraint.NATURAL_LOOK: "保持自然观感",
    DirectionConstraint.AVOID_COLOR_CAST: "避免明显偏色",
}


@dataclass(frozen=True, slots=True)
class EvolutionOutcome:
    profile: PersonalStyleProfile
    definition: PersonalStyleDefinition
    reason: str
    summary: str
    adjustments: tuple[StyleEvolutionAdjustment, ...]
    limitations: tuple[str, ...]
    feedback_count: int


def _cap(text: str) -> str:
    cleaned = text.strip()
    return (cleaned or "—")[:500]


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _shift(targets: dict[str, float], field: str, delta: float) -> None:
    targets[field] = targets.get(field, 0.0) + delta


def _toward_zero(targets: dict[str, float], field: str, amount: float) -> None:
    current = targets.get(field, 0.0)
    if current > 0.0:
        targets[field] = max(0.0, current - amount)
    elif current < 0.0:
        targets[field] = min(0.0, current + amount)


def _add_unique(items: list[_T], value: _T) -> bool:
    if value in items:
        return False
    items.append(value)
    return True


def evolve_profile(
    base: PersonalStyleProfile,
    base_definition: PersonalStyleDefinition,
    feedbacks: Sequence[StyleFeedbackType],
    *,
    notes: Sequence[str] = (),
    note: str | None = None,
    version: str,
) -> EvolutionOutcome:
    """Turn confirmed personal-style feedback into a bounded candidate version."""

    counts = Counter(feedbacks)
    feedback_count = sum(counts.values())
    targets = {field: float(value) for field, value in base.personal.targets.items()}
    base_targets = dict(base.personal.targets)
    confidence = float(base.personal.confidence)
    strength = float(base.default_strength)
    protected = list(base.personal.protected)
    avoid = list(base.personal.avoid)
    base_protected = set(base.personal.protected)
    base_avoid = set(base.personal.avoid)
    reasons: list[str] = []
    limitations: list[str] = []

    def protect(constraint: DirectionConstraint) -> None:
        _add_unique(protected, constraint)

    def evade(effect: PersonalAvoidEffect) -> None:
        _add_unique(avoid, effect)

    for feedback_type, count in counts.items():
        label = FEEDBACK_TYPE_LABELS[feedback_type]
        if feedback_type is StyleFeedbackType.LIKE_RESULT:
            confidence = min(0.95, confidence + 0.05 * count)
            reasons.append(f"{label}×{count}：提升置信度，保持现有方向")
        elif feedback_type is StyleFeedbackType.DISLIKE_RESULT:
            strength = max(0.2, strength - 0.05 * count)
            confidence = max(0.1, confidence - 0.03 * count)
            reasons.append(f"{label}×{count}：保守降低默认强度与置信度")
        elif feedback_type is StyleFeedbackType.COLOR_TOO_STRONG:
            _shift(targets, "saturation", -min(4.0 * count, 16.0))
            _shift(targets, "vibrance", -min(2.0 * count, 8.0))
            evade(PersonalAvoidEffect.OVERSATURATED)
            protect(DirectionConstraint.AVOID_EXTREME_SATURATION)
            reasons.append(f"{label}×{count}：降低饱和度并避免极端饱和")
        elif feedback_type is StyleFeedbackType.CONTRAST_TOO_STRONG:
            _shift(targets, "contrast", -min(4.0 * count, 16.0))
            evade(PersonalAvoidEffect.FLAT_CONTRAST)
            protect(DirectionConstraint.AVOID_EXTREME_CONTRAST)
            reasons.append(f"{label}×{count}：降低反差并避免极端反差")
        elif feedback_type is StyleFeedbackType.SHADOWS_TOO_DARK:
            _shift(targets, "shadows", min(4.0 * count, 16.0))
            evade(PersonalAvoidEffect.CRUSHED_BLACKS)
            protect(DirectionConstraint.PRESERVE_SHADOW_DETAIL)
            reasons.append(f"{label}×{count}：提亮暗部并保护暗部细节")
        elif feedback_type is StyleFeedbackType.SKIN_UNNATURAL:
            evade(PersonalAvoidEffect.UNNATURAL_SKIN)
            protect(DirectionConstraint.PRESERVE_SKIN_TONE)
            _toward_zero(targets, "temperature", min(2.0 * count, 6.0))
            _toward_zero(targets, "tint", min(2.0 * count, 6.0))
            reasons.append(f"{label}×{count}：保护肤色并把色温/色调回退中性")
        elif feedback_type is StyleFeedbackType.STYLE_SUBTLE:
            magnitude = min(2.0 * count, 6.0)
            active = [field for field, value in targets.items() if abs(value) >= 0.5]
            for field in active:
                sign = 1.0 if targets[field] > 0 else -1.0
                _shift(targets, field, sign * magnitude)
            strength = min(0.85, strength + 0.03 * count)
            reasons.append(f"{label}×{count}：增强已有风格方向并适度提高强度")
            if not active:
                limitations.append("当前风格没有明确数值方向，风格不明显反馈仅提高默认强度。")
        elif feedback_type is StyleFeedbackType.STYLE_OVERDONE:
            factor = 1.0 - min(0.15 * count, 0.45)
            for field in list(targets):
                targets[field] *= factor
            strength = max(0.2, strength - 0.05 * count)
            evade(PersonalAvoidEffect.HEAVY_FILTER)
            protect(DirectionConstraint.NATURAL_LOOK)
            reasons.append(f"{label}×{count}：把风格数值向中性收敛并降低强度")
        elif feedback_type is StyleFeedbackType.KEEP_ORIGINAL:
            amount = min(3.0 * count, 9.0)
            for field in ("clarity", "sharpen", "grain"):
                _toward_zero(targets, field, amount)
            evade(PersonalAvoidEffect.OVER_SHARPENED)
            evade(PersonalAvoidEffect.HEAVY_FILTER)
            protect(DirectionConstraint.NATURAL_LOOK)
            reasons.append(f"{label}×{count}：收敛清晰度/锐化/颗粒，保持自然观感")

    cleaned_targets: dict[str, float] = {}
    for field in PERSONAL_TARGET_FIELDS:
        if field not in targets:
            continue
        value = round(_clamp(targets[field], -100.0, 100.0), 2)
        if abs(value) >= 0.5:
            cleaned_targets[field] = value
    confidence = round(_clamp(confidence, 0.0, 1.0), 3)
    strength = round(_clamp(strength, 0.15, 0.9), 3)
    protected_tuple = tuple(dict.fromkeys(protected))[:11]
    avoid_tuple = tuple(dict.fromkeys(avoid))[:8]
    constraints = tuple(
        dict.fromkeys(
            (
                *base.constraints,
                *protected_tuple,
                *(_AVOID_TO_CONSTRAINT[effect] for effect in avoid_tuple),
            )
        )
    )[:11]

    adjustments: list[StyleEvolutionAdjustment] = []
    if confidence != round(float(base.personal.confidence), 3):
        adjustments.append(
            StyleEvolutionAdjustment(
                field="personal.confidence",
                label="置信度",
                before=round(float(base.personal.confidence), 3),
                after=confidence,
            )
        )
    if strength != round(float(base.default_strength), 3):
        adjustments.append(
            StyleEvolutionAdjustment(
                field="defaultStrength",
                label="默认强度",
                before=round(float(base.default_strength), 3),
                after=strength,
            )
        )
    for field in PERSONAL_TARGET_FIELDS:
        before = round(float(base_targets.get(field, 0.0)), 2)
        after = cleaned_targets.get(field, 0.0)
        if before != after:
            adjustments.append(
                StyleEvolutionAdjustment(
                    field=f"personal.targets.{field}",
                    label=_TARGET_LABELS.get(field, field),
                    before=before,
                    after=after,
                )
            )
    added_protected = [item for item in protected_tuple if item not in base_protected]
    if added_protected:
        adjustments.append(
            StyleEvolutionAdjustment(
                field="personal.protected",
                label="新增保护约束",
                before=None,
                after=[_CONSTRAINT_LABELS.get(item, item.value) for item in added_protected],
            )
        )
    added_avoid = [item for item in avoid_tuple if item not in base_avoid]
    if added_avoid:
        adjustments.append(
            StyleEvolutionAdjustment(
                field="personal.avoid",
                label="新增回避效果",
                before=None,
                after=[item.value for item in added_avoid],
            )
        )

    reason_parts = list(reasons)
    user_note = (note or "").strip()
    if user_note:
        reason_parts.append(f"用户意见：{user_note}")
    elif notes:
        joined = "；".join(item.strip() for item in notes if item.strip())
        if joined:
            reason_parts.append(f"反馈备注：{joined}")
    reason = _cap("；".join(reason_parts) if reason_parts else "根据用户反馈生成保守候选。")

    personal = base.personal.model_copy(
        update={
            "targets": cleaned_targets,
            "confidence": confidence,
            "protected": protected_tuple,
            "avoid": avoid_tuple,
            "user_overrides": tuple(
                dict.fromkeys(
                    (
                        *base.personal.user_overrides,
                        "personal.targets",
                        "personal.avoid",
                        "personal.protected",
                    )
                )
            )[:40],
        }
    )
    profile = base.model_copy(
        update={
            "version": version,
            "personal": personal,
            "constraints": constraints,
            "default_strength": strength,
        }
    )
    definition = base_definition.model_copy(
        update={
            "user_overrides": {
                **base_definition.user_overrides,
                "personal.targets": dict(cleaned_targets),
                "personal.avoid": [effect.value for effect in avoid_tuple],
                "personal.protected": [item.value for item in protected_tuple],
                "evolution": {
                    "feedbackCounts": {item.value: count for item, count in counts.items()},
                    "reason": reason,
                },
            },
            "note": user_note or base_definition.note,
        }
    )

    protection_text = "、".join(
        _CONSTRAINT_LABELS.get(item, item.value) for item in protected_tuple
    )
    summary = _cap(
        f"基于 {feedback_count} 条个人风格反馈生成候选版本。\n"
        f"{reason}\n"
        f"保护约束：{protection_text or '保留原有保护'}"
    )
    if not limitations:
        limitations.append("候选仅为有界建议，仍受既有风格包络与校验链约束，确认前不会修改风格。")

    return EvolutionOutcome(
        profile=profile,
        definition=definition,
        reason=reason,
        summary=summary,
        adjustments=tuple(adjustments[:40]),
        limitations=tuple(_cap(item) for item in limitations)[:12],
        feedback_count=feedback_count,
    )


__all__ = ["EvolutionOutcome", "evolve_profile"]
