from __future__ import annotations

from dataclasses import dataclass

from app.ai.contracts import (
    CompositionBalance,
    LightingDirection,
    NegativeSpace,
    Occlusion,
    SceneLabel,
    SubjectRole,
    SubjectType,
)
from app.models.analysis_report import AnalysisReport
from app.models.photographer import DirectionConstraint
from app.models.style_fit import (
    ConversionMode,
    DimensionFit,
    FitDimension,
    FitLevel,
    RecommendedStrength,
    StyleFitConflict,
)
from app.models.style_profile import StyleProfile
from app.photographer.rules import (
    clamp,
    is_cool_ambient,
    is_high_contrast,
    is_low_key,
    is_low_saturation,
    is_strong_color_cast,
    is_warm_ambient,
)
from app.styles.vocabulary import SCENE_NAMES

DIMENSION_NAMES: dict[FitDimension, str] = {
    FitDimension.COLOR: "色彩",
    FitDimension.LIGHT: "光线",
    FitDimension.SCENE: "场景",
    FitDimension.COMPOSITION: "构图",
    FitDimension.SUBJECT: "主体",
}
DIMENSION_WEIGHTS: dict[FitDimension, float] = {
    FitDimension.COLOR: 0.20,
    FitDimension.LIGHT: 0.20,
    FitDimension.SCENE: 0.25,
    FitDimension.COMPOSITION: 0.20,
    FitDimension.SUBJECT: 0.15,
}
MAX_OVERALL_SCORE = 92.0
HIGH_CLIP_THRESHOLD = 5.0
LOW_CONFIDENCE = 0.40
SCENE_LOW_CONFIDENCE = 0.35

_BALANCE_NAMES: dict[CompositionBalance, str] = {
    CompositionBalance.BALANCED: "均衡",
    CompositionBalance.MODERATE: "一般",
    CompositionBalance.UNBALANCED: "失衡",
    CompositionBalance.UNKNOWN: "未知",
}
_NEGATIVE_NAMES: dict[NegativeSpace, str] = {
    NegativeSpace.LOW: "少",
    NegativeSpace.MODERATE: "适中",
    NegativeSpace.HIGH: "充足",
    NegativeSpace.UNKNOWN: "未知",
}
_OCCLUSION_NAMES: dict[Occlusion, str] = {
    Occlusion.NONE: "无",
    Occlusion.MINOR: "轻微",
    Occlusion.SIGNIFICANT: "明显",
    Occlusion.UNKNOWN: "未知",
}
_DIRECTIONAL = frozenset(
    {LightingDirection.SIDE, LightingDirection.SIDE_BACK, LightingDirection.BACK}
)
_DIFFUSE = frozenset({LightingDirection.DIFFUSE, LightingDirection.OVERCAST})
_CONFLICT_PRIORITY: dict[FitDimension, int] = {
    FitDimension.SCENE: 0,
    FitDimension.SUBJECT: 1,
    FitDimension.LIGHT: 2,
    FitDimension.COLOR: 3,
    FitDimension.COMPOSITION: 4,
}


@dataclass(frozen=True)
class FitEvaluation:
    overall_score: float
    overall_level: FitLevel
    dimensions: tuple[DimensionFit, ...]
    conflicts: tuple[StyleFitConflict, ...]
    achievable: tuple[str, ...]
    unachievable: tuple[str, ...]
    recommended_mode: ConversionMode
    recommended_strength: RecommendedStrength
    limitations: tuple[str, ...]
    summary: str


def level_for(score: float) -> FitLevel:
    if score >= 70.0:
        return FitLevel.HIGH
    if score >= 50.0:
        return FitLevel.MEDIUM
    if score >= 30.0:
        return FitLevel.LOW
    return FitLevel.UNSUITABLE


