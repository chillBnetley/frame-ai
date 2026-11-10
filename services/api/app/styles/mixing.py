"""Deterministic two-style mixing.

The engine combines two style archives dimension by dimension instead of
averaging two parameter tables: continuous targets interpolate only when a
dimension is genuinely blended, trait descriptions recombine semantically with
attribution, protection constraints are always unioned (never averaged away),
and contradictory directions are surfaced as conflicts resolved by user choice,
feature source, or a neutral protective fallback. No provider call is involved,
so previews stay instant and adjustable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from app.ai.contracts import SceneLabel
from app.models.personal_style import (
    PERSONAL_TARGET_FIELDS,
    PersonalAvoidEffect,
    PersonalStyleDefinition,
    PersonalStyleHints,
    PersonalStyleProfile,
    PersonalStyleSource,
)
from app.models.photographer import DirectionConstraint, StyleEnvelope
from app.models.style_mix import (
    MIX_DIMENSIONS,
    ConflictResolution,
    MixDimension,
    MixSource,
    StyleMixConflict,
    StyleMixDimensionPlan,
    StyleMixProvenance,
)
from app.models.style_profile import (
    StyleColorTraits,
    StyleCompositionTraits,
    StyleLightTraits,
    StyleProfile,
    StyleSceneFit,
    StyleSource,
    StyleTextureTraits,
)
from app.styles.vocabulary import SCENE_NAMES

MIX_SCHEMA_VERSION = "style-mix/1"

_ResolvedBy = Literal["weight", "source", "protection", "user"]

_PROTECTION_CONSTRAINTS = frozenset(
    {
        DirectionConstraint.PRESERVE_SKIN_TONE,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.AVOID_EXTREME_SATURATION,
        DirectionConstraint.AVOID_EXTREME_CONTRAST,
        DirectionConstraint.AVOID_COLOR_CAST,
        DirectionConstraint.MAINTAIN_NEUTRALITY,
        DirectionConstraint.NATURAL_LOOK,
    }
)

_CONSTRAINT_LABELS: dict[DirectionConstraint, str] = {
    DirectionConstraint.PRESERVE_SKIN_TONE: "保护肤色",
    DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL: "保护高光细节",
    DirectionConstraint.PRESERVE_SHADOW_DETAIL: "保护暗部细节",
    DirectionConstraint.AVOID_EXTREME_SATURATION: "避免极端饱和度",
    DirectionConstraint.AVOID_EXTREME_CONTRAST: "避免极端反差",
    DirectionConstraint.KEEP_AMBIENT_COLOR: "保留环境色",
    DirectionConstraint.NATURAL_LOOK: "保持自然观感",
    DirectionConstraint.AVOID_COLOR_CAST: "避免明显偏色",
    DirectionConstraint.MAINTAIN_NEUTRALITY: "保持中性白平衡",
    DirectionConstraint.KEEP_LOW_KEY: "保持低调",
    DirectionConstraint.KEEP_WARM_TONES: "保留暖调",
}

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

_CONSTRAINT_TO_AVOID: dict[DirectionConstraint, PersonalAvoidEffect] = {
    DirectionConstraint.AVOID_EXTREME_SATURATION: PersonalAvoidEffect.OVERSATURATED,
    DirectionConstraint.PRESERVE_SHADOW_DETAIL: PersonalAvoidEffect.CRUSHED_BLACKS,
    DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL: PersonalAvoidEffect.CLIPPED_HIGHLIGHTS,
    DirectionConstraint.AVOID_COLOR_CAST: PersonalAvoidEffect.COLOR_CAST,
    DirectionConstraint.PRESERVE_SKIN_TONE: PersonalAvoidEffect.UNNATURAL_SKIN,
    DirectionConstraint.NATURAL_LOOK: PersonalAvoidEffect.HEAVY_FILTER,
    DirectionConstraint.AVOID_EXTREME_CONTRAST: PersonalAvoidEffect.FLAT_CONTRAST,
}

_DIMENSION_TITLES: dict[MixDimension, str] = {
    "color": "色彩",
    "tone": "影调",
    "light": "光线",
    "texture": "质感",
    "composition": "构图",
    "scene": "场景适配",
}

_DIMENSION_TARGETS: dict[MixDimension, tuple[str, ...]] = {
    "color": ("temperature", "tint", "saturation", "vibrance"),
    "tone": ("exposureEv", "contrast", "highlights", "shadows", "whites", "blacks"),
    "light": (),
    "texture": ("clarity", "sharpen", "denoise", "grain", "vignette"),
    "composition": (),
    "scene": (),
}

_TARGET_DIMENSION: dict[str, MixDimension] = {
    field: dimension for dimension, fields in _DIMENSION_TARGETS.items() for field in fields
}

_CONFLICT_PARENT: dict[str, MixDimension] = {
    "color.saturation": "color",
    "color.temperature": "color",
    "color.tint": "color",
    "tone.contrast": "tone",
    "tone.key": "tone",
    "skin": "color",
    "detail": "tone",
    "scene": "scene",
}


@dataclass(frozen=True, slots=True)
class StyleDirection:
    """A bounded numeric/semantic reading of one archive used for mixing."""

    targets: dict[str, float]
    monochrome: bool
    protected: tuple[DirectionConstraint, ...]
    avoid: tuple[PersonalAvoidEffect, ...]
    constraints: tuple[DirectionConstraint, ...]
    scenes: tuple[SceneLabel, ...]
    is_personal: bool


@dataclass(frozen=True, slots=True)
class _ConflictSpec:
    dimension: str
    title: str
    labels: tuple[str, str]
    message: str
    suggestion: str
    fields: tuple[str, ...]
    protection: tuple[DirectionConstraint, ...]


@dataclass(frozen=True, slots=True)
class MixOutcome:
    profile: PersonalStyleProfile
    definition: PersonalStyleDefinition
    weight: int
    sources: dict[MixDimension, MixSource]
    dimensions: tuple[StyleMixDimensionPlan, ...]
    conflicts: tuple[StyleMixConflict, ...]
    protections: tuple[str, ...]
    summary: str
    limitations: tuple[str, ...]
    provenance: StyleMixProvenance


def _cap(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "—"
    return cleaned[:500]


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _keyword(text: str, words: Sequence[str]) -> bool:
    return any(word in text for word in words)


def _master_targets(profile: StyleProfile) -> tuple[dict[str, float], bool]:
    """Heuristic bounded hints read from a master/genre archive's traits.

    These are understanding material, not recipe parameters: the stage 5
    generator still applies the envelope, conversion scaling, and validator.
    """

    color_text = f"{profile.color.tendency} {profile.color.saturation}"
    relationships = profile.color.relationships
    monochrome = _keyword(color_text, ("黑白", "单色", "去饱和"))
    targets = {field: 0.0 for field in PERSONAL_TARGET_FIELDS}
    if monochrome:
        targets["saturation"] = -100.0
    elif _keyword(color_text, ("低饱和", "偏低", "克制")):
        targets["saturation"] = -12.0
    elif _keyword(color_text, ("高饱和", "浓郁", "鲜艳")):
        targets["saturation"] = 12.0
    temp_text = f"{profile.color.tendency} {relationships}"
    if _keyword(temp_text, ("暖调", "偏暖", "暖色", "温暖")):
        targets["temperature"] = 8.0
    elif _keyword(temp_text, ("偏冷", "冷调", "冷色", "清冷")):
        targets["temperature"] = -8.0
    if _keyword(temp_text, ("偏绿", "绿调")):
        targets["tint"] = -5.0
    elif _keyword(temp_text, ("洋红", "偏紫", "品红")):
        targets["tint"] = 5.0
    if _keyword(profile.light.contrast, ("高对比", "高反差", "强烈反差", "强对比")):
        targets["contrast"] = 15.0
    elif _keyword(profile.light.contrast, ("中低对比", "低对比", "柔和", "柔化", "低反差")):
        targets["contrast"] = -8.0
    if _keyword(profile.light.highlights, ("抑制", "压高光", "压制亮部")):
        targets["highlights"] = -10.0
    if _keyword(profile.light.shadows, ("深阴影", "大面积深", "压暗")):
        targets["shadows"] = -8.0
    elif _keyword(profile.light.shadows, ("不压死黑", "灰暗部", "暗部开放")):
        targets["shadows"] = 6.0
    if _keyword(profile.texture.grain, ("颗粒", "银盐", "胶片")):
        targets["grain"] = 8.0
    sharp_text = f"{profile.texture.sharpness} {profile.texture.detail}"
    if _keyword(sharp_text, ("偏锐", "锐利", "强化", "突出结构")):
        targets["clarity"] = 6.0
    elif _keyword(sharp_text, ("偏软", "不追求极致锐利")):
        targets["clarity"] = -5.0
    return targets, monochrome


def derive_direction(profile: StyleProfile) -> StyleDirection:
    if isinstance(profile, PersonalStyleProfile):
        targets = {
            field: float(profile.personal.targets.get(field, 0.0))
            for field in PERSONAL_TARGET_FIELDS
        }
        monochrome = targets.get("saturation", 0.0) <= -50.0
        protected = tuple(profile.personal.protected)
        avoid = tuple(profile.personal.avoid)
        is_personal = True
    else:
        targets, monochrome = _master_targets(profile)
        protected = tuple(item for item in profile.constraints if item in _PROTECTION_CONSTRAINTS)
        avoid = tuple(
            dict.fromkeys(
                _CONSTRAINT_TO_AVOID[item]
                for item in profile.constraints
                if item in _CONSTRAINT_TO_AVOID
            )
        )
        is_personal = False
    return StyleDirection(
        targets=targets,
        monochrome=monochrome,
        protected=protected,
        avoid=avoid,
        constraints=tuple(profile.constraints),
        scenes=tuple(profile.scene_fit.suitable),
        is_personal=is_personal,
    )


def _scene_names(scenes: Sequence[SceneLabel]) -> str:
    return "、".join(SCENE_NAMES.get(scene, scene.value) for scene in scenes) or "其他"


def _detect_conflicts(
    a: StyleDirection,
    b: StyleDirection,
    a_name: str,
    b_name: str,
) -> list[_ConflictSpec]:
    conflicts: list[_ConflictSpec] = []
    ta, tb = a.targets, b.targets

    if a.monochrome != b.monochrome:
        mono_name = a_name if a.monochrome else b_name
        color_name = b_name if a.monochrome else a_name
        conflicts.append(
            _ConflictSpec(
                dimension="color.saturation",
                title="色彩饱和度",
                labels=("黑白单色", "保留色彩"),
                message=(
                    f"「{mono_name}」以黑白单色为核心，而「{color_name}」保留色彩，"
                    "直接平均会同时失去灰阶层次与色彩关系。"
                ),
                suggestion="将色彩维度来源设为单一风格；若混合则回退到中性饱和度并避免极端饱和。",
                fields=("saturation", "vibrance"),
                protection=(DirectionConstraint.AVOID_EXTREME_SATURATION,),
            )
        )
    elif (
        ta["saturation"] * tb["saturation"] < 0
        and min(abs(ta["saturation"]), abs(tb["saturation"])) >= 5.0
    ):
        low_name = a_name if ta["saturation"] < 0 else b_name
        high_name = b_name if ta["saturation"] < 0 else a_name
        conflicts.append(
            _ConflictSpec(
                dimension="color.saturation",
                title="色彩饱和度",
                labels=("低饱和", "高饱和"),
                message=(
                    f"「{low_name}」偏低饱和，「{high_name}」偏高饱和，取平均会丢失两者的色彩立场。"
                ),
                suggestion="按权重选择主导方，或将色彩来源固定为一种风格。",
                fields=("saturation", "vibrance"),
                protection=(DirectionConstraint.AVOID_EXTREME_SATURATION,),
            )
        )

    if (
        ta["temperature"] * tb["temperature"] < 0
        and min(abs(ta["temperature"]), abs(tb["temperature"])) >= 4.0
    ):
        cool_name = a_name if ta["temperature"] < 0 else b_name
        warm_name = b_name if ta["temperature"] < 0 else a_name
        conflicts.append(
            _ConflictSpec(
                dimension="color.temperature",
                title="色温方向",
                labels=("偏冷", "偏暖"),
                message=(
                    f"「{cool_name}」偏冷，「{warm_name}」偏暖，"
                    "混合平均会产生不伦不类的色温并可能引入偏色。"
                ),
                suggestion="选择主导色温，或回退中性白平衡并保留环境色。",
                fields=("temperature",),
                protection=(DirectionConstraint.AVOID_COLOR_CAST,),
            )
        )

    if ta["tint"] * tb["tint"] < 0 and min(abs(ta["tint"]), abs(tb["tint"])) >= 4.0:
        conflicts.append(
            _ConflictSpec(
                dimension="color.tint",
                title="色调方向",
                labels=("偏绿", "偏洋红"),
                message="两种风格的色调偏移方向相反，平均后仍可能留下明显偏色。",
                suggestion="固定色调来源，或回退中性并避免偏色。",
                fields=("tint",),
                protection=(DirectionConstraint.AVOID_COLOR_CAST,),
            )
        )

    if ta["contrast"] * tb["contrast"] < 0 and min(abs(ta["contrast"]), abs(tb["contrast"])) >= 5.0:
        soft_name = a_name if ta["contrast"] < 0 else b_name
        strong_name = b_name if ta["contrast"] < 0 else a_name
        conflicts.append(
            _ConflictSpec(
                dimension="tone.contrast",
                title="影调反差",
                labels=("柔和反差", "强烈反差"),
                message=(
                    f"「{soft_name}」追求柔和过渡，「{strong_name}」强调强烈明暗，"
                    "平均反差会削弱两者的影调性格。"
                ),
                suggestion="按权重或来源选择主导反差，冲突时避免极端反差。",
                fields=("contrast",),
                protection=(DirectionConstraint.AVOID_EXTREME_CONTRAST,),
            )
        )

    key_a = ta["shadows"] + ta["blacks"]
    key_b = tb["shadows"] + tb["blacks"]
    low_a = key_a <= -8.0 or DirectionConstraint.KEEP_LOW_KEY in a.constraints
    low_b = key_b <= -8.0 or DirectionConstraint.KEEP_LOW_KEY in b.constraints
    high_a = key_a >= 8.0
    high_b = key_b >= 8.0
    if (low_a and high_b) or (low_b and high_a):
        conflicts.append(
            _ConflictSpec(
                dimension="tone.key",
                title="明暗基调",
                labels=("低调", "高调"),
                message="一种风格倾向低调深影，另一种倾向高调明亮，平均会丢失明暗基调。",
                suggestion="选择主导基调，并保留暗部细节保护。",
                fields=("shadows", "blacks", "exposureEv"),
                protection=(DirectionConstraint.PRESERVE_SHADOW_DETAIL,),
            )
        )

    def protects_skin(direction: StyleDirection) -> bool:
        return (
            DirectionConstraint.PRESERVE_SKIN_TONE in direction.protected
            or PersonalAvoidEffect.UNNATURAL_SKIN in direction.avoid
        )

    def pushes_color(direction: StyleDirection) -> bool:
        t = direction.targets
        return abs(t["temperature"]) >= 8.0 or abs(t["tint"]) >= 5.0 or t["saturation"] >= 15.0

    if (protects_skin(a) and pushes_color(b)) or (protects_skin(b) and pushes_color(a)):
        guard = a_name if protects_skin(a) else b_name
        push = b_name if protects_skin(a) else a_name
        conflicts.append(
            _ConflictSpec(
                dimension="skin",
                title="肤色处理",
                labels=("保护肤色", "强烈色彩偏移"),
                message=(
                    f"「{guard}」要求保护肤色，「{push}」带有较强色彩偏移，全局偏移可能让肤色失真。"
                ),
                suggestion="肤色保护约束始终保留；色彩维度避免极端偏移。",
                fields=(),
                protection=(DirectionConstraint.PRESERVE_SKIN_TONE,),
            )
        )

    detail_pairs = (
        (
            DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
            "highlights",
            -12.0,
            "高光细节",
        ),
        (DirectionConstraint.PRESERVE_SHADOW_DETAIL, "shadows", -10.0, "暗部细节"),
    )
    for constraint, field, threshold, label in detail_pairs:
        a_guard = constraint in a.protected
        b_guard = constraint in b.protected
        if (a_guard and tb[field] <= threshold) or (b_guard and ta[field] <= threshold):
            guard = a_name if a_guard else b_name
            push = b_name if a_guard else a_name
            conflicts.append(
                _ConflictSpec(
                    dimension="detail",
                    title="细节保护",
                    labels=(f"保护{label}", f"强烈压暗{label}"),
                    message=(
                        f"「{guard}」要求保护{label}，「{push}」倾向强烈压暗，"
                        "平均会牺牲受保护的细节层次。"
                    ),
                    suggestion=f"{label}保护约束始终保留，避免把受保护区域压死。",
                    fields=("highlights", "shadows"),
                    protection=(constraint,),
                )
            )
            break

    if not (set(a.scenes) & set(b.scenes)):
        conflicts.append(
            _ConflictSpec(
                dimension="scene",
                title="场景适配",
                labels=(_scene_names(a.scenes), _scene_names(b.scenes)),
                message=(
                    f"「{a_name}」适用{_scene_names(a.scenes)}，"
                    f"「{b_name}」适用{_scene_names(b.scenes)}，两者几乎不重叠。"
                ),
                suggestion="确认目标照片场景；混合风格适用场景取并集，必要时按场景区分。",
                fields=(),
                protection=(),
            )
        )
    return conflicts


def _effective_resolution(
    spec: _ConflictSpec,
    sources: Mapping[MixDimension, MixSource],
    resolutions: Mapping[str, ConflictResolution],
) -> tuple[ConflictResolution, _ResolvedBy]:
    choice = resolutions.get(spec.dimension, "auto")
    if choice in {"a", "b", "neutral"}:
        return choice, "user"
    parent_source = sources.get(_CONFLICT_PARENT[spec.dimension], "blend")
    if parent_source in {"a", "b"}:
        return parent_source, "source"
    return "neutral", "protection"


def _mix_targets(
    a: StyleDirection,
    b: StyleDirection,
    *,
    weight: int,
    sources: Mapping[MixDimension, MixSource],
    conflict_fields: Mapping[str, tuple[ConflictResolution, str]],
    overrides: Mapping[str, float],
) -> dict[str, float]:
    ratio = weight / 100.0
    targets: dict[str, float] = {}
    for field in PERSONAL_TARGET_FIELDS:
        if field in conflict_fields:
            resolution, _ = conflict_fields[field]
            if resolution == "a":
                value = a.targets[field]
            elif resolution == "b":
                value = b.targets[field]
            else:
                value = 0.0
        else:
            source = sources.get(_TARGET_DIMENSION[field], "blend")
            if source == "a":
                value = a.targets[field]
            elif source == "b":
                value = b.targets[field]
            else:
                value = a.targets[field] * ratio + b.targets[field] * (1.0 - ratio)
        value = round(_clamp(value, -100.0, 100.0), 2)
        if abs(value) >= 0.5:
            targets[field] = value
    for field, value in overrides.items():
        targets[field] = round(_clamp(value, -100.0, 100.0), 2)
    return targets


def _select_text(
    a_text: str,
    b_text: str,
    source: MixSource,
    weight: int,
    a_name: str,
    b_name: str,
) -> str:
    if source == "a":
        return _cap(a_text)
    if source == "b":
        return _cap(b_text)
    if weight >= 100:
        return _cap(a_text)
    if weight <= 0:
        return _cap(b_text)
    if weight == 50:
        return _cap(f"{a_text}；{b_text}")
    if weight > 50:
        return _cap(f"{a_text}；兼顾{b_name}：{b_text}")
    return _cap(f"{b_text}；兼顾{a_name}：{a_text}")


def _dim_summary(profile: StyleProfile, dimension: MixDimension) -> str:
    if dimension == "color":
        return profile.color.tendency
    if dimension == "tone":
        return profile.light.contrast
    if dimension == "light":
        return profile.light.expression
    if dimension == "texture":
        return profile.texture.grain
    if dimension == "composition":
        return profile.composition.geometry
    return _scene_names(profile.scene_fit.suitable)


def _envelope(
    a: StyleProfile,
    b: StyleProfile,
    targets: Mapping[str, float],
) -> StyleEnvelope:
    values: dict[str, float] = {}
    for field in StyleEnvelope.model_fields:
        values[field] = max(
            float(getattr(a.envelope, field)),
            float(getattr(b.envelope, field)),
        )
    if targets.get("saturation", 0.0) <= -50.0:
        values["saturation"] = 100.0
        values["vibrance"] = max(values["vibrance"], 40.0)
    for field in ("saturation", "contrast", "grain"):
        floor = min(abs(targets.get(field, 0.0)) + 5.0, 100.0)
        values[field] = max(values[field], floor)
    return StyleEnvelope.model_validate(values)


def _confidence(a: StyleProfile, b: StyleProfile) -> float:
    ca = a.personal.confidence if isinstance(a, PersonalStyleProfile) else 0.85
    cb = b.personal.confidence if isinstance(b, PersonalStyleProfile) else 0.85
    return round((ca + cb) / 2.0, 3)


def mix_styles(
    a: StyleProfile,
    b: StyleProfile,
    *,
    weight: int = 50,
    sources: Mapping[MixDimension, MixSource] | None = None,
    resolutions: Mapping[str, ConflictResolution] | None = None,
    style_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    target_overrides: Mapping[str, float] | None = None,
    avoid_overrides: Sequence[PersonalAvoidEffect] | None = None,
    note: str | None = None,
) -> MixOutcome:
    """Mix two archives into one personal-style snapshot with full provenance."""

    weight = int(_clamp(weight, 0, 100))
    normalized: dict[MixDimension, MixSource] = {
        dimension: (sources or {}).get(dimension, "blend") for dimension in MIX_DIMENSIONS
    }
    resolutions = dict(resolutions or {})
    overrides = dict(target_overrides or {})
    a_dir = derive_direction(a)
    b_dir = derive_direction(b)
    specs = _detect_conflicts(a_dir, b_dir, a.name, b.name)

    resolved: dict[str, tuple[ConflictResolution, _ResolvedBy]] = {}
    conflict_fields: dict[str, tuple[ConflictResolution, _ResolvedBy]] = {}
    conflict_protections: list[DirectionConstraint] = []
    conflicts: list[StyleMixConflict] = []
    for spec in specs:
        resolution, resolved_by = _effective_resolution(spec, normalized, resolutions)
        resolved[spec.dimension] = (resolution, resolved_by)
        for field in spec.fields:
            conflict_fields[field] = (resolution, resolved_by)
        conflict_protections.extend(spec.protection)
        conflicts.append(
            StyleMixConflict(
                dimension=spec.dimension,
                title=spec.title,
                labels=spec.labels,
                message=spec.message,
                suggestion=spec.suggestion,
                resolution=resolution,
                resolved_by=resolved_by,
            )
        )

    targets = _mix_targets(
        a_dir,
        b_dir,
        weight=weight,
        sources=normalized,
        conflict_fields=conflict_fields,
        overrides=overrides,
    )
    monochrome = targets.get("saturation", 0.0) <= -50.0

    avoid = tuple(
        dict.fromkeys(
            (
                *(avoid_overrides if avoid_overrides is not None else ()),
                *(a_dir.avoid if avoid_overrides is None else ()),
                *(b_dir.avoid if avoid_overrides is None else ()),
            )
        )
    )[:8]
    avoid_protections = [_AVOID_TO_CONSTRAINT[effect] for effect in avoid]

    protection_floor = tuple(
        dict.fromkeys(
            (
                *a_dir.protected,
                *b_dir.protected,
                *(item for item in a_dir.constraints if item in _PROTECTION_CONSTRAINTS),
                *(item for item in b_dir.constraints if item in _PROTECTION_CONSTRAINTS),
                *avoid_protections,
                *conflict_protections,
            )
        )
    )
    constraint_source = normalized.get("color", "blend")
    if constraint_source == "a":
        base_constraints = a_dir.constraints
    elif constraint_source == "b":
        base_constraints = b_dir.constraints
    else:
        base_constraints = (*a_dir.constraints, *b_dir.constraints)
    constraints = tuple(dict.fromkeys((*base_constraints, *protection_floor)))[:11]
    protected = tuple(item for item in protection_floor if item in _PROTECTION_CONSTRAINTS)[:11]

    def sel(dimension: MixDimension, a_text: str, b_text: str) -> str:
        return _select_text(a_text, b_text, normalized[dimension], weight, a.name, b.name)

    color = StyleColorTraits(
        tendency=(
            "黑白影调，色彩完全去饱和"
            if monochrome
            else sel("color", a.color.tendency, b.color.tendency)
        ),
        relationships=sel("color", a.color.relationships, b.color.relationships),
        saturation=(
            "去饱和至单色，保留灰阶层次"
            if monochrome
            else sel("color", a.color.saturation, b.color.saturation)
        ),
    )
    light = StyleLightTraits(
        contrast=sel("tone", a.light.contrast, b.light.contrast),
        shadows=sel("tone", a.light.shadows, b.light.shadows),
        highlights=sel("tone", a.light.highlights, b.light.highlights),
        expression=sel("light", a.light.expression, b.light.expression),
    )
    texture = StyleTextureTraits(
        grain=sel("texture", a.texture.grain, b.texture.grain),
        sharpness=sel("texture", a.texture.sharpness, b.texture.sharpness),
        detail=sel("texture", a.texture.detail, b.texture.detail),
    )
    composition = StyleCompositionTraits(
        space=sel("composition", a.composition.space, b.composition.space),
        geometry=sel("composition", a.composition.geometry, b.composition.geometry),
        negative_space=sel(
            "composition", a.composition.negative_space, b.composition.negative_space
        ),
        subject_relation=sel(
            "composition", a.composition.subject_relation, b.composition.subject_relation
        ),
    )
    scene_source = normalized["scene"]
    if scene_source == "a":
        suitable = a_dir.scenes
    elif scene_source == "b":
        suitable = b_dir.scenes
    else:
        suitable = tuple(dict.fromkeys((*a_dir.scenes, *b_dir.scenes)))[:9]
    suitable = suitable or (SceneLabel.OTHER,)
    scene_fit = StyleSceneFit(
        suitable=suitable,
        suitable_notes=sel("scene", a.scene_fit.suitable_notes, b.scene_fit.suitable_notes),
        unsuitable_notes=sel("scene", a.scene_fit.unsuitable_notes, b.scene_fit.unsuitable_notes),
    )

    dimensions = tuple(
        StyleMixDimensionPlan(
            dimension=dimension,
            title=_DIMENSION_TITLES[dimension],
            source=normalized[dimension],
            description=_cap(_dim_summary_result(a, b, dimension, normalized, weight)),
            from_a=_cap(_dim_summary(a, dimension)),
            from_b=_cap(_dim_summary(b, dimension)),
        )
        for dimension in MIX_DIMENSIONS
    )

    mixed_name = _cap(name or f"{a.name} × {b.name}")[:80]
    color_desc = color.tendency
    tone_desc = light.contrast
    texture_desc = texture.grain
    mixed_description = _cap(
        description
        or (
            f"由「{a.name}」与「{b.name}」按 {weight}% / {100 - weight}% 混合。"
            f"色彩：{color_desc}；影调：{tone_desc}；质感：{texture_desc}。"
        )
    )
    engine_style = a.engine_style if weight >= 50 else b.engine_style
    default_strength = round(
        _clamp(
            a.default_strength * (weight / 100.0) + b.default_strength * (1.0 - weight / 100.0),
            0.0,
            1.0,
        ),
        3,
    )
    envelope = _envelope(a, b, targets)

    combination_rules = tuple(
        _cap(rule)
        for rule in (
            f"权重：风格 A {weight}%，风格 B {100 - weight}%。",
            "连续数值仅在混合维度且无冲突时按权重插值。",
            "冲突维度按用户选择、特征来源或中性保护回退处理，不取平均。",
            "保护约束取两种风格并集，不受权重平均影响。",
            *(
                f"{_DIMENSION_TITLES[dimension]}来源：{_source_label(normalized[dimension])}。"
                for dimension in MIX_DIMENSIONS
            ),
        )
    )[:12]

    provenance = StyleMixProvenance(
        style_a_id=a.id,
        style_a_version=a.version,
        style_a_name=a.name,
        style_b_id=b.id,
        style_b_version=b.version,
        style_b_name=b.name,
        weight=weight,
        sources=normalized,
        resolutions={dimension: value[0] for dimension, value in resolved.items()},
        combination_rules=combination_rules,
        user_overrides={
            **({"name": name} if name else {}),
            **({"description": description} if description else {}),
            **({"targets": dict(overrides)} if overrides else {}),
            **(
                {"avoid": [effect.value for effect in avoid_overrides]}
                if avoid_overrides is not None
                else {}
            ),
        },
    )

    user_override_markers: dict[str, object] = {
        "mix": provenance.model_dump(mode="json", by_alias=True)
    }
    personal_overrides: list[str] = []
    if name:
        user_override_markers["name"] = name
    if description:
        user_override_markers["description"] = description
    if overrides:
        user_override_markers["personal.targets"] = dict(overrides)
        personal_overrides.append("personal.targets")
    if avoid_overrides is not None:
        user_override_markers["personal.avoid"] = [effect.value for effect in avoid_overrides]
        personal_overrides.append("personal.avoid")

    personal = PersonalStyleHints(
        source=PersonalStyleSource.MIXED,
        confidence=_confidence(a, b),
        targets=targets,
        protected=protected,
        avoid=avoid,
        user_overrides=tuple(personal_overrides),
    )
    profile = PersonalStyleProfile(
        id=style_id or f"personal_{uuid4().hex[:12]}",
        version="1.0",
        name=mixed_name,
        description=mixed_description,
        philosophy=(
            f"混合风格：结合「{a.name}」与「{b.name}」的视觉语言，"
            "按维度来源与权重组合，保护约束取并集。"
        ),
        color=color,
        light=light,
        composition=composition,
        texture=texture,
        scene_fit=scene_fit,
        post_strategy=(
            "通过既有风格决策链把混合特征转化为有界调整；"
            "保护约束优先，冲突维度按用户选择或中性处理。"
        ),
        capture_techniques=(f"来源风格：{a.name}、{b.name}。混合不创造拍摄时不存在的光线或结构。"),
        constraints=constraints,
        preserve_notes=(
            "保护约束来自两种来源风格的并集，不被权重平均；来源与规则记录在版本溯源中。"
        ),
        sources=(
            StyleSource(
                title=_cap(f"风格混合：{a.name} × {b.name}")[:120],
                license="用户私有，不用于模型训练",
            ),
            *a.sources[:3],
            *b.sources[:3],
        )[:8],
        engine_style=engine_style,
        envelope=envelope,
        default_strength=default_strength,
        enabled=False,
        personal=personal,
    )
    definition = PersonalStyleDefinition(user_overrides=user_override_markers, note=note)

    protections = tuple(_CONSTRAINT_LABELS[item] for item in protected)
    limitations: list[str] = []
    if conflicts:
        limitations.append(f"检测到 {len(conflicts)} 处风格冲突，已按优先级处理而非平均。")
    if not a_dir.is_personal or not b_dir.is_personal:
        limitations.append("大师/流派来源的数值方向由档案文字启发式推导，仅供混合参考。")
    if monochrome:
        limitations.append("混合结果为黑白单色，色彩维度以灰阶层次为主。")
    if "scene" in resolved:
        limitations.append("两种风格适用场景几乎不重叠，已取并集，建议按目标照片场景确认。")

    summary = _cap(
        f"混合概览（A {weight}% / B {100 - weight}%）：\n"
        f"色彩：{color_desc}\n"
        f"影调：{tone_desc}\n"
        f"光线：{light.expression}\n"
        f"质感：{texture_desc}\n"
        f"适用场景：{_scene_names(suitable)}\n"
        f"保护约束：{'、'.join(protections) if protections else '保留自然过渡'}"
    )

    return MixOutcome(
        profile=profile,
        definition=definition,
        weight=weight,
        sources=normalized,
        dimensions=dimensions,
        conflicts=tuple(conflicts),
        protections=protections,
        summary=summary,
        limitations=tuple(_cap(item) for item in limitations),
        provenance=provenance,
    )


def _source_label(source: MixSource) -> str:
    return {"a": "风格 A", "b": "风格 B", "blend": "混合"}[source]


def _dim_summary_result(
    a: StyleProfile,
    b: StyleProfile,
    dimension: MixDimension,
    sources: Mapping[MixDimension, MixSource],
    weight: int,
) -> str:
    return _select_text(
        _dim_summary(a, dimension),
        _dim_summary(b, dimension),
        sources[dimension],
        weight,
        a.name,
        b.name,
    )


__all__ = [
    "MIX_SCHEMA_VERSION",
    "MixOutcome",
    "StyleDirection",
    "derive_direction",
    "mix_styles",
]
