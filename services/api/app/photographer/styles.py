from __future__ import annotations

import math

from app.ai.contracts import SceneLabel
from app.models.photographer import (
    CreativeDirection,
    DirectionConstraint,
    PhotographerPreferences,
    PhotographerStyleId,
    StyleCategory,
    StyleDefinition,
    StyleEnvelope,
)
from app.models.recipe import ColorGradeZone, ColorGrading, CurvePoint
from app.photographer.rules import clamp, round2

_ALL_SCENES: tuple[SceneLabel, ...] = tuple(SceneLabel)

_NATURAL_CONSTRAINTS = (
    DirectionConstraint.NATURAL_LOOK,
    DirectionConstraint.PRESERVE_SKIN_TONE,
    DirectionConstraint.AVOID_EXTREME_SATURATION,
    DirectionConstraint.AVOID_EXTREME_CONTRAST,
)

_SCENE_DIRECTIONS: dict[SceneLabel, tuple[str, str, str, tuple[DirectionConstraint, ...]]] = {
    SceneLabel.PORTRAIT: (
        "natural_portrait",
        "自然人像",
        "保留自然肤色，平衡人物曝光，并适当控制背景亮度。",
        (
            DirectionConstraint.PRESERVE_SKIN_TONE,
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.AVOID_EXTREME_SATURATION,
        ),
    ),
    SceneLabel.LANDSCAPE: (
        "natural_landscape",
        "自然风光",
        "保留天空层次，增强空间与细节，同时控制过度锐化。",
        (
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.PRESERVE_SHADOW_DETAIL,
            DirectionConstraint.NATURAL_LOOK,
        ),
    ),
    SceneLabel.STREET: (
        "documentary_street",
        "纪实街头",
        "保持现场氛围与真实色彩，用克制的对比强调主体。",
        (
            DirectionConstraint.KEEP_AMBIENT_COLOR,
            DirectionConstraint.NATURAL_LOOK,
            DirectionConstraint.AVOID_EXTREME_SATURATION,
        ),
    ),
    SceneLabel.ARCHITECTURE: (
        "clean_architecture",
        "建筑线条",
        "突出结构线条与材质细节，保护高光并保持中性色。",
        (
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.MAINTAIN_NEUTRALITY,
            DirectionConstraint.AVOID_COLOR_CAST,
        ),
    ),
    SceneLabel.NIGHT: (
        "night_ambience",
        "夜景氛围",
        "保留夜色氛围，控制噪点，仅温和提亮必要的暗部。",
        (
            DirectionConstraint.KEEP_LOW_KEY,
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.KEEP_AMBIENT_COLOR,
        ),
    ),
    SceneLabel.INDOOR: (
        "indoor_natural",
        "室内自然",
        "校正混合光源，保持肤色与室内氛围的平衡。",
        (
            DirectionConstraint.PRESERVE_SKIN_TONE,
            DirectionConstraint.AVOID_COLOR_CAST,
            DirectionConstraint.KEEP_AMBIENT_COLOR,
        ),
    ),
    SceneLabel.FOOD: (
        "food_warmth",
        "食物质感",
        "突出食物色彩与质感，避免过度饱和和生硬对比。",
        (
            DirectionConstraint.AVOID_EXTREME_SATURATION,
            DirectionConstraint.KEEP_WARM_TONES,
            DirectionConstraint.NATURAL_LOOK,
        ),
    ),
    SceneLabel.NATURE: (
        "nature_fresh",
        "自然清新",
        "保留植被层次与自然色彩，维持柔和的明暗过渡。",
        (
            DirectionConstraint.NATURAL_LOOK,
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.AVOID_EXTREME_CONTRAST,
        ),
    ),
    SceneLabel.OTHER: (
        "balanced_natural",
        "自然平衡",
        "以克制的方式平衡曝光、色彩与细节，保留原始观感。",
        _NATURAL_CONSTRAINTS,
    ),
}


def _envelope(**overrides: float) -> StyleEnvelope:
    return StyleEnvelope(**overrides)