def evaluate_style_fit(profile: StyleProfile, report: AnalysisReport) -> FitEvaluation:
    """Score one style against a completed stage 3 report, without model calls."""

    scene = _evaluate_scene(profile, report)
    light = _evaluate_light(profile, report)
    color = _evaluate_color(profile, report)
    composition = _evaluate_composition(profile, report)
    subject = _evaluate_subject(profile, report)
    dimensions = (color, light, scene, composition, subject)

    overall = sum(
        dimension.score * DIMENSION_WEIGHTS[dimension.dimension] for dimension in dimensions
    )
    overall = round(
        clamp(_apply_caps(overall, scene, dimensions, report, profile), 0.0, MAX_OVERALL_SCORE),
        1,
    )

    conflicts = _conflicts(profile, report, scene, subject)
    return FitEvaluation(
        overall_score=overall,
        overall_level=level_for(overall),
        dimensions=dimensions,
        conflicts=conflicts,
        achievable=_achievable(profile, dimensions),
        unachievable=_unachievable(profile, report, scene, subject),
        recommended_mode=_mode_for(overall),
        recommended_strength=_strength_for(profile, overall),
        limitations=_limitations(report, scene),
        summary=_summary(profile, overall, dimensions, conflicts),
    )


def _dimension(
    dimension: FitDimension,
    score: float,
    basis: str,
    refs: tuple[str, ...],
    *,
    level: FitLevel | None = None,
) -> DimensionFit:
    bounded = clamp(score, 0.0, 100.0)
    return DimensionFit(
        dimension=dimension,
        level=level if level is not None else level_for(bounded),
        score=round(bounded, 1),
        basis=basis,
        evidence_refs=refs,
    )


def _evaluate_scene(profile: StyleProfile, report: AnalysisReport) -> DimensionFit:
    scene = report.scene.primary
    confidence = report.scene.confidence
    refs = ("scene.primary", "scene.confidence")
    if scene in profile.scene_fit.suitable:
        score = 72.0 + 18.0 * confidence
        basis = f"照片场景为{SCENE_NAMES[scene]}，属于该风格的适用场景。"
        if confidence < SCENE_LOW_CONFIDENCE:
            score = min(score, 55.0)
            basis += "但场景判断置信度较低，需要人工确认。"
        return _dimension(FitDimension.SCENE, score, basis, refs)

    suitable = "、".join(SCENE_NAMES[item] for item in profile.scene_fit.suitable)
    if scene is SceneLabel.OTHER:
        score = min(45.0 + 20.0 * confidence, 55.0)
        return _dimension(
            FitDimension.SCENE,
            score,
            "场景未能明确识别，无法确认与风格典型题材一致。",
            refs,
        )
    score = 20.0 + 10.0 * confidence
    level = FitLevel.UNSUITABLE if confidence >= 0.5 else FitLevel.LOW
    basis = f"照片场景为{SCENE_NAMES[scene]}，不在该风格的适用场景（{suitable}）内。"
    return _dimension(FitDimension.SCENE, score, basis, refs, level=level)


def _evaluate_light(profile: StyleProfile, report: AnalysisReport) -> DimensionFit:
    constraints = set(profile.constraints)
    protect_highlights = DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL in constraints
    protect_shadows = DirectionConstraint.PRESERVE_SHADOW_DETAIL in constraints
    low_key = DirectionConstraint.KEEP_LOW_KEY in constraints
    soft = DirectionConstraint.AVOID_EXTREME_CONTRAST in constraints
    dramatic = profile.envelope.contrast >= 35.0 and not soft

    luminance = report.measurements.luminance
    clipping = report.measurements.clipping
    lighting = report.lighting
    score = 60.0
    notes: list[str] = []
    refs = [
        "lighting.contrast",
        "lighting.direction",
        "measurement.luminance.std",
        "measurement.clipping.highlightsPct",
        "measurement.clipping.shadowsPct",
    ]

    if protect_highlights:
        if clipping.highlights_pct <= 2.0:
            score += 12.0
            notes.append("高光保护良好")
        elif clipping.highlights_pct <= HIGH_CLIP_THRESHOLD:
            score += 6.0
        elif clipping.highlights_pct > 10.0:
            score -= 20.0
            notes.append("高光裁切较多")
        else:
            score -= 10.0
            notes.append("高光略有裁切")
    if protect_shadows:
        if clipping.shadows_pct <= 2.0:
            score += 8.0
            notes.append("暗部细节完整")
        elif clipping.shadows_pct > 10.0:
            score -= 15.0
            notes.append("暗部裁切较多")
        elif clipping.shadows_pct > HIGH_CLIP_THRESHOLD:
            score -= 8.0

    if low_key:
        refs.append("measurement.luminance.p50")
        if is_low_key(report):
            score += 18.0
            notes.append("整体低调符合风格")
        else:
            score -= 18.0
            notes.append("画面整体不够低调")

    if dramatic:
        if is_high_contrast(report):
            score += 12.0
            notes.append("明暗反差足以支撑风格化光影")
        elif luminance.std < 0.16:
            score -= 12.0
            notes.append("光线偏平，缺少风格所需的明暗层次")
    if soft:
        if luminance.std <= 0.20:
            score += 10.0
            notes.append("光线柔和，符合风格的克制反差")
        elif luminance.std >= 0.30:
            score -= 10.0
            notes.append("反差过强，超出风格的柔和倾向")

    if dramatic and lighting.direction in _DIRECTIONAL:
        score += 5.0
    if soft and lighting.direction in _DIFFUSE:
        score += 5.0

    if lighting.confidence < LOW_CONFIDENCE:
        score = min(score, 55.0)
        notes.append("光线判断置信度较低")
    if not notes:
        notes.append("光线条件与风格没有明显冲突")
    basis = (
        "；".join(notes)
        + f"（明暗中位数 {luminance.p50:.2f}，反差 {luminance.std:.2f}，"
        + f"高光裁切 {clipping.highlights_pct:.1f}%，暗部裁切 {clipping.shadows_pct:.1f}%）。"
    )
    return _dimension(FitDimension.LIGHT, score, basis, tuple(refs))


