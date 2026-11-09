"""Deterministic constraints for the Natural, Style, and Creative conversion modes.

A mode is decision context and a bound, never a filter parameter: it scales and
caps the style intent that the stage 4 engine can already realise. Style mode is
the neutral baseline and reproduces the pre-V6.1 behaviour, so existing style
plans stay byte-identical.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.models.conversion import ConversionMode
from app.models.photographer import (
    ConversionModeInfo,
    DirectionConstraint,
    PhotographerPreferences,
    PhotographerStyleId,
    PlannerMode,
    StyleDefinition,
)
from app.models.recipe import ColorGrading, CurvePoint
from app.photographer.rules import clamp, round2
from app.photographer.styles import (
    strength_factor,
    style_adjustment_intent,
    style_curve_points,
    style_grading,
    style_local_intent,
)
from app.photographer.validator import clamp_adjustment

ALLOWED_ADJUSTMENTS: tuple[str, ...] = (
    "exposureEv",
    "contrast",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "temperature",
    "tint",
    "saturation",
    "vibrance",
    "clarity",
    "sharpen",
    "denoise",
    "vignette",
    "grain",
)

_FORBIDDEN_OPERATIONS: tuple[str, ...] = (
    "生成式填充、扩图、移除或添加画面中的真实物体，以及替换天空",
    "重构背景、添加不存在的光源，或改变人物面部与身体结构",
    "使用超出阶段四调色引擎能力范围的新参数",
    "把普通调色伪装成生成式内容修改",
)


@dataclass(frozen=True, slots=True)
class ConversionProfile:
    mode: ConversionMode
    name: str
    description: str
    envelope_scale: float
    field_scales: Mapping[str, float]
    field_caps: Mapping[str, float]
    local_scale: float
    curve_scale: float
    grading_scale: float
    recommended_strength_min: float
    recommended_strength_max: float
    recommended_strength_default: float
    preservation_constraints: tuple[DirectionConstraint, ...]
    forbidden_operations: tuple[str, ...] = _FORBIDDEN_OPERATIONS

    def field_scale(self, field: str) -> float:
        return self.field_scales.get(field, 1.0)

    def field_cap(self, field: str, envelope_limit: float) -> float:
        limit = envelope_limit * self.envelope_scale
        cap = self.field_caps.get(field)
        return limit if cap is None else min(limit, cap)

    def info(self) -> ConversionModeInfo:
        return ConversionModeInfo(
            mode=self.mode,
            name=self.name,
            description=self.description,
            allowed_adjustments=ALLOWED_ADJUSTMENTS,
            forbidden_operations=self.forbidden_operations,
            preservation_constraints=self.preservation_constraints,
            recommended_strength_min=self.recommended_strength_min,
            recommended_strength_max=self.recommended_strength_max,
            recommended_strength_default=self.recommended_strength_default,
            envelope_scale=self.envelope_scale,
        )


NATURAL_PROFILE = ConversionProfile(
    mode=ConversionMode.NATURAL,
    name="Natural 真实优先",
    description="温和曝光与色彩，保护高光、阴影和肤色，避免明显色偏。",
    envelope_scale=0.6,
    field_scales={
        "exposureEv": 0.6,
        "contrast": 0.5,
        "highlights": 0.6,
        "shadows": 0.65,
        "whites": 0.5,
        "blacks": 0.5,
        "temperature": 0.45,
        "tint": 0.4,
        "saturation": 0.35,
        "vibrance": 0.45,
        "clarity": 0.4,
        "sharpen": 0.4,
        "denoise": 0.8,
        "vignette": 0.25,
        "grain": 0.2,
    },
    field_caps={
        "exposureEv": 0.5,
        "contrast": 18.0,
        "highlights": 18.0,
        "shadows": 20.0,
        "whites": 12.0,
        "blacks": 12.0,
        "temperature": 8.0,
        "tint": 5.0,
        "saturation": 18.0,
        "vibrance": 12.0,
        "clarity": 10.0,
        "sharpen": 10.0,
        "denoise": 20.0,
        "vignette": 8.0,
        "grain": 5.0,
    },
    local_scale=0.55,
    curve_scale=0.55,
    grading_scale=0.6,
    recommended_strength_min=0.2,
    recommended_strength_max=0.7,
    recommended_strength_default=0.45,
    preservation_constraints=(
        DirectionConstraint.NATURAL_LOOK,
        DirectionConstraint.PRESERVE_SKIN_TONE,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
        DirectionConstraint.AVOID_EXTREME_CONTRAST,
        DirectionConstraint.AVOID_COLOR_CAST,
    ),
)

STYLE_PROFILE = ConversionProfile(
    mode=ConversionMode.STYLE,
    name="Style 风格优先",
    description="让目标风格的色彩关系、影调与局部层次清晰可见，同时保留原始内容。",
    envelope_scale=1.0,
    field_scales={},
    field_caps={},
    local_scale=1.0,
    curve_scale=1.0,
    grading_scale=1.0,
    recommended_strength_min=0.4,
    recommended_strength_max=0.9,
    recommended_strength_default=0.65,
    preservation_constraints=(
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
        DirectionConstraint.AVOID_EXTREME_CONTRAST,
    ),
)

CREATIVE_PROFILE = ConversionProfile(
    mode=ConversionMode.CREATIVE,
    name="Creative 创意优先",
    description="在阶段四引擎边界内强化色彩、明暗与局部氛围，不引入生成式内容。",
    envelope_scale=1.25,
    field_scales={
        "exposureEv": 1.05,
        "contrast": 1.25,
        "highlights": 1.1,
        "shadows": 1.1,
        "whites": 1.1,
        "blacks": 1.1,
        "temperature": 1.1,
        "tint": 1.1,
        "saturation": 1.2,
        "vibrance": 1.2,
        "clarity": 1.2,
        "sharpen": 1.2,
        "denoise": 1.1,
        "vignette": 1.25,
        "grain": 1.3,
    },
    field_caps={
        "exposureEv": 2.0,
        "contrast": 45.0,
        "highlights": 35.0,
        "shadows": 35.0,
        "whites": 25.0,
        "blacks": 25.0,
        "temperature": 18.0,
        "tint": 12.0,
        "saturation": 100.0,
        "vibrance": 40.0,
        "clarity": 35.0,
        "sharpen": 30.0,
        "denoise": 30.0,
        "vignette": 30.0,
        "grain": 25.0,
    },
    local_scale=1.25,
    curve_scale=1.1,
    grading_scale=1.2,
    recommended_strength_min=0.55,
    recommended_strength_max=1.0,
    recommended_strength_default=0.8,
    preservation_constraints=(
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
    ),
)

CONVERSION_PROFILES: Mapping[ConversionMode, ConversionProfile] = {
    ConversionMode.NATURAL: NATURAL_PROFILE,
    ConversionMode.STYLE: STYLE_PROFILE,
    ConversionMode.CREATIVE: CREATIVE_PROFILE,
}


def conversion_profile(mode: ConversionMode) -> ConversionProfile:
    return CONVERSION_PROFILES[mode]


def conversion_mode_infos() -> tuple[ConversionModeInfo, ...]:
    return tuple(CONVERSION_PROFILES[mode].info() for mode in ConversionMode)


def resolve_conversion_mode(
    planner_mode: PlannerMode,
    requested: ConversionMode | None,
) -> ConversionMode | None:
    """Auto plans have no conversion; style plans default to the neutral baseline."""
    if planner_mode is PlannerMode.AUTO:
        return None
    return requested if requested is not None else ConversionMode.STYLE


def mode_style_intent(
    style: StyleDefinition,
    strength: float,
    preferences: PhotographerPreferences,
    mode: ConversionMode,
) -> dict[str, float]:
    if strength <= 0.0:
        return {}
    base = style_adjustment_intent(style, strength, preferences)
    profile = conversion_profile(mode)
    if mode is ConversionMode.STYLE:
        return base
    envelope = style.envelope.model_dump(by_alias=True)
    result: dict[str, float] = {}
    for field, delta in base.items():
        limit = profile.field_cap(field, float(envelope[field]))
        scaled = clamp(delta * profile.field_scale(field), -limit, limit)
        rounded = round2(clamp_adjustment(field, scaled))
        if abs(rounded) >= 0.005:
            result[field] = rounded
    return result


def mode_local_intent(
    style_id: PhotographerStyleId,
    strength: float,
    mode: ConversionMode,
) -> dict[str, float]:
    profile = conversion_profile(mode)
    base = style_local_intent(style_id, strength, scale=profile.local_scale)
    return {field: round2(clamp_adjustment(field, value)) for field, value in base.items()}


def mode_curve_points(
    style_id: PhotographerStyleId,
    strength: float,
    mode: ConversionMode,
) -> tuple[CurvePoint, ...]:
    return style_curve_points(
        style_id,
        strength,
        scale=conversion_profile(mode).curve_scale,
    )


def mode_grading(
    style_id: PhotographerStyleId,
    strength: float,
    mode: ConversionMode,
) -> ColorGrading | None:
    return style_grading(
        style_id,
        strength,
        scale=conversion_profile(mode).grading_scale,
    )


def interpolate_intent(
    full_intent: Mapping[str, float],
    strength: float,
    *,
    identity_fields: frozenset[str] = frozenset(),
) -> dict[str, float]:
    """Rescale a stored full-strength intent without calling the model again."""
    if strength <= 0.0:
        return {}
    result: dict[str, float] = {}
    for field, value in full_intent.items():
        factor = strength_factor(field, strength, identity=field in identity_fields)
        rounded = round2(value * factor)
        if abs(rounded) >= 0.005:
            result[field] = rounded
    return result


__all__ = [
    "ALLOWED_ADJUSTMENTS",
    "CONVERSION_PROFILES",
    "CREATIVE_PROFILE",
    "ConversionProfile",
    "NATURAL_PROFILE",
    "STYLE_PROFILE",
    "conversion_mode_infos",
    "conversion_profile",
    "interpolate_intent",
    "mode_curve_points",
    "mode_grading",
    "mode_local_intent",
    "mode_style_intent",
    "resolve_conversion_mode",
]