_NATURAL_STYLE = StyleDefinition(
    id="natural",
    engine_style="natural",
    version="1.0",
    name="自然摄影",
    category=StyleCategory.CREATIVE,
    description="以最小干预保留原始观感，只处理明确的技术问题。",
    supported_scenes=_ALL_SCENES,
    default_strength=0.35,
    envelope=_envelope(
        exposure_ev=0.8,
        contrast=15.0,
        highlights=20.0,
        shadows=20.0,
        whites=15.0,
        blacks=15.0,
        temperature=8.0,
        tint=5.0,
        saturation=8.0,
        vibrance=10.0,
        clarity=15.0,
        denoise=25.0,
        vignette=0.0,
        grain=0.0,
    ),
    constraints=_NATURAL_CONSTRAINTS,
)

STYLE_CATALOG: tuple[StyleDefinition, ...] = (
    _NATURAL_STYLE,
    StyleDefinition(
        id="portrait",
        engine_style="portrait",
        version="1.0",
        name="自然人像",
        category=StyleCategory.SCENE,
        description="优先肤色与人物曝光，背景保持克制。",
        supported_scenes=(SceneLabel.PORTRAIT, SceneLabel.INDOOR, SceneLabel.STREET),
        default_strength=0.5,
        envelope=_envelope(saturation=10.0, vibrance=12.0, clarity=8.0, vignette=8.0),
        constraints=(
            DirectionConstraint.PRESERVE_SKIN_TONE,
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.AVOID_EXTREME_SATURATION,
        ),
    ),
    StyleDefinition(
        id="clear_portrait",
        engine_style="portrait",
        version="1.0",
        name="清透人像",
        category=StyleCategory.SCENE,
        description="提亮暗部、柔和高光，让皮肤与画面更通透，不牺牲细节。",
        supported_scenes=(SceneLabel.PORTRAIT, SceneLabel.INDOOR, SceneLabel.FOOD),
        default_strength=0.55,
        envelope=_envelope(
            exposure_ev=0.6,
            contrast=12.0,
            highlights=30.0,
            shadows=30.0,
            whites=15.0,
            blacks=15.0,
            temperature=8.0,
            tint=6.0,
            saturation=8.0,
            vibrance=15.0,
            clarity=10.0,
            vignette=0.0,
            grain=0.0,
        ),
        constraints=(
            DirectionConstraint.PRESERVE_SKIN_TONE,
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.PRESERVE_SHADOW_DETAIL,
            DirectionConstraint.NATURAL_LOOK,
        ),
    ),
    StyleDefinition(
        id="landscape",
        engine_style="landscape",
        version="1.0",
        name="风光",
        category=StyleCategory.SCENE,
        description="强调天空层次、植被色彩与空间细节。",
        supported_scenes=(SceneLabel.LANDSCAPE, SceneLabel.NATURE, SceneLabel.ARCHITECTURE),
        default_strength=0.55,
        envelope=_envelope(highlights=35.0, shadows=35.0, vibrance=25.0, clarity=30.0),
        constraints=(
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.PRESERVE_SHADOW_DETAIL,
            DirectionConstraint.NATURAL_LOOK,
        ),
    ),
    StyleDefinition(
        id="street",
        engine_style="street",
        version="1.0",
        name="街头",
        category=StyleCategory.SCENE,
        description="保留现场光色，用克制的对比与清晰度强调主体。",
        supported_scenes=(SceneLabel.STREET, SceneLabel.ARCHITECTURE, SceneLabel.NIGHT),
        default_strength=0.5,
        envelope=_envelope(contrast=25.0, clarity=25.0, vibrance=15.0, grain=10.0),
        constraints=(
            DirectionConstraint.KEEP_AMBIENT_COLOR,
            DirectionConstraint.NATURAL_LOOK,
            DirectionConstraint.AVOID_EXTREME_SATURATION,
        ),
    ),
    StyleDefinition(
        id="documentary",
        engine_style="documentary",
        version="1.0",
        name="纪实",
        category=StyleCategory.CREATIVE,
        description="忠实记录现场，避免明显风格化和过度修饰。",
        supported_scenes=_ALL_SCENES,
        default_strength=0.4,
        envelope=_envelope(
            exposure_ev=0.8,
            contrast=15.0,
            highlights=25.0,
            shadows=25.0,
            temperature=8.0,
            tint=5.0,
            saturation=8.0,
            vibrance=10.0,
            clarity=15.0,
            vignette=0.0,
            grain=0.0,
        ),
        constraints=_NATURAL_CONSTRAINTS,
    ),
    StyleDefinition(
        id="film",
        engine_style="film",
        version="1.0",
        name="复古胶片",
        category=StyleCategory.CREATIVE,
        description="柔和的高光过渡、克制的饱和与轻微颗粒感。",
        supported_scenes=(
            SceneLabel.PORTRAIT,
            SceneLabel.STREET,
            SceneLabel.LANDSCAPE,
            SceneLabel.INDOOR,
            SceneLabel.NATURE,
        ),
        default_strength=0.6,
        envelope=_envelope(
            contrast=20.0,
            highlights=25.0,
            shadows=25.0,
            temperature=12.0,
            tint=10.0,
            saturation=12.0,
            vibrance=12.0,
            grain=25.0,
            vignette=12.0,
        ),
        constraints=(
            DirectionConstraint.AVOID_EXTREME_CONTRAST,
            DirectionConstraint.PRESERVE_SKIN_TONE,
            DirectionConstraint.KEEP_AMBIENT_COLOR,
        ),
    ),
    StyleDefinition(
        id="cinematic",
        engine_style="cinematic",
        version="1.0",
        name="电影叙事",
        category=StyleCategory.CREATIVE,
        description="受控的明暗对比与冷暖分离，保留高光层次。",
        supported_scenes=(
            SceneLabel.LANDSCAPE,
            SceneLabel.STREET,
            SceneLabel.NIGHT,
            SceneLabel.ARCHITECTURE,
            SceneLabel.PORTRAIT,
        ),
        default_strength=0.65,
        envelope=_envelope(
            contrast=30.0,
            highlights=35.0,
            shadows=30.0,
            temperature=15.0,
            tint=12.0,
            saturation=12.0,
            vibrance=15.0,
            clarity=20.0,
            vignette=18.0,
            grain=12.0,
        ),
        constraints=(
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.AVOID_EXTREME_SATURATION,
            DirectionConstraint.KEEP_AMBIENT_COLOR,
        ),
    ),
    StyleDefinition(
        id="monochrome",
        engine_style="documentary",
        version="1.0",
        name="黑白纪实",
        category=StyleCategory.CREATIVE,
        description="完全去饱和，用层次而非色彩讲述画面，保护高光与阴影细节。",
        supported_scenes=(
            SceneLabel.PORTRAIT,
            SceneLabel.STREET,
            SceneLabel.ARCHITECTURE,
            SceneLabel.NIGHT,
            SceneLabel.NATURE,
            SceneLabel.INDOOR,
            SceneLabel.OTHER,
        ),
        default_strength=0.7,
        envelope=_envelope(
            exposure_ev=0.8,
            contrast=35.0,
            highlights=30.0,
            shadows=30.0,
            whites=20.0,
            blacks=20.0,
            temperature=8.0,
            tint=5.0,
            saturation=100.0,
            vibrance=20.0,
            clarity=25.0,
            vignette=15.0,
            grain=0.0,
        ),
        constraints=(
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.PRESERVE_SHADOW_DETAIL,
            DirectionConstraint.MAINTAIN_NEUTRALITY,
            DirectionConstraint.AVOID_EXTREME_CONTRAST,
        ),
    ),
    StyleDefinition(
        id="vivid",
        engine_style="landscape",
        version="1.0",
        name="鲜艳纪实",
        category=StyleCategory.CREATIVE,
        description="在保留细节的前提下加强色彩与立体感，避免过度饱和。",
        supported_scenes=(
            SceneLabel.LANDSCAPE,
            SceneLabel.NATURE,
            SceneLabel.FOOD,
            SceneLabel.STREET,
            SceneLabel.INDOOR,
            SceneLabel.OTHER,
        ),
        default_strength=0.55,
        envelope=_envelope(
            contrast=30.0,
            highlights=30.0,
            shadows=30.0,
            saturation=20.0,
            vibrance=30.0,
            clarity=30.0,
            vignette=10.0,
            grain=0.0,
        ),
        constraints=(
            DirectionConstraint.PRESERVE_SKIN_TONE,
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.PRESERVE_SHADOW_DETAIL,
            DirectionConstraint.AVOID_EXTREME_CONTRAST,
        ),
    ),
    StyleDefinition(
        id="warm_life",
        engine_style="portrait",
        version="1.0",
        name="暖调生活",
        category=StyleCategory.CREATIVE,
        description="温暖的现场氛围与柔和暗部，保持肤色自然。",
        supported_scenes=(
            SceneLabel.INDOOR,
            SceneLabel.FOOD,
            SceneLabel.PORTRAIT,
            SceneLabel.STREET,
            SceneLabel.OTHER,
        ),
        default_strength=0.5,
        envelope=_envelope(
            exposure_ev=0.5,
            contrast=18.0,
            highlights=25.0,
            shadows=25.0,
            temperature=20.0,
            tint=10.0,
            saturation=12.0,
            vibrance=15.0,
            clarity=12.0,
            vignette=12.0,
            grain=10.0,
        ),
        constraints=(
            DirectionConstraint.KEEP_WARM_TONES,
            DirectionConstraint.PRESERVE_SKIN_TONE,
            DirectionConstraint.NATURAL_LOOK,
        ),
    ),
    StyleDefinition(
        id="cool_urban",
        engine_style="street",
        version="1.0",
        name="冷调城市",
        category=StyleCategory.CREATIVE,
        description="偏冷的都市色调与克制的色彩，强调结构与对比。",
        supported_scenes=(
            SceneLabel.STREET,
            SceneLabel.ARCHITECTURE,
            SceneLabel.NIGHT,
            SceneLabel.INDOOR,
            SceneLabel.OTHER,
        ),
        default_strength=0.5,
        envelope=_envelope(
            contrast=30.0,
            highlights=25.0,
            shadows=25.0,
            temperature=20.0,
            tint=10.0,
            saturation=12.0,
            vibrance=15.0,
            clarity=25.0,
            vignette=15.0,
            grain=8.0,
        ),
        constraints=(
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            DirectionConstraint.PRESERVE_SHADOW_DETAIL,
            DirectionConstraint.AVOID_EXTREME_CONTRAST,
        ),
    ),
)