def _evaluate_color(profile: StyleProfile, report: AnalysisReport) -> DimensionFit:
    constraints = set(profile.constraints)
    neutral = DirectionConstraint.MAINTAIN_NEUTRALITY in constraints
    avoid_cast = DirectionConstraint.AVOID_COLOR_CAST in constraints or neutral
    monochrome = profile.envelope.saturation >= 60.0 and neutral
    warm = DirectionConstraint.KEEP_WARM_TONES in constraints
    ambient = DirectionConstraint.KEEP_AMBIENT_COLOR in constraints
    avoid_extreme = DirectionConstraint.AVOID_EXTREME_SATURATION in constraints

    color = report.measurements.color
    cast = color.cast
    saturation = color.saturation_mean
    refs = (
        "color.temperature",
        "color.saturation",
        "measurement.color.saturationMean",
        "measurement.color.cast.temperature",
        "measurement.color.cast.tint",
    )
    score = 62.0
    notes: list[str] = []

    if monochrome:
        score = 74.0
        notes.append("风格以黑白呈现，现场色彩不构成主要限制")
        if not is_strong_color_cast(report):
            score += 8.0
        if saturation >= 0.20:
            score += 6.0
        else:
            notes.append("色彩信息较少")
    else:
        if avoid_cast:
            if is_strong_color_cast(report):
                score -= 22.0
                notes.append("色彩偏色明显，需要较强的白平衡校正")
            else:
                score += 14.0
                notes.append("白平衡中性，符合风格的中性色彩要求")
        if warm:
            if is_warm_ambient(report):
                score += 12.0
                notes.append("暖调氛围符合风格")
            elif is_cool_ambient(report):
                score -= 10.0
                notes.append("画面偏冷，与风格的暖调倾向冲突")
        if ambient:
            if saturation <= 0.60:
                score += 6.0
                notes.append("现场色彩关系可以保留")
            elif avoid_extreme:
                score -= 10.0
                notes.append("饱和度过高，需要明显降低饱和度")
        if avoid_extreme:
            if saturation >= 0.70:
                score -= 12.0
                notes.append("色彩浓度超出风格的克制范围")
            elif saturation <= 0.50:
                score += 10.0
        if profile.envelope.saturation <= 25.0 and not ambient:
            if saturation >= 0.55:
                score -= 10.0
                notes.append("色彩浓度高于风格的克制范围")
            elif saturation <= 0.40:
                score += 8.0
        if profile.envelope.saturation >= 50.0 and not avoid_extreme:
            if saturation >= 0.45:
                score += 10.0
                notes.append("色彩浓度足以支撑风格的色彩表达")
            elif is_low_saturation(report):
                score -= 8.0
                notes.append("色彩较淡，风格需要更鲜明的色彩")

    if report.color.confidence < LOW_CONFIDENCE:
        score = min(score, 55.0)
        notes.append("色彩判断置信度较低")
    if not notes:
        notes.append("色彩条件与风格没有明显冲突")

    basis = (
        "；".join(notes)
        + f"（饱和度均值 {saturation:.2f}，色温偏色 {cast.temperature:+.2f}，"
        + f"色调偏色 {cast.tint:+.2f}）。"
    )
    return _dimension(FitDimension.COLOR, score, basis, refs)


