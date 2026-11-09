"""Scene-aware fusion of per-photo Visual DNA features.

The fusion deliberately avoids taking arithmetic means across unrelated photos:
contrast, saturation, light, texture, and cast are aggregated as weighted
directions, scenes keep their own targets, and contradictory preferences are
reported as conflicts instead of being flattened into a middle value.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.ai.contracts import SceneLabel
from app.models.personal_style import PersonalAvoidEffect
from app.models.photographer import DirectionConstraint, StyleEnvelope
from app.models.style_fusion import (
    PersonalStyleFusionConflict,
    PersonalStyleFusionScene,
    PersonalStyleFusionSection,
)
from app.models.style_profile import (
    StyleColorTraits,
    StyleCompositionTraits,
    StyleLightTraits,
    StyleSceneFit,
    StyleTextureTraits,
)
from app.models.visual_dna import FeatureSeverity, PhotoVisualFeatures
from app.styles.vocabulary import SCENE_NAMES

WARNING_ANOMALY_WEIGHT = 0.6
MIN_GLOBAL_PHOTOS = 3
PREFERRED_GLOBAL_PHOTOS = 5
STABLE_SUPPORT = 0.70
CANDIDATE_SUPPORT = 0.50
CONFLICT_SUPPORT = 0.30

_SCENE_LABELS = SCENE_NAMES
_HARMONY_LABELS = {
    "harmonious": "色彩关系和谐",
    "moderate": "色彩关系自然",
    "clashing": "色彩对比强烈",
    "unknown": "色彩关系待确认",
}
_DIRECTION_LABELS = {
    "front": "顺光",
    "side": "侧光",
    "back": "逆光",
    "side_back": "侧逆光",
    "diffuse": "漫射光",
    "overcast": "阴天散射光",
    "artificial": "人工光",
    "mixed": "混合光",
    "unknown": "光线方向待确认",
}
_BALANCE_LABELS = {
    "balanced": "平衡",
    "moderate": "较为平衡",
    "unbalanced": "不平衡",
    "unknown": "待确认",
}
_NEGATIVE_SPACE_LABELS = {
    "low": "较少",
    "moderate": "适中",
    "high": "较多",
    "unknown": "待确认",
}
_SUBJECT_POSITION_LABELS = {
    "left": "左侧",
    "right": "右侧",
    "center": "画面中央",
    "top": "上部",
    "bottom": "下部",
    "unknown": "待确认",
}
_AVOID_TEXT = {
    PersonalAvoidEffect.OVERSATURATED: "避免过饱和",
    PersonalAvoidEffect.CRUSHED_BLACKS: "避免压黑暗部",
    PersonalAvoidEffect.CLIPPED_HIGHLIGHTS: "避免高光溢出",
    PersonalAvoidEffect.COLOR_CAST: "避免明显偏色",
    PersonalAvoidEffect.UNNATURAL_SKIN: "避免肤色不自然",
    PersonalAvoidEffect.HEAVY_FILTER: "避免明显滤镜感",
    PersonalAvoidEffect.OVER_SHARPENED: "避免过度锐化",
    PersonalAvoidEffect.FLAT_CONTRAST: "避免反差过强",
}
_CONSTRAINT_TEXT = {
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


@dataclass(frozen=True, slots=True)
class FusionPhoto:
    reference_id: str
    image_id: str | None
    features: PhotoVisualFeatures


@dataclass(frozen=True, slots=True)
class FusionOutcome:
    color: StyleColorTraits
    light: StyleLightTraits
    composition: StyleCompositionTraits
    texture: StyleTextureTraits
    scene_fit: StyleSceneFit
    constraints: tuple[DirectionConstraint, ...]
    protected: tuple[DirectionConstraint, ...]
    envelope: StyleEnvelope
    targets: dict[str, float]
    scene_targets: dict[SceneLabel, dict[str, float]]
    stability: dict[str, float]
    confidence: float
    sample_count: int
    anomaly_count: int
    default_strength: float
    summary: str
    sections: tuple[PersonalStyleFusionSection, ...]
    conflicts: tuple[PersonalStyleFusionConflict, ...]
    scenes: tuple[PersonalStyleFusionScene, ...]
    occasional: tuple[str, ...]
    limitations: tuple[str, ...]


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _round(value: float) -> float:
    return round(float(value), 2) + 0.0


def _has_warning(features: PhotoVisualFeatures) -> bool:
    return any(anomaly.severity is FeatureSeverity.WARNING for anomaly in features.anomalies)


def _weight(features: PhotoVisualFeatures) -> float:
    base = max(features.overall_confidence, 0.05)
    return base * (WARNING_ANOMALY_WEIGHT if _has_warning(features) else 1.0)


def fusion_weight(features: PhotoVisualFeatures) -> float:
    """Relative contribution of one photo, after the anomaly penalty."""

    return _weight(features)


def _weighted_median(values: Iterable[tuple[float, float]]) -> float:
    pairs = sorted((value, weight) for value, weight in values if weight > 0.0)
    if not pairs:
        return 0.0
    total = sum(weight for _, weight in pairs)
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= total / 2.0:
            return float(value)
    return float(pairs[-1][0])


def _shares(labels: Iterable[tuple[str, float]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    total = 0.0
    for label, weight in labels:
        totals[label] += weight
        total += weight
    if total <= 0.0:
        return {}
    return {label: value / total for label, value in totals.items()}


def _top_label(shares: dict[str, float]) -> str:
    if not shares:
        return "unknown"
    return max(shares.items(), key=lambda item: (item[1], item[0]))[0]


def _support(shares: dict[str, float], label: str) -> float:
    return shares.get(label, 0.0)


def _share_text(share: float, label: str) -> str:
    return f"{share:.0%} 的照片支持{label}"


def _minority_messages(
    shares: dict[str, float],
    labels: dict[str, str],
    dimension: str,
) -> list[str]:
    top = _top_label(shares)
    messages: list[str] = []
    for label, support in shares.items():
        if label == top or support >= CONFLICT_SUPPORT or support < 0.10:
            continue
        messages.append(
            f"{dimension}中少数照片呈现{labels.get(label, label)}"
            f"（{support:.0%}），视为个别特征而非稳定偏好。"
        )
    return messages


def _saturation_label(value: float) -> str:
    if value <= 0.25:
        return "lower"
    if value >= 0.50:
        return "higher"
    return "neutral"


def _contrast_label(value: float) -> str:
    if value <= 0.45:
        return "soft"
    if value >= 0.75:
        return "strong"
    return "moderate"


def _temperature_label(value: float) -> str:
    if value <= -0.08:
        return "cool"
    if value >= 0.08:
        return "warm"
    return "neutral"


def _tint_label(value: float) -> str:
    if value <= -0.08:
        return "green"
    if value >= 0.08:
        return "magenta"
    return "neutral"


def _light_label(value: float) -> str:
    if value >= 0.65:
        return "soft"
    if value <= 0.45:
        return "directional"
    return "balanced"


def _texture_label(sharpness: float, noise: float) -> str:
    if noise >= 0.35:
        return "grainy"
    if sharpness >= 0.55:
        return "crisp"
    if sharpness <= 0.08:
        return "soft_detail"
    return "natural"


def _key_label(features: PhotoVisualFeatures) -> str:
    if features.tone.low_key:
        return "low"
    if features.tone.high_key:
        return "high"
    return "normal"


_SATURATION_TEXT = {
    "lower": "低饱和",
    "neutral": "中等饱和",
    "higher": "高饱和",
}
_CONTRAST_TEXT = {
    "soft": "柔和反差",
    "moderate": "中等反差",
    "strong": "强烈反差",
}
_TEMPERATURE_TEXT = {
    "cool": "整体偏冷",
    "neutral": "色温中性",
    "warm": "整体偏暖",
}
_TINT_TEXT = {
    "green": "轻微偏绿",
    "neutral": "色调中性",
    "magenta": "轻微偏洋红",
}
_LIGHT_TEXT = {
    "soft": "柔和漫射光",
    "balanced": "柔和程度中等",
    "directional": "方向性较强",
}
_KEY_TEXT = {
    "low": "低调画面",
    "normal": "中间调为主",
    "high": "高调画面",
}
_TEXTURE_TEXT = {
    "grainy": "颗粒感较明显",
    "crisp": "清晰锐利",
    "soft_detail": "画面柔和、细节较少",
    "natural": "自然质感",
}


_CONFLICT_TEXT = {
    "color.saturation": ("色彩饱和度", "低饱和", "高饱和"),
    "color.temperature": ("色温", "偏冷", "偏暖"),
    "color.tint": ("色调", "偏绿", "偏洋红"),
    "tone.contrast": ("影调反差", "柔和", "强烈"),
    "tone.key": ("明暗基调", "低调", "高调"),
    "light.softness": ("光线柔和度", "柔和漫射", "方向性"),
}


def _conflict_matches(
    dimension: str,
    shares: dict[str, float],
    first: str,
    second: str,
) -> PersonalStyleFusionConflict | None:
    left = _support(shares, first)
    right = _support(shares, second)
    if left < CONFLICT_SUPPORT or right < CONFLICT_SUPPORT:
        return None
    title, first_text, second_text = _CONFLICT_TEXT[dimension]
    return PersonalStyleFusionConflict(
        dimension=dimension,
        labels=(first, second),
        support=(round(left, 3), round(right, 3)),
        message=(
            f"检测到{title}存在两种稳定倾向（{first_text} {left:.0%}，"
            f"{second_text} {right:.0%}），未取平均，建议按场景区分或混合使用。"
        ),
    )


def _numeric_targets(
    *,
    saturation_median: float,
    temperature_median: float,
    tint_median: float,
    contrast_median: float,
    noise_median: float,
    sharpness_median: float,
    shares: dict[str, float],
    conflict_dimensions: frozenset[str],
) -> dict[str, float]:
    targets: dict[str, float] = {}
    monochrome = shares.get("monochrome", 0.0) >= STABLE_SUPPORT
    if monochrome:
        targets["saturation"] = -100.0
        targets["vibrance"] = 0.0
    else:
        if "color.saturation" not in conflict_dimensions:
            value = _round(_clamp((saturation_median - 0.35) * 60.0, -18.0, 18.0))
            if abs(value) >= 0.5:
                targets["saturation"] = value
        if "color.temperature" not in conflict_dimensions:
            value = _round(_clamp(temperature_median * 60.0, -12.0, 12.0))
            if abs(value) >= 0.5:
                targets["temperature"] = value
        if "color.tint" not in conflict_dimensions:
            value = _round(_clamp(tint_median * 50.0, -8.0, 8.0))
            if abs(value) >= 0.5:
                targets["tint"] = value
    if "tone.contrast" not in conflict_dimensions:
        value = _round(_clamp((contrast_median - 0.50) * 40.0, -20.0, 20.0))
        if abs(value) >= 0.5:
            targets["contrast"] = value
    if shares.get("crisp", 0.0) >= CANDIDATE_SUPPORT:
        targets["clarity"] = _round(_clamp((sharpness_median - 0.50) * 20.0, 3.0, 10.0))
    elif shares.get("soft_detail", 0.0) >= CANDIDATE_SUPPORT:
        targets["clarity"] = _round(_clamp((sharpness_median - 0.50) * 20.0, -8.0, -2.0))
    if shares.get("grainy", 0.0) >= CANDIDATE_SUPPORT:
        targets["grain"] = _round(_clamp((noise_median - 0.20) * 40.0, 3.0, 15.0))
    return targets


def _envelope_for(targets: dict[str, float], *, monochrome: bool) -> StyleEnvelope:
    if monochrome:
        return StyleEnvelope(saturation=100.0, vibrance=40.0, grain=15.0)
    saturation = abs(targets.get("saturation", 0.0)) + 5.0
    contrast = abs(targets.get("contrast", 0.0)) + 5.0
    grain = abs(targets.get("grain", 0.0)) + 5.0
    return StyleEnvelope(
        saturation=_clamp(saturation, 25.0, 80.0),
        vibrance=20.0,
        contrast=_clamp(contrast, 25.0, 60.0),
        grain=_clamp(grain, 15.0, 30.0),
    )


def _avoid_constraints(avoid: Sequence[PersonalAvoidEffect]) -> list[DirectionConstraint]:
    mapping = {
        PersonalAvoidEffect.OVERSATURATED: DirectionConstraint.AVOID_EXTREME_SATURATION,
        PersonalAvoidEffect.CRUSHED_BLACKS: DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        PersonalAvoidEffect.CLIPPED_HIGHLIGHTS: DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        PersonalAvoidEffect.COLOR_CAST: DirectionConstraint.AVOID_COLOR_CAST,
        PersonalAvoidEffect.UNNATURAL_SKIN: DirectionConstraint.PRESERVE_SKIN_TONE,
        PersonalAvoidEffect.HEAVY_FILTER: DirectionConstraint.NATURAL_LOOK,
        PersonalAvoidEffect.OVER_SHARPENED: DirectionConstraint.NATURAL_LOOK,
        PersonalAvoidEffect.FLAT_CONTRAST: DirectionConstraint.AVOID_EXTREME_CONTRAST,
    }
    return [mapping[effect] for effect in avoid]


def _constraints(
    photos: Sequence[tuple[FusionPhoto, float]],
    *,
    avoid: Sequence[PersonalAvoidEffect],
    conflicts: Sequence[PersonalStyleFusionConflict],
) -> tuple[DirectionConstraint, ...]:
    total = sum(weight for _, weight in photos) or 1.0
    portrait_share = sum(
        weight
        for photo, weight in photos
        if photo.features.scene.primary is SceneLabel.PORTRAIT
    ) / total
    highlight_rate = sum(
        weight
        for photo, weight in photos
        if any(item.code == "highlights_clipped" for item in photo.features.anomalies)
    ) / total
    shadow_rate = sum(
        weight
        for photo, weight in photos
        if any(item.code == "shadows_clipped" for item in photo.features.anomalies)
    ) / total

    result: list[DirectionConstraint] = []
    if portrait_share >= CONFLICT_SUPPORT:
        result.append(DirectionConstraint.PRESERVE_SKIN_TONE)
    if highlight_rate >= CONFLICT_SUPPORT:
        result.append(DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL)
    if shadow_rate >= CONFLICT_SUPPORT:
        result.append(DirectionConstraint.PRESERVE_SHADOW_DETAIL)
    conflict_dimensions = {conflict.dimension for conflict in conflicts}
    if "color.saturation" in conflict_dimensions:
        result.append(DirectionConstraint.AVOID_EXTREME_SATURATION)
    if "tone.contrast" in conflict_dimensions:
        result.append(DirectionConstraint.AVOID_EXTREME_CONTRAST)
    if {"color.temperature", "color.tint"} & conflict_dimensions:
        result.append(DirectionConstraint.AVOID_COLOR_CAST)
    result.extend(_avoid_constraints(avoid))
    return tuple(dict.fromkeys(result))[:11]


def _protected(constraints: Sequence[DirectionConstraint]) -> tuple[DirectionConstraint, ...]:
    protected = {
        DirectionConstraint.PRESERVE_SKIN_TONE,
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
        DirectionConstraint.PRESERVE_SHADOW_DETAIL,
        DirectionConstraint.MAINTAIN_NEUTRALITY,
        DirectionConstraint.AVOID_COLOR_CAST,
    }
    return tuple(item for item in constraints if item in protected)


def _scene_description(photos: Sequence[tuple[FusionPhoto, float]]) -> str:
    def median(getter: Callable[[PhotoVisualFeatures], float]) -> float:
        return _weighted_median(
            (getter(photo.features), weight) for photo, weight in photos
        )

    saturation = _saturation_label(median(lambda features: features.color.saturation_mean))
    contrast = _contrast_label(median(lambda features: features.tone.contrast_strength))
    light = _light_label(median(lambda features: features.light.softness))
    return (
        f"{_SATURATION_TEXT[saturation]}、{_CONTRAST_TEXT[contrast]}、"
        f"{_LIGHT_TEXT[light]}"
    )


def _scene_summaries(
    groups: dict[SceneLabel, list[tuple[FusionPhoto, float]]],
    *,
    total_weight: float,
) -> tuple[PersonalStyleFusionScene, ...]:
    scenes: list[PersonalStyleFusionScene] = []
    ordered = sorted(
        groups.items(),
        key=lambda item: (-sum(weight for _, weight in item[1]), item[0].value),
    )
    for scene, photos in ordered:
        weight = sum(item_weight for _, item_weight in photos)
        confidence = sum(
            photo.features.overall_confidence * item_weight for photo, item_weight in photos
        ) / (weight or 1.0)
        share = weight / (total_weight or 1.0)
        scenes.append(
            PersonalStyleFusionScene(
                scene=scene,
                photo_count=len(photos),
                share=round(share, 3),
                confidence=round(confidence, 3),
                description=_scene_description(photos),
            )
        )
    return tuple(scenes)


def _composition_traits(
    photos: Sequence[tuple[FusionPhoto, float]],
) -> StyleCompositionTraits:
    def mode(getter: Callable[[PhotoVisualFeatures], str]) -> str:
        shares = _shares((getter(photo.features), weight) for photo, weight in photos)
        return _top_label(shares)

    balance = _BALANCE_LABELS[mode(lambda features: features.composition.balance.value)]
    negative_space = _NEGATIVE_SPACE_LABELS[
        mode(lambda features: features.composition.negative_space.value)
    ]
    subject_position = _SUBJECT_POSITION_LABELS[
        mode(lambda features: features.composition.subject_position.value)
    ]
    return StyleCompositionTraits(
        space=f"负空间以{negative_space}为主。",
        geometry=f"构图平衡以{balance}为主。",
        negative_space=f"负空间{negative_space}。",
        subject_relation=f"主体多位于{subject_position}。",
    )


def _sections(
    *,
    color_description: str,
    tone_description: str,
    light_description: str,
    texture_description: str,
    scene_description: str,
    constraint_description: str,
    evidence: dict[str, tuple[str, ...]],
) -> tuple[PersonalStyleFusionSection, ...]:
    return (
        PersonalStyleFusionSection(
            key="color",
            title="色彩",
            description=color_description,
            evidence=evidence.get("color", ()),
        ),
        PersonalStyleFusionSection(
            key="tone",
            title="影调",
            description=tone_description,
            evidence=evidence.get("tone", ()),
        ),
        PersonalStyleFusionSection(
            key="light",
            title="光线",
            description=light_description,
            evidence=evidence.get("light", ()),
        ),
        PersonalStyleFusionSection(
            key="texture",
            title="质感",
            description=texture_description,
            evidence=evidence.get("texture", ()),
        ),
        PersonalStyleFusionSection(
            key="scene",
            title="场景",
            description=scene_description,
            evidence=evidence.get("scene", ()),
        ),
        PersonalStyleFusionSection(
            key="constraints",
            title="处理原则",
            description=constraint_description,
            evidence=evidence.get("constraints", ()),
        ),
    )


def fuse_photo_features(
    photos: Sequence[FusionPhoto],
    *,
    avoid: Sequence[PersonalAvoidEffect] = (),
) -> FusionOutcome:
    """Fuse per-photo features into one personal-style candidate."""

    if not photos:
        raise ValueError("at least one photo feature is required for fusion")
    weighted: list[tuple[FusionPhoto, float]] = [
        (photo, _weight(photo.features)) for photo in photos
    ]
    total_weight = sum(weight for _, weight in weighted)
    scene_groups: dict[SceneLabel, list[tuple[FusionPhoto, float]]] = defaultdict(list)
    for photo, weight in weighted:
        scene_groups[photo.features.scene.primary].append((photo, weight))
    scene_shares = {
        scene: sum(weight for _, weight in group) / (total_weight or 1.0)
        for scene, group in scene_groups.items()
    }
    scene_stability = max(scene_shares.values()) if scene_shares else 0.0

    def medians(
        subset: Sequence[tuple[FusionPhoto, float]],
    ) -> dict[str, float]:
        return {
            "saturation": _weighted_median(
                (photo.features.color.saturation_mean, weight) for photo, weight in subset
            ),
            "temperature": _weighted_median(
                (photo.features.color.temperature_offset, weight) for photo, weight in subset
            ),
            "tint": _weighted_median(
                (photo.features.color.tint_offset, weight) for photo, weight in subset
            ),
            "contrast": _weighted_median(
                (photo.features.tone.contrast_strength, weight) for photo, weight in subset
            ),
            "noise": _weighted_median(
                (photo.features.texture.noise, weight) for photo, weight in subset
            ),
            "sharpness": _weighted_median(
                (photo.features.texture.sharpness, weight) for photo, weight in subset
            ),
            "softness": _weighted_median(
                (photo.features.light.softness, weight) for photo, weight in subset
            ),
        }

    global_medians = medians(weighted)
    saturation_shares = _shares(
        (_saturation_label(photo.features.color.saturation_mean), weight)
        for photo, weight in weighted
    )
    contrast_shares = _shares(
        (_contrast_label(photo.features.tone.contrast_strength), weight)
        for photo, weight in weighted
    )
    temperature_shares = _shares(
        (_temperature_label(photo.features.color.temperature_offset), weight)
        for photo, weight in weighted
    )
    tint_shares = _shares(
        (_tint_label(photo.features.color.tint_offset), weight)
        for photo, weight in weighted
    )
    light_shares = _shares(
        (_light_label(photo.features.light.softness), weight)
        for photo, weight in weighted
    )
    key_shares = _shares((_key_label(photo.features), weight) for photo, weight in weighted)
    texture_shares = _shares(
        (
            _texture_label(
                photo.features.texture.sharpness,
                photo.features.texture.noise,
            ),
            weight,
        )
        for photo, weight in weighted
    )
    monochrome_share = sum(
        weight for photo, weight in weighted if photo.features.color.monochrome
    ) / (total_weight or 1.0)

    conflicts: list[PersonalStyleFusionConflict] = []
    for conflict in (
        _conflict_matches("color.saturation", saturation_shares, "lower", "higher"),
        _conflict_matches("color.temperature", temperature_shares, "cool", "warm"),
        _conflict_matches("color.tint", tint_shares, "green", "magenta"),
        _conflict_matches("tone.contrast", contrast_shares, "soft", "strong"),
        _conflict_matches("tone.key", key_shares, "low", "high"),
        _conflict_matches("light.softness", light_shares, "soft", "directional"),
    ):
        if conflict is not None:
            conflicts.append(conflict)
    conflict_dimensions = frozenset(conflict.dimension for conflict in conflicts)

    targets = _numeric_targets(
        saturation_median=global_medians["saturation"],
        temperature_median=global_medians["temperature"],
        tint_median=global_medians["tint"],
        contrast_median=global_medians["contrast"],
        noise_median=global_medians["noise"],
        sharpness_median=global_medians["sharpness"],
        shares={
            **texture_shares,
            "monochrome": monochrome_share,
            "crisp": texture_shares.get("crisp", 0.0),
            "soft_detail": texture_shares.get("soft_detail", 0.0),
            "grainy": texture_shares.get("grainy", 0.0),
        },
        conflict_dimensions=conflict_dimensions,
    )
    monochrome = monochrome_share >= STABLE_SUPPORT
    envelope = _envelope_for(targets, monochrome=monochrome)

    scene_targets: dict[SceneLabel, dict[str, float]] = {}
    for scene, group in scene_groups.items():
        if len(group) < 2:
            continue
        group_medians = medians(group)
        group_texture = _shares(
            (
                _texture_label(
                    photo.features.texture.sharpness,
                    photo.features.texture.noise,
                ),
                weight,
            )
            for photo, weight in group
        )
        group_targets = _numeric_targets(
            saturation_median=group_medians["saturation"],
            temperature_median=group_medians["temperature"],
            tint_median=group_medians["tint"],
            contrast_median=group_medians["contrast"],
            noise_median=group_medians["noise"],
            sharpness_median=group_medians["sharpness"],
            shares={
                **group_texture,
                "monochrome": sum(
                    weight
                    for photo, weight in group
                    if photo.features.color.monochrome
                )
                / (sum(weight for _, weight in group) or 1.0),
            },
            conflict_dimensions=frozenset(),
        )
        scene_targets[scene] = group_targets

    stability = {
        "color": round(
            (
                _support(saturation_shares, _top_label(saturation_shares))
                + _support(temperature_shares, _top_label(temperature_shares))
                + _support(tint_shares, _top_label(tint_shares))
            )
            / 3.0,
            3,
        ),
        "tone": round(
            (
                _support(contrast_shares, _top_label(contrast_shares))
                + _support(key_shares, _top_label(key_shares))
            )
            / 2.0,
            3,
        ),
        "light": round(_support(light_shares, _top_label(light_shares)), 3),
        "texture": round(_support(texture_shares, _top_label(texture_shares)), 3),
        "scene": round(scene_stability, 3),
    }
    consistency = (
        stability["color"] + stability["tone"] + stability["light"] + stability["texture"]
    ) / 4.0
    coverage = min(1.0, len(weighted) / PREFERRED_GLOBAL_PHOTOS)
    if len(weighted) >= PREFERRED_GLOBAL_PHOTOS:
        scene_factor = 1.0
    elif len(weighted) >= MIN_GLOBAL_PHOTOS:
        scene_factor = 0.85
    else:
        scene_factor = 0.70
    provider_factor = 0.50 + 0.50 * (
        sum(photo.features.overall_confidence for photo, _ in weighted) / len(weighted)
    )
    anomaly_count = sum(1 for photo, _ in weighted if _has_warning(photo.features))
    anomaly_factor = 1.0 - 0.25 * (anomaly_count / len(weighted))
    confidence = _clamp(
        (0.65 * consistency + 0.35 * scene_stability)
        * coverage
        * scene_factor
        * provider_factor
        * anomaly_factor,
        0.0,
        1.0,
    )

    scene_summaries = _scene_summaries(scene_groups, total_weight=total_weight)
    top_scene_labels = [
        scene for scene, _ in sorted(
            scene_groups.items(),
            key=lambda item: (-sum(weight for _, weight in item[1]), item[0].value),
        )
    ]
    suitable_scenes = tuple(top_scene_labels[:4]) or (SceneLabel.OTHER,)
    scene_names = "、".join(_SCENE_LABELS[scene] for scene in suitable_scenes)

    top_saturation = _top_label(saturation_shares)
    top_contrast = _top_label(contrast_shares)
    top_temperature = _top_label(temperature_shares)
    top_tint = _top_label(tint_shares)
    top_light = _top_label(light_shares)
    top_key = _top_label(key_shares)
    top_texture = _top_label(texture_shares)
    top_harmony = _top_label(
        _shares(
            (photo.features.color.harmony.value, weight)
            for photo, weight in weighted
        )
    )
    top_direction = _top_label(
        _shares(
            (photo.features.light.direction.value, weight)
            for photo, weight in weighted
        )
    )
    saturation_text = _SATURATION_TEXT[top_saturation]
    contrast_text = _CONTRAST_TEXT[top_contrast]
    temperature_text = _TEMPERATURE_TEXT[top_temperature]
    tint_text = _TINT_TEXT[top_tint]
    light_text = _LIGHT_TEXT[top_light]
    key_text = _KEY_TEXT[top_key]
    texture_text = _TEXTURE_TEXT[top_texture]
    harmony_text = _HARMONY_LABELS.get(top_harmony, "色彩关系待确认")
    direction_text = _DIRECTION_LABELS.get(top_direction, "光线方向待确认")

    if monochrome:
        color_description = "以黑白影调为主，色彩整体去饱和，重点保留灰阶层次。"
    else:
        tint_part = "" if top_tint == "neutral" else f"{tint_text}，"
        color_description = f"{temperature_text}，{tint_part}{saturation_text}；{harmony_text}。"
    tone_description = f"{contrast_text}，{key_text}。"
    light_description = f"{light_text}，{direction_text}。"
    texture_description = f"{texture_text}。"
    scene_description = f"参考照片主要来自{scene_names}。"
    constraints = _constraints(weighted, avoid=avoid, conflicts=conflicts)
    protected = _protected(constraints)
    avoid_labels = "；".join(_AVOID_TEXT[effect] for effect in avoid) if avoid else "无明显回避项"
    protected_labels = "、".join(_CONSTRAINT_TEXT[item] for item in protected)
    constraint_description = (
        f"{protected_labels}；" if protected_labels else "保留自然过渡；"
    ) + f"用户回避：{avoid_labels}。"

    sections = _sections(
        color_description=color_description,
        tone_description=tone_description,
        light_description=light_description,
        texture_description=texture_description,
        scene_description=scene_description,
        constraint_description=constraint_description,
        evidence={
            "color": (
                _share_text(
                    _support(temperature_shares, top_temperature),
                    _TEMPERATURE_TEXT[top_temperature],
                ),
                _share_text(
                    _support(saturation_shares, top_saturation),
                    _SATURATION_TEXT[top_saturation],
                ),
                _share_text(
                    _support(tint_shares, top_tint),
                    _TINT_TEXT[top_tint],
                ),
            ),
            "tone": (
                _share_text(
                    _support(contrast_shares, top_contrast),
                    _CONTRAST_TEXT[top_contrast],
                ),
                f"{_support(key_shares, top_key):.0%} 的照片为{_KEY_TEXT[top_key]}",
            ),
            "light": (
                _share_text(
                    _support(light_shares, top_light),
                    _LIGHT_TEXT[top_light],
                ),
                f"常见光线方向：{direction_text}",
            ),
            "texture": (
                _share_text(
                    _support(texture_shares, top_texture),
                    _TEXTURE_TEXT[top_texture],
                ),
            ),
            "scene": tuple(
                f"{_SCENE_LABELS[scene]} {len(group)} 张"
                for scene, group in sorted(
                    scene_groups.items(),
                    key=lambda item: (-len(item[1]), item[0].value),
                )
            )[:8],
            "constraints": tuple(_CONSTRAINT_TEXT[item] for item in constraints)[:12],
        },
    )

    occasional: list[str] = []
    for key, label in (
        ("color", "色彩"),
        ("tone", "影调"),
        ("light", "光线"),
        ("texture", "质感"),
        ("scene", "场景"),
    ):
        if stability[key] < CANDIDATE_SUPPORT:
            occasional.append(f"{label}倾向不稳定，暂不作为稳定个人特征。")
    occasional.extend(
        _minority_messages(saturation_shares, _SATURATION_TEXT, "色彩")
    )
    occasional.extend(
        _minority_messages(temperature_shares, _TEMPERATURE_TEXT, "色温")
    )
    occasional.extend(_minority_messages(light_shares, _LIGHT_TEXT, "光线"))
    occasional.extend(
        _minority_messages(texture_shares, _TEXTURE_TEXT, "质感")
    )
    occasional = list(dict.fromkeys(occasional))[:6]
    limitations: list[str] = []
    if len(weighted) < MIN_GLOBAL_PHOTOS:
        limitations.append("参考照片少于 3 张，全局结论的置信度有限。")
    elif len(weighted) < PREFERRED_GLOBAL_PHOTOS:
        limitations.append("参考照片少于 5 张，建议补充后重新融合。")
    if any(photo.features.is_mock for photo, _ in weighted):
        limitations.append("部分参考照片使用模拟分析，语义特征仅供占位。")
    if conflicts:
        limitations.append(f"检测到 {len(conflicts)} 处偏好冲突，已保留为候选而非平均。")
    if len(scene_groups) > 1 and scene_stability < CANDIDATE_SUPPORT:
        limitations.append("参考照片场景差异较大，全局风格仅保留跨场景一致的方向。")
    if anomaly_count:
        limitations.append(f"{anomaly_count} 张照片存在裁切、清晰度或噪声异常，已降低其权重。")

    default_strength = _clamp(0.35 + 0.35 * confidence, 0.35, 0.75)
    summary = (
        f"个人风格概览：{color_description}\n"
        f"影调：{tone_description}\n"
        f"光线：{light_description}\n"
        f"质感：{texture_description}\n"
        f"适用场景：{scene_names}。\n"
        f"处理原则：{constraint_description}"
    )

    return FusionOutcome(
        color=StyleColorTraits(
            tendency=(
                "黑白影调，色彩完全去饱和"
                if monochrome
                else f"{temperature_text}，{saturation_text}"
            ),
            relationships=harmony_text,
            saturation=(
                "去饱和至单色，保留灰阶层次"
                if monochrome
                else saturation_text
            ),
        ),
        light=StyleLightTraits(
            contrast=contrast_text,
            shadows=(
                "暗部较深，保留少量层次"
                if key_shares.get("low", 0.0) >= CANDIDATE_SUPPORT
                else "暗部开放，层次自然"
                if key_shares.get("high", 0.0) >= CANDIDATE_SUPPORT
                else "暗部层次自然"
            ),
            highlights=(
                "高光容易溢出，优先保护高光细节"
                if sum(
                    weight
                    for photo, weight in weighted
                    if any(item.code == "highlights_clipped" for item in photo.features.anomalies)
                )
                / (total_weight or 1.0)
                >= CONFLICT_SUPPORT
                else "高光柔和受控"
            ),
            expression=f"{light_text}，{direction_text}",
        ),
        composition=_composition_traits(weighted),
        texture=StyleTextureTraits(
            grain=(
                "颗粒感明显"
                if texture_shares.get("grainy", 0.0) >= CANDIDATE_SUPPORT
                else "颗粒克制"
            ),
            sharpness=(
                "清晰锐利"
                if texture_shares.get("crisp", 0.0) >= CANDIDATE_SUPPORT
                else "画面柔和"
                if texture_shares.get("soft_detail", 0.0) >= CANDIDATE_SUPPORT
                else "清晰度自然"
            ),
            detail=(
                "保留较多细节"
                if texture_shares.get("crisp", 0.0) >= CANDIDATE_SUPPORT
                else "细节保留有限"
                if texture_shares.get("soft_detail", 0.0) >= CANDIDATE_SUPPORT
                else "细节保留自然"
            ),
        ),
        scene_fit=StyleSceneFit(
            suitable=suitable_scenes,
            suitable_notes=f"参考照片覆盖{scene_names}；全局结论只保留跨场景一致的方向。",
            unsuitable_notes=(
                "未覆盖场景需要重新适配；存在偏好冲突或场景差异过大时，不强行套用统一参数。"
            ),
        ),
        constraints=constraints,
        protected=protected,
        envelope=envelope,
        targets=targets,
        scene_targets=scene_targets,
        stability=stability,
        confidence=round(confidence, 3),
        sample_count=len(weighted),
        anomaly_count=anomaly_count,
        default_strength=round(default_strength, 3),
        summary=summary[:500],
        sections=sections,
        conflicts=tuple(conflicts),
        scenes=scene_summaries,
        occasional=tuple(occasional),
        limitations=tuple(limitations),
    )


__all__ = [
    "FusionOutcome",
    "FusionPhoto",
    "fuse_photo_features",
    "fusion_weight",
]