_STYLES_BY_ID: dict[PhotographerStyleId, StyleDefinition] = {
    style.id: style for style in STYLE_CATALOG
}


def get_style(style_id: PhotographerStyleId) -> StyleDefinition | None:
    return _STYLES_BY_ID.get(style_id)


_STYLE_VALUES: dict[PhotographerStyleId, dict[str, float]] = {
    "natural": {},
    "portrait": {"vibrance": 6.0, "clarity": 4.0, "vignette": 6.0},
    "clear_portrait": {
        "exposureEv": 0.12,
        "highlights": -10.0,
        "shadows": 12.0,
        "whites": 6.0,
        "vibrance": 8.0,
        "clarity": -4.0,
    },
    "landscape": {"vibrance": 14.0, "clarity": 10.0, "highlights": -10.0, "shadows": 8.0},
    "street": {"contrast": 10.0, "clarity": 8.0, "vibrance": 6.0, "grain": 6.0},
    "documentary": {},
    "film": {
        "contrast": 8.0,
        "highlights": -8.0,
        "shadows": 10.0,
        "temperature": 5.0,
        "saturation": -3.0,
        "grain": 16.0,
        "vignette": 8.0,
    },
    "cinematic": {
        "contrast": 14.0,
        "highlights": -10.0,
        "shadows": 10.0,
        "vibrance": 8.0,
        "vignette": 10.0,
        "grain": 6.0,
    },
    "monochrome": {"contrast": 12.0, "highlights": -8.0, "shadows": 8.0, "clarity": 8.0},
    "vivid": {
        "contrast": 10.0,
        "vibrance": 16.0,
        "saturation": 6.0,
        "clarity": 10.0,
        "highlights": -8.0,
        "shadows": 6.0,
    },
    "warm_life": {
        "temperature": 9.0,
        "tint": 2.0,
        "shadows": 8.0,
        "vibrance": 6.0,
        "saturation": 3.0,
        "grain": 6.0,
    },
    "cool_urban": {
        "temperature": -9.0,
        "tint": -2.0,
        "contrast": 12.0,
        "clarity": 8.0,
        "vibrance": 4.0,
        "saturation": -4.0,
        "vignette": 6.0,
    },
}