def _evaluate_composition(profile: StyleProfile, report: AnalysisReport) -> DimensionFit:
    composition = report.composition
    measurement = report.measurements.composition
    grid = measurement.edge_density_grid_3x3
    spread = max(grid) - min(grid)
    suitable = set(profile.scene_fit.suitable)
    constraints = set(profile.constraints)
    portrait_style = (
        profile.engine_style == "portrait" or DirectionConstraint.PRESERVE_SKIN_TONE in constraints
    )
    structure = SceneLabel.ARCHITECTURE in suitable or profile.engine_style in {
        "landscape",
        "street",
    }
    negative_wanted = profile.engine_style in {"landscape", "natural"}

    score = 60.0
    notes: list[str] = []

    if composition.balance is CompositionBalance.BALANCED:
        score += 10.0
        notes.append("画面平衡良好")
    elif composition.balance is CompositionBalance.MODERATE:
        score += 4.0
    elif composition.balance is CompositionBalance.UNBALANCED:
        score -= 12.0
        notes.append("画面平衡度不足")

    if portrait_style:
        if composition.occlusion is Occlusion.NONE:
            score += 8.0
            notes.append("主体没有被遮挡")
        elif composition.occlusion is Occlusion.SIGNIFICANT:
            score -= 15.0
            notes.append("主体被明显遮挡")

    horizon = composition.horizon_tilt_deg
    if (SceneLabel.ARCHITECTURE in suitable or SceneLabel.LANDSCAPE in suitable) and (
        horizon is not None
    ):
        if abs(horizon) <= 1.0:
            score += 8.0
            notes.append("地平线水平，结构稳定")
        elif abs(horizon) > 3.0:
            score -= 15.0
            notes.append(f"地平线倾斜 {abs(horizon):.1f}°")

    if structure:
        if spread >= 0.50:
            score += 8.0
            notes.append("画面结构分布明显")
        elif spread <= 0.15:
            score -= 8.0
            notes.append("画面结构层次较弱")

    if negative_wanted:
        if composition.negative_space is NegativeSpace.HIGH:
            score += 10.0
            notes.append("留白充足，符合风格的呼吸感")
        elif composition.negative_space is NegativeSpace.MODERATE:
            score += 4.0
        elif composition.negative_space is NegativeSpace.LOW:
            score -= 8.0
            notes.append("留白偏少")

    if composition.confidence < LOW_CONFIDENCE:
        score = min(score, 55.0)
        notes.append("构图判断置信度较低")
    if not notes:
        notes.append("构图条件与风格没有明显冲突")

    basis = (
        "；".join(notes)
        + f"（平衡 {_BALANCE_NAMES[composition.balance]}，留白 "
        + f"{_NEGATIVE_NAMES[composition.negative_space]}，遮挡 "
        + f"{_OCCLUSION_NAMES[composition.occlusion]}，边缘分布差异 {spread:.2f}）。"
    )
    refs = (
        "composition.balance",
        "composition.subjectPosition",
        "composition.negativeSpace",
        "composition.occlusion",
        "measurement.composition.horizonTiltDeg",
    )
    return _dimension(FitDimension.COMPOSITION, score, basis, refs)


def _evaluate_subject(profile: StyleProfile, report: AnalysisReport) -> DimensionFit:
    primary = next(
        (subject for subject in report.subjects if subject.role is SubjectRole.PRIMARY),
        report.subjects[0] if report.subjects else None,
    )
    people = [subject for subject in report.subjects if subject.type is SubjectType.PERSON]
    suitable = set(profile.scene_fit.suitable)
    constraints = set(profile.constraints)
    portrait_style = (
        profile.engine_style == "portrait" or DirectionConstraint.PRESERVE_SKIN_TONE in constraints
    )
    landscape_style = profile.engine_style == "landscape" or (
        SceneLabel.LANDSCAPE in suitable and not portrait_style
    )
    architecture_style = SceneLabel.ARCHITECTURE in suitable

    score = 60.0
    level: FitLevel | None = None
    notes: list[str] = []
    confidence = primary.confidence if primary is not None else 0.0

    if portrait_style:
        if primary is not None and primary.type is SubjectType.PERSON:
            score = 78.0 + 15.0 * confidence
            notes.append("检测到人物主体，符合风格的题材取向")
        elif people:
            score = 58.0 + 10.0 * max(subject.confidence for subject in people)
            notes.append("人物不是主要主体，风格表达会受限")
        else:
            score = 30.0
            level = FitLevel.UNSUITABLE
            notes.append("未检测到人物主体，风格依赖人物关系")
    elif landscape_style:
        if primary is not None and primary.type is SubjectType.PERSON:
            score = 58.0
            notes.append("人物作为主体会偏离风景风格的题材")
        elif primary is not None and primary.type in {
            SubjectType.BUILDING,
            SubjectType.PLANT,
            SubjectType.ANIMAL,
            SubjectType.SKY,
        }:
            score = 78.0 + 12.0 * confidence
            notes.append("自然或结构主体符合风景风格的题材")
        elif primary is None:
            score = 62.0
            notes.append("画面没有突出主体，符合开阔风景的常见形态")
        else:
            score = 66.0
            notes.append("主体类型与风景风格的典型题材部分吻合")
    elif architecture_style:
        if primary is not None and primary.type is SubjectType.BUILDING:
            score = 82.0
            notes.append("建筑主体符合风格的题材取向")
        elif any(subject.type is SubjectType.BUILDING for subject in report.subjects):
            score = 72.0
            notes.append("画面包含建筑结构，但主体不够集中")
        elif primary is not None and primary.type is SubjectType.PERSON:
            score = 62.0
            notes.append("人物主体会削弱建筑结构的表达")
        else:
            score = 58.0
            notes.append("缺少明确的建筑结构主体")
    else:
        if primary is not None and primary.type is SubjectType.PERSON:
            score = 80.0 + 10.0 * confidence
            notes.append("人物主体符合街头与纪实风格的题材取向")
        elif primary is not None:
            score = 76.0
            notes.append("存在明确主体，可以承载风格叙事")
        else:
            score = 55.0
            notes.append("画面没有明确主体，叙事性会减弱")

    if primary is not None and primary.confidence < LOW_CONFIDENCE:
        score = min(score, 55.0)
        notes.append("主体识别置信度较低")
    if not notes:
        notes.append("主体条件与风格没有明显冲突")

    refs: list[str] = ["composition.subjectPosition", "composition.occlusion"]
    if primary is not None:
        refs.insert(0, primary.id)
    basis = "；".join(notes) + "。"
    return _dimension(FitDimension.SUBJECT, score, basis, tuple(refs), level=level)


def _apply_caps(
    overall: float,
    scene: DimensionFit,
    dimensions: tuple[DimensionFit, ...],
    report: AnalysisReport,
    profile: StyleProfile,
) -> float:
    if scene.level is FitLevel.UNSUITABLE:
        overall = min(overall, 38.0)
    elif scene.score < 35.0:
        overall = min(overall, 55.0)

    low_count = sum(
        dimension.level in {FitLevel.LOW, FitLevel.UNSUITABLE} for dimension in dimensions
    )
    if low_count >= 2:
        overall = min(overall, 45.0)

    high_count = sum(dimension.level is FitLevel.HIGH for dimension in dimensions)
    if high_count < 3:
        overall = min(overall, 69.0)
    elif high_count == 3:
        overall = min(overall, 84.0)

    if report.scene.primary is SceneLabel.OTHER:
        overall = min(overall, 60.0)

    if report.scene.confidence < SCENE_LOW_CONFIDENCE:
        overall = min(overall, 49.0)
    if _analysis_confidence(report) < LOW_CONFIDENCE:
        overall = min(overall, 49.0)

    subject = next(item for item in dimensions if item.dimension is FitDimension.SUBJECT)
    if subject.level is FitLevel.UNSUITABLE and (
        profile.engine_style == "portrait"
        or DirectionConstraint.PRESERVE_SKIN_TONE in set(profile.constraints)
    ):
        overall = min(overall, 45.0)

    return overall