# Colour-mode parameters define the style itself, so they are not scaled by
# naturalness: a black-and-white style is monochrome once it is engaged.
_STYLE_COLOR_MODE: dict[PhotographerStyleId, dict[str, float]] = {
    "monochrome": {"saturation": -100.0},
}

_CURVE_PRESETS: dict[str, tuple[tuple[float, float], ...]] = {
    "soft_contrast": ((0.0, 0.0), (0.25, 0.21), (0.75, 0.79), (1.0, 1.0)),
    "film_fade": ((0.0, 0.06), (0.2, 0.22), (0.5, 0.5), (0.8, 0.8), (1.0, 0.95)),
    "lifted_blacks": ((0.0, 0.04), (0.25, 0.26), (0.75, 0.76), (1.0, 1.0)),
}

_STYLE_CURVES: dict[PhotographerStyleId, str] = {
    "clear_portrait": "lifted_blacks",
    "landscape": "soft_contrast",
    "street": "soft_contrast",
    "film": "film_fade",
    "cinematic": "lifted_blacks",
    "monochrome": "soft_contrast",
    "vivid": "soft_contrast",
    "cool_urban": "lifted_blacks",
}

_STYLE_GRADING: dict[PhotographerStyleId, dict[str, tuple[float, float]]] = {
    "film": {
        "shadows": (35.0, 10.0),
        "midtones": (45.0, 6.0),
        "highlights": (50.0, 8.0),
    },
    "cinematic": {
        "shadows": (220.0, 18.0),
        "midtones": (210.0, 6.0),
        "highlights": (35.0, 12.0),
    },
    "warm_life": {
        "shadows": (30.0, 8.0),
        "midtones": (40.0, 6.0),
        "highlights": (48.0, 8.0),
    },
    "cool_urban": {
        "shadows": (205.0, 16.0),
        "midtones": (200.0, 6.0),
        "highlights": (190.0, 8.0),
    },
}