def _analysis_confidence(report: AnalysisReport) -> float:
    values = (
        report.scene.confidence,
        report.lighting.confidence,
        report.color.confidence,
        report.composition.confidence,
        report.technical_quality.confidence,
    )
    return sum(values) / len(values)


def _conflicts(
    profile: StyleProfile,
    report: AnalysisReport,
    scene: DimensionFit,
    subject: DimensionFit,
) -> tuple[StyleFitConflict, ...]:
    constraints = set(profile.constraints)
    conflicts: list[StyleFitConflict] = []

    if scene.level in {FitLevel.LOW, FitLevel.UNSUITABLE}:
        suitable = "、".join(SCENE_NAMES[item] for item in profile.scene_fit.suitable)
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.SCENE,
                description=(
                    f"照片场景为{SCENE_NAMES[report.scene.primary]}，而风格更适用于{suitable}；"
                    "后期无法改变拍摄场景。"
                ),
                evidence_refs=("scene.primary", "scene.confidence"),
                improvable=False,
            )
        )

    clipping = report.measurements.clipping
    if (
        DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL in constraints
        and clipping.highlights_pct > HIGH_CLIP_THRESHOLD
    ):
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.LIGHT,
                description=(
                    f"高光裁切 {clipping.highlights_pct:.1f}%，压缩高光后仍有部分细节无法恢复。"
                ),
                evidence_refs=(
                    "measurement.clipping.highlightsPct",
                    "lighting.contrast",
                ),
                improvable=True,
            )
        )
    if (
        DirectionConstraint.PRESERVE_SHADOW_DETAIL in constraints
        and clipping.shadows_pct > HIGH_CLIP_THRESHOLD
    ):
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.LIGHT,
                description=f"暗部裁切 {clipping.shadows_pct:.1f}%，提亮暗部会放大噪点。",
                evidence_refs=(
                    "measurement.clipping.shadowsPct",
                    "measurement.detail.noiseEstimate",
                ),
                improvable=True,
            )
        )
    if DirectionConstraint.KEEP_LOW_KEY in constraints and not is_low_key(report):
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.LIGHT,
                description=(
                    "画面整体偏亮，压暗只能部分接近低调氛围，无法还原低调布光下未记录的暗部层次。"
                ),
                evidence_refs=(
                    "measurement.luminance.p50",
                    "measurement.luminance.std",
                ),
                improvable=False,
            )
        )
    if (
        DirectionConstraint.AVOID_EXTREME_CONTRAST in constraints
        and report.measurements.luminance.std >= 0.30
    ):
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.LIGHT,
                description="光线反差较强，柔化会损失部分立体感。",
                evidence_refs=(
                    "measurement.luminance.std",
                    "lighting.contrast",
                ),
                improvable=True,
            )
        )

    saturation = report.measurements.color.saturation_mean
    neutral = DirectionConstraint.MAINTAIN_NEUTRALITY in constraints
    if (
        (DirectionConstraint.AVOID_COLOR_CAST in constraints or neutral)
        and not (profile.envelope.saturation >= 60.0 and neutral)
        and is_strong_color_cast(report)
    ):
        cast = report.measurements.color.cast
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.COLOR,
                description=(
                    f"存在明显色偏（色温 {cast.temperature:+.2f}，色调 {cast.tint:+.2f}），"
                    "需要通过白平衡校正。"
                ),
                evidence_refs=(
                    "measurement.color.cast.temperature",
                    "measurement.color.cast.tint",
                ),
                improvable=True,
            )
        )
    if DirectionConstraint.AVOID_EXTREME_SATURATION in constraints and saturation >= 0.70:
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.COLOR,
                description="饱和度较高，需要明显降低饱和度才能符合风格的克制色彩。",
                evidence_refs=("measurement.color.saturationMean",),
                improvable=True,
            )
        )
    if DirectionConstraint.KEEP_WARM_TONES in constraints and is_cool_ambient(report):
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.COLOR,
                description="画面偏冷，与风格的暖调倾向不一致。",
                evidence_refs=("color.temperature", "measurement.color.cast.temperature"),
                improvable=True,
            )
        )

    if (
        profile.engine_style == "portrait" or DirectionConstraint.PRESERVE_SKIN_TONE in constraints
    ) and report.composition.occlusion is Occlusion.SIGNIFICANT:
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.COMPOSITION,
                description="主体被明显遮挡，后期无法移除遮挡物。",
                evidence_refs=("composition.occlusion", "composition.subjectPosition"),
                improvable=False,
            )
        )
    horizon = report.composition.horizon_tilt_deg
    if (
        (
            SceneLabel.ARCHITECTURE in set(profile.scene_fit.suitable)
            or SceneLabel.LANDSCAPE in set(profile.scene_fit.suitable)
        )
        and horizon is not None
        and abs(horizon) > 3.0
    ):
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.COMPOSITION,
                description=f"地平线倾斜 {abs(horizon):.1f}°，可通过旋转校正。",
                evidence_refs=(
                    "measurement.composition.horizonTiltDeg",
                    "composition.balance",
                ),
                improvable=True,
            )
        )
    if report.composition.balance is CompositionBalance.UNBALANCED:
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.COMPOSITION,
                description="画面平衡度不足，可通过裁剪或暗角弱化干扰元素。",
                evidence_refs=("composition.balance", "composition.subjectPosition"),
                improvable=True,
            )
        )

    if subject.level is FitLevel.UNSUITABLE:
        conflicts.append(
            StyleFitConflict(
                dimension=FitDimension.SUBJECT,
                description="画面缺少风格所需的主体，后期无法创造不存在的人物或场景关系。",
                evidence_refs=("composition.subjectPosition", "scene.primary"),
                improvable=False,
            )
        )

    return tuple(sorted(conflicts, key=lambda item: _CONFLICT_PRIORITY[item.dimension])[:8])