# Local strategies reshape the masks the user already owns; the planner never
# creates masks, so a style without an available mask simply reports a limitation.
_LOCAL_STRATEGIES: dict[PhotographerStyleId, dict[str, float]] = {
    "portrait": {"shadows": 8.0, "highlights": -6.0, "clarity": 4.0},
    "clear_portrait": {"shadows": 10.0, "highlights": -8.0},
    "landscape": {"highlights": -10.0, "shadows": 8.0, "clarity": 8.0},
    "street": {"contrast": 8.0, "clarity": 6.0},
    "film": {"shadows": 6.0, "contrast": 6.0},
    "cinematic": {"contrast": 10.0, "shadows": 6.0},
    "monochrome": {"contrast": 10.0, "clarity": 6.0},
    "vivid": {"clarity": 8.0, "contrast": 8.0, "vibrance": 8.0},
    "warm_life": {"shadows": 6.0, "temperature": 4.0},
    "cool_urban": {"contrast": 8.0, "clarity": 6.0},
}

_SMOOTH_FIELDS = frozenset({"contrast", "highlights", "shadows", "whites", "blacks", "clarity"})
_GRADING_THRESHOLD = 0.25


def blend_factor(field: str, strength: float) -> float:
    """Non-linear engagement curve for one parameter, exposed for previews."""
    return _blend_factor(field, strength)


def _blend_factor(field: str, strength: float) -> float:
    strength = clamp(strength, 0.0, 1.0)
    if field == "exposureEv":
        return math.sqrt(strength)
    if field in _SMOOTH_FIELDS:
        if strength < 0.15:
            return 0.0
        scaled = (strength - 0.15) / 0.85
        return scaled * scaled * (3.0 - 2.0 * scaled)
    return strength


def _identity_factor(strength: float) -> float:
    # A colour-mode parameter defines the style, so it ramps twice as fast:
    # half strength already means a fully monochrome image.
    return clamp(strength * 2.0, 0.0, 1.0)