def _achievable(
    profile: StyleProfile,
    dimensions: tuple[DimensionFit, ...],
) -> tuple[str, ...]:
    achievable: list[str] = []
    constraints = set(profile.constraints)
    monochrome = (
        profile.envelope.saturation >= 60.0
        and DirectionConstraint.MAINTAIN_NEUTRALITY in constraints
    )
    for dimension in dimensions:
        if dimension.level in {FitLevel.LOW, FitLevel.UNSUITABLE}:
            continue
        if dimension.dimension is FitDimension.LIGHT:
            achievable.append("可调整曝光、反差与高光/暗部，向风格的影调倾向靠拢。")
        elif dimension.dimension is FitDimension.COLOR:
            if monochrome:
                achievable.append("可去除色彩信息，呈现风格的黑白影调与明暗结构。")
            else:
                achievable.append("可调整白平衡、饱和度与色彩关系，贴近风格的色彩倾向。")
        elif dimension.dimension is FitDimension.SCENE:
            achievable.append("场景本身符合风格的典型题材，可保留现场氛围。")
        elif dimension.dimension is FitDimension.COMPOSITION:
            achievable.append("可通过裁剪、旋转、暗角与清晰度调整强化现有构图结构。")
        elif dimension.dimension is FitDimension.SUBJECT:
            achievable.append("可对现有主体做局部调整，强化主体与背景的分离。")
    if not achievable:
        achievable.append("可进行基础的曝光与色彩校正，但难以呈现风格的核心特征。")
    return tuple(achievable[:8])


def _unachievable(
    profile: StyleProfile,
    report: AnalysisReport,
    scene: DimensionFit,
    subject: DimensionFit,
) -> tuple[str, ...]:
    unachievable: list[str] = [
        "无法改变拍摄时的机位、光线方向与天气条件。",
    ]
    constraints = set(profile.constraints)
    if scene.level in {FitLevel.LOW, FitLevel.UNSUITABLE}:
        suitable = "、".join(SCENE_NAMES[item] for item in profile.scene_fit.suitable)
        unachievable.append(
            f"后期无法把{SCENE_NAMES[report.scene.primary]}场景转换成风格典型的{suitable}场景。"
        )
    if subject.level is FitLevel.UNSUITABLE and (
        profile.engine_style == "portrait" or DirectionConstraint.PRESERVE_SKIN_TONE in constraints
    ):
        unachievable.append("无法在画面中创造不存在的人物主体与人物关系。")
    if DirectionConstraint.KEEP_LOW_KEY in constraints and not is_low_key(report):
        unachievable.append("无法还原低调布光下未记录的暗部层次。")
    if report.measurements.clipping.highlights_pct > 10.0:
        unachievable.append("已经裁切的高光细节无法恢复。")
    spread = max(report.measurements.composition.edge_density_grid_3x3) - min(
        report.measurements.composition.edge_density_grid_3x3
    )
    if SceneLabel.ARCHITECTURE in set(profile.scene_fit.suitable) and spread <= 0.15:
        unachievable.append("无法创造画面中不存在的建筑结构或几何线条。")
    if (
        profile.engine_style == "portrait" or DirectionConstraint.PRESERVE_SKIN_TONE in constraints
    ) and report.composition.occlusion is Occlusion.SIGNIFICANT:
        unachievable.append("无法移除主体前方的遮挡物，被遮挡的部分无法补全。")
    return tuple(unachievable[:8])


def _mode_for(overall: float) -> ConversionMode:
    if overall >= 70.0:
        return ConversionMode.STYLE
    if overall >= 50.0:
        return ConversionMode.NATURAL
    return ConversionMode.CREATIVE


def _strength_for(profile: StyleProfile, overall: float) -> RecommendedStrength:
    if overall >= 70.0:
        minimum, maximum = 0.50, 0.75
    elif overall >= 50.0:
        minimum, maximum = 0.35, 0.60
    elif overall >= 30.0:
        minimum, maximum = 0.20, 0.40
    else:
        minimum, maximum = 0.15, 0.30
    return RecommendedStrength(
        minimum=minimum,
        maximum=maximum,
        default=round(clamp(profile.default_strength, minimum, maximum), 2),
    )


def _limitations(report: AnalysisReport, scene: DimensionFit) -> tuple[str, ...]:
    limitations: list[str] = [
        "适配评估基于阶段三分析，不替代摄影师对原始拍摄意图的判断。",
    ]
    if report.engine.is_mock:
        limitations.append("当前分析来自模拟引擎，适配评估仅供流程验证。")
    if _analysis_confidence(report) < LOW_CONFIDENCE:
        limitations.append("阶段三分析的整体置信度较低，评估结果需要人工复核。")
    if report.scene.confidence < SCENE_LOW_CONFIDENCE:
        limitations.append("场景判断置信度较低，题材匹配需要人工确认。")
    return tuple(limitations[:8])


def _summary(
    profile: StyleProfile,
    overall: float,
    dimensions: tuple[DimensionFit, ...],
    conflicts: tuple[StyleFitConflict, ...],
) -> str:
    strong = [
        DIMENSION_NAMES[item.dimension] for item in dimensions if item.level is FitLevel.HIGH
    ][:2]
    weak = [
        DIMENSION_NAMES[item.dimension]
        for item in dimensions
        if item.level in {FitLevel.LOW, FitLevel.UNSUITABLE}
    ]
    level = level_for(overall)
    if level is FitLevel.HIGH:
        strengths = "、".join(strong) if strong else "主要维度"
        return f"照片与{profile.name}的视觉条件较匹配，{strengths}适配较高，可以按该风格方向推进。"
    if level is FitLevel.MEDIUM:
        reason = conflicts[0].description.rstrip("。") if conflicts else "部分维度只达到中等水平"
        return f"照片具备融入{profile.name}的基础条件，但{reason}，建议以克制强度推进。"
    reason = (
        conflicts[0].description.rstrip("。")
        if conflicts
        else (f"{weak[0]}条件不足" if weak else "关键条件不足")
    )
    return (
        f"照片与{profile.name}的适配度较低：{reason}。"
        "不建议直接套用该风格，可降低强度尝试或选择替代风格。"
    )


__all__ = [
    "DIMENSION_NAMES",
    "DIMENSION_WEIGHTS",
    "FitEvaluation",
    "MAX_OVERALL_SCORE",
    "evaluate_style_fit",
    "level_for",
]