def style_adjustment_intent(
    style: StyleDefinition,
    strength: float,
    preferences: PhotographerPreferences,
) -> dict[str, float]:
    """Parameter deltas for an explicitly selected style, blended and envelope-capped.

    Style deltas are not run through the conservative auto caps: choosing a style is
    already an opt-in to its look, and the envelope is what bounds it here.
    """
    if strength <= 0.0:
        return {}
    envelope = style.envelope.model_dump(by_alias=True)
    naturalness_scale = 1.0 - 0.5 * preferences.naturalness
    identity = _STYLE_COLOR_MODE.get(style.id, {})
    plan = [(field, raw, False) for field, raw in _STYLE_VALUES.get(style.id, {}).items()]
    plan += [(field, raw, True) for field, raw in identity.items()]

    values: dict[str, float] = {}
    for field, raw, is_identity in plan:
        factor = _identity_factor(strength) if is_identity else _blend_factor(field, strength)
        delta = raw * factor
        if not is_identity:
            delta *= naturalness_scale
        limit = float(envelope[field])
        rounded = round2(clamp(delta, -limit, limit))
        if abs(rounded) >= 0.005:
            values[field] = rounded
    return values


def style_local_intent(style_id: PhotographerStyleId, strength: float) -> dict[str, float]:
    """Local deltas for masks the user already created; empty when the style has none."""
    if strength <= 0.0:
        return {}
    values: dict[str, float] = {}
    for field, raw in _LOCAL_STRATEGIES.get(style_id, {}).items():
        rounded = round2(raw * _blend_factor(field, strength))
        if abs(rounded) >= 0.005:
            values[field] = rounded
    return values


def style_curve_points(style_id: PhotographerStyleId, strength: float) -> tuple[CurvePoint, ...]:
    preset = _STYLE_CURVES.get(style_id)
    if preset is None or strength <= 0.0:
        return ()
    amount = clamp(strength, 0.0, 1.0)
    points: list[CurvePoint] = []
    for x, y in _CURVE_PRESETS[preset]:
        blended = x + (y - x) * amount
        points.append(CurvePoint(x=round(x, 6), y=round(blended, 6)))
    return tuple(points)


def style_grading(style_id: PhotographerStyleId, strength: float) -> ColorGrading | None:
    if strength < _GRADING_THRESHOLD:
        return None
    spec = _STYLE_GRADING.get(style_id)
    if spec is None:
        return None
    amount = (clamp(strength, 0.0, 1.0) - _GRADING_THRESHOLD) / (1.0 - _GRADING_THRESHOLD)
    zones = {
        name: ColorGradeZone(hue=round2(hue), saturation=round2(saturation * amount))
        for name, (hue, saturation) in spec.items()
    }
    return ColorGrading(
        shadows=zones["shadows"],
        midtones=zones["midtones"],
        highlights=zones["highlights"],
    )


def direction_for_scene(
    scene: SceneLabel,
    preferences: PhotographerPreferences,
    style: StyleDefinition | None = None,
    *,
    style_strength: float | None = None,
) -> CreativeDirection:
    base_id, base_name, base_description, base_constraints = _SCENE_DIRECTIONS[scene]

    if style is not None:
        constraints = tuple(dict.fromkeys((*style.constraints, *base_constraints)))
        strength = style.default_strength if style_strength is None else style_strength
        return CreativeDirection(
            id=f"{style.id}_direction",
            name=style.name,
            category=style.category,
            description=style.description,
            strength=round(min(max(strength, 0.0), 1.0), 2),
            constraints=constraints,
        )

    strength = 0.35 + 0.3 * preferences.adjustment_strength + 0.15 * (1.0 - preferences.naturalness)
    return CreativeDirection(
        id=base_id,
        name=base_name,
        category=StyleCategory.SCENE,
        description=base_description,
        strength=round(min(max(strength, 0.0), 1.0), 2),
        constraints=base_constraints,
    )


__all__ = [
    "STYLE_CATALOG",
    "blend_factor",
    "direction_for_scene",
    "get_style",
    "style_adjustment_intent",
    "style_curve_points",
    "style_grading",
    "style_local_intent",
]
