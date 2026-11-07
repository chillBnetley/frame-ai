"""Deterministic, evidence-bound photography critique (Stage 5 Task 7).

No language model is involved: every sentence is templated from Stage 3 report
fields and carries the report identifiers it was derived from. Object nouns are
emitted only when the report describes a subject of that type, so a critique
cannot invent a person, a sky, or a building the analysis never saw.
"""

from __future__ import annotations

from typing import Literal

from app.ai.contracts import (
    ColorHarmony,
    ColorTemperature,
    CompositionBalance,
    ContrastLevel,
    ExposureQuality,
    IssueType,
    LightingDirection,
    LightingType,
    NegativeSpace,
    NoiseLevel,
    RecommendationCategory,
    SaturationLevel,
    SceneLabel,
    Severity,
    SharpnessQuality,
    SubjectPosition,
    SubjectRole,
    SubjectType,
)
from app.models.analysis_report import AnalysisReport, SubjectInfo
from app.models.photographer import (
    AdjustmentIntent,
    CritiqueCreative,
    CritiquePoint,
    CritiqueResponse,
    CritiqueSuggestion,
    CritiqueTechnical,
    DiagnosisItem,
    DiagnosisResult,
    PhotographerPreferences,
)
from app.photographer.diagnosis import diagnose
from app.photographer.rules import (
    creative_choices,
    is_cool_ambient,
    is_high_contrast,
    is_high_key,
    is_high_saturation,
    is_low_key,
    is_low_saturation,
    is_strong_color_cast,
    is_warm_ambient,
    issue_adjustments,
)

CRITIQUE_GENERATED_BY: Literal["deterministic-rules"] = "deterministic-rules"
_WEAK_CONFIDENCE = 0.55
_LIMIT = 8

_SUBJECT_NOUNS: dict[SubjectType, str] = {
    SubjectType.PERSON: "人物",
    SubjectType.BUILDING: "建筑",
    SubjectType.SKY: "天空",
    SubjectType.ROAD: "道路",
    SubjectType.PLANT: "植物",
    SubjectType.ANIMAL: "动物",
    SubjectType.FOOD: "食物",
    SubjectType.VEHICLE: "车辆",
}

_ISSUE_LABELS: dict[IssueType, str] = {
    IssueType.OVEREXPOSURE: "整体偏亮",
    IssueType.UNDEREXPOSURE: "整体偏暗",
    IssueType.HIGHLIGHT_CLIPPING: "高光溢出",
    IssueType.SHADOW_CLIPPING: "暗部死黑",
    IssueType.SUBJECT_UNDEREXPOSURE: "主体欠曝",
    IssueType.BACKGROUND_OVEREXPOSURE: "背景过亮",
    IssueType.COLOR_CAST: "整体色偏",
    IssueType.TEMPERATURE_MISMATCH: "冷暖不统一",
    IssueType.SATURATION_ISSUE: "饱和度失衡",
    IssueType.COLOR_HIERARCHY_ISSUE: "色彩层次接近",
    IssueType.SUBJECT_PLACEMENT: "主体位置存疑",
    IssueType.BALANCE_ISSUE: "画面重心偏移",
    IssueType.NEGATIVE_SPACE_ISSUE: "负空间比例存疑",
    IssueType.HORIZON_TILT: "水平线倾斜",
    IssueType.FOCUS_ISSUE: "合焦不实",
    IssueType.MOTION_BLUR: "运动模糊",
    IssueType.HIGH_NOISE: "噪点偏高",
    IssueType.LOW_DETAIL: "细节偏少",
    IssueType.HARSH_CONTRAST: "反差过硬",
    IssueType.FLAT_LIGHTING: "光线偏平",
}

_ADVICE: dict[IssueType, tuple[RecommendationCategory, str]] = {
    IssueType.OVEREXPOSURE: (
        RecommendationCategory.EXPOSURE,
        "先整体降曝光，再单独收高光，避免一起压暗导致发灰。",
    ),
    IssueType.UNDEREXPOSURE: (
        RecommendationCategory.EXPOSURE,
        "小幅提升曝光与阴影，保留暗部层次而不是整体提亮。",
    ),
    IssueType.HIGHLIGHT_CLIPPING: (
        RecommendationCategory.EXPOSURE,
        "压低高光与白色色阶，尽量找回被裁切的高光层次。",
    ),
    IssueType.SHADOW_CLIPPING: (
        RecommendationCategory.EXPOSURE,
        "提亮阴影与黑色色阶，让暗部重新出现细节。",
    ),
    IssueType.SUBJECT_UNDEREXPOSURE: (
        RecommendationCategory.LIGHTING,
        "对主体区域局部提亮，缩小主体与背景的亮度差。",
    ),
    IssueType.BACKGROUND_OVEREXPOSURE: (
        RecommendationCategory.LIGHTING,
        "压低背景高光，避免背景亮度压过主体。",
    ),
    IssueType.COLOR_CAST: (
        RecommendationCategory.COLOR,
        "以白平衡或中性灰参考校正色偏，再判断剩余暖冷是否保留。",
    ),
    IssueType.TEMPERATURE_MISMATCH: (
        RecommendationCategory.COLOR,
        "统一整体色温，减少主体与背景之间的冷暖冲突。",
    ),
    IssueType.SATURATION_ISSUE: (
        RecommendationCategory.COLOR,
        "以自然饱和度优先，避免一次性推动整体饱和度。",
    ),
    IssueType.COLOR_HIERARCHY_ISSUE: (
        RecommendationCategory.COLOR,
        "拉开主体与背景的色彩层次，避免主次颜色过于接近。",
    ),
    IssueType.SUBJECT_PLACEMENT: (
        RecommendationCategory.COMPOSITION,
        "重新审视取景与裁切，让主体避开画面边缘并留出视线空间。",
    ),
    IssueType.BALANCE_ISSUE: (
        RecommendationCategory.COMPOSITION,
        "调整裁切或局部明暗来平衡画面重心，先不改变主体。",
    ),
    IssueType.NEGATIVE_SPACE_ISSUE: (
        RecommendationCategory.COMPOSITION,
        "确认负空间比例是否符合表达需要，再决定裁切范围。",
    ),
    IssueType.HORIZON_TILT: (
        RecommendationCategory.COMPOSITION,
        "校正水平线，再检查主体是否因旋转需要重新裁切。",
    ),
    IssueType.FOCUS_ISSUE: (
        RecommendationCategory.SHARPNESS,
        "适度提升清晰度与锐化只能弥补观感，不能恢复丢失的细节。",
    ),
    IssueType.MOTION_BLUR: (
        RecommendationCategory.SHARPNESS,
        "轻微锐化可以改善观感，明显拖影建议重新拍摄。",
    ),
    IssueType.HIGH_NOISE: (
        RecommendationCategory.SHARPNESS,
        "先降噪再补细节，避免锐化把噪点一起放大。",
    ),
    IssueType.LOW_DETAIL: (
        RecommendationCategory.SHARPNESS,
        "提升清晰度与锐化改善观感，注意不要放大噪点。",
    ),
    IssueType.HARSH_CONTRAST: (
        RecommendationCategory.EXPOSURE,
        "压反差：降低对比与高光，同时提起阴影过渡。",
    ),
    IssueType.FLAT_LIGHTING: (
        RecommendationCategory.LIGHTING,
        "增加对比与清晰度，或用局部调整重建主次。",
    ),
}

_SEVERITY_LABELS: dict[Severity, str] = {
    Severity.HIGH: "高",
    Severity.MEDIUM: "中",
    Severity.LOW: "低",
}

_EXPOSURE_LABELS: dict[ExposureQuality, str] = {
    ExposureQuality.UNDEREXPOSED: "欠曝",
    ExposureQuality.SLIGHTLY_UNDEREXPOSED: "略欠曝",
    ExposureQuality.BALANCED: "均衡",
    ExposureQuality.SLIGHTLY_OVEREXPOSED: "略过曝",
    ExposureQuality.OVEREXPOSED: "过曝",
}
_SHARPNESS_LABELS: dict[SharpnessQuality, str] = {
    SharpnessQuality.POOR: "较差",
    SharpnessQuality.SOFT: "偏软",
    SharpnessQuality.GOOD: "良好",
}
_NOISE_LABELS: dict[NoiseLevel, str] = {
    NoiseLevel.LOW: "低",
    NoiseLevel.MODERATE: "中等",
    NoiseLevel.HIGH: "偏高",
}
_COLOR_TEMPERATURE_LABELS: dict[ColorTemperature, str] = {
    ColorTemperature.WARM: "偏暖",
    ColorTemperature.NEUTRAL: "中性",
    ColorTemperature.COOL: "偏冷",
}
_SATURATION_LABELS: dict[SaturationLevel, str] = {
    SaturationLevel.LOW: "偏低",
    SaturationLevel.MODERATE: "适中",
    SaturationLevel.HIGH: "偏高",
}
_HARMONY_LABELS: dict[ColorHarmony, str] = {
    ColorHarmony.HARMONIOUS: "协调",
    ColorHarmony.MODERATE: "一般",
    ColorHarmony.CLASHING: "冲突",
}
_CONTRAST_LABELS: dict[ContrastLevel, str] = {
    ContrastLevel.LOW: "柔和",
    ContrastLevel.MODERATE: "中等",
    ContrastLevel.HIGH: "强烈",
}
_LIGHTING_TYPE_LABELS: dict[LightingType, str] = {
    LightingType.NATURAL: "自然光",
    LightingType.ARTIFICIAL: "人造光",
    LightingType.MIXED: "混合光",
}
_DIRECTION_LABELS: dict[LightingDirection, str] = {
    LightingDirection.FRONT: "正面光",
    LightingDirection.SIDE: "侧面光",
    LightingDirection.BACK: "逆光",
    LightingDirection.SIDE_BACK: "侧逆光",
    LightingDirection.DIFFUSE: "散射光",
    LightingDirection.OVERCAST: "阴天光",
    LightingDirection.ARTIFICIAL: "人工光",
    LightingDirection.MIXED: "混合方向光",
}
_POSITION_LABELS: dict[SubjectPosition, str] = {
    SubjectPosition.LEFT: "画面左侧",
    SubjectPosition.RIGHT: "画面右侧",
    SubjectPosition.CENTER: "画面中央",
    SubjectPosition.TOP: "画面上方",
    SubjectPosition.BOTTOM: "画面下方",
}
_BALANCE_LABELS: dict[CompositionBalance, str] = {
    CompositionBalance.BALANCED: "平衡",
    CompositionBalance.MODERATE: "大致平衡",
    CompositionBalance.UNBALANCED: "失衡",
}
_NEGATIVE_LABELS: dict[NegativeSpace, str] = {
    NegativeSpace.LOW: "较少",
    NegativeSpace.MODERATE: "适中",
    NegativeSpace.HIGH: "充足",
}
_SCENE_LABELS: dict[SceneLabel, str] = {
    SceneLabel.PORTRAIT: "人像",
    SceneLabel.LANDSCAPE: "风景",
    SceneLabel.STREET: "街拍",
    SceneLabel.ARCHITECTURE: "建筑",
    SceneLabel.NIGHT: "夜景",
    SceneLabel.INDOOR: "室内",
    SceneLabel.FOOD: "美食",
    SceneLabel.NATURE: "自然",
}


def build_critique(
    report: AnalysisReport,
    preferences: PhotographerPreferences | None = None,
) -> CritiqueResponse:
    """Turn one completed analysis report into a traceable critique."""
    prefs = preferences or PhotographerPreferences()
    diagnosis = diagnose(report)
    return CritiqueResponse(
        analysis_id=report.analysis_id,
        is_mock=report.engine.is_mock,
        generated_by=CRITIQUE_GENERATED_BY,
        strengths=_strengths(report),
        technical=CritiqueTechnical(
            objective=_objective(report),
            possible_issues=_problems(diagnosis),
        ),
        creative=_creative(report),
        suggestions=_suggestions(report, diagnosis, prefs),
        limitations=_limitations(report),
    )


def _primary_subject(report: AnalysisReport) -> SubjectInfo | None:
    for subject in report.subjects:
        if subject.role is SubjectRole.PRIMARY:
            return subject
    return report.subjects[0] if report.subjects else None


def _strengths(report: AnalysisReport) -> tuple[CritiquePoint, ...]:
    points: list[CritiquePoint] = []
    subject = _primary_subject(report)
    measurements = report.measurements
    quality = report.technical_quality

    if subject is not None and report.composition.subject_position in _POSITION_LABELS:
        noun = _SUBJECT_NOUNS.get(subject.type, "被摄主体")
        points.append(
            _point(
                f"{noun}位置明确，视觉落点清楚。",
                (subject.region_id, "composition.subjectPosition"),
            )
        )
    if quality.exposure in _EXPOSURE_LABELS:
        points.append(
            _point(
                f"整体曝光{_EXPOSURE_LABELS[quality.exposure]}，中位亮度 "
                f"{measurements.luminance.p50:.2f}。",
                ("technicalQuality.exposure", "measurement.luminance.p50"),
            )
        )
    clipping = measurements.clipping
    if clipping.highlights_pct <= 1.0 and clipping.shadows_pct <= 1.0:
        points.append(
            _point(
                f"高光与暗部几乎没有裁切（{clipping.highlights_pct:.1f}% / "
                f"{clipping.shadows_pct:.1f}%），层次保留完整。",
                ("measurement.clipping.highlightsPct", "measurement.clipping.shadowsPct"),
            )
        )
    luminance = measurements.luminance
    if luminance.std >= 0.18:
        points.append(
            _point(
                f"亮度分布有层次（标准差 {luminance.std:.2f}，"
                f"p1–p99 = {luminance.p1:.2f}–{luminance.p99:.2f}）。",
                (
                    "measurement.luminance.std",
                    "measurement.luminance.p1",
                    "measurement.luminance.p99",
                ),
            )
        )
    detail = measurements.detail
    if quality.sharpness is SharpnessQuality.GOOD or detail.sharpness >= 0.25:
        points.append(
            _point(
                f"细节与边缘{_SHARPNESS_LABELS.get(quality.sharpness, '保留尚可')}"
                f"（清晰度 {detail.sharpness:.3f}）。",
                ("measurement.detail.sharpness", "technicalQuality.sharpness"),
            )
        )
    if quality.noise is NoiseLevel.LOW or detail.noise_estimate <= 0.15:
        points.append(
            _point(
                f"噪声水平{_NOISE_LABELS.get(quality.noise, '可控')}"
                f"（估计值 {detail.noise_estimate:.2f}）。",
                ("measurement.detail.noiseEstimate", "technicalQuality.noise"),
            )
        )
    if report.color.harmony is ColorHarmony.HARMONIOUS:
        points.append(_point("色彩关系协调，主次颜色没有互相干扰。", ("color.harmony",)))
    if report.composition.balance is CompositionBalance.BALANCED:
        points.append(_point("画面重心平衡，观感稳定。", ("composition.balance",)))
    return tuple(points[:_LIMIT])


def _objective(report: AnalysisReport) -> tuple[CritiquePoint, ...]:
    """The measurable characteristics of the frame: light, exposure, colour, detail."""
    points: list[CritiquePoint] = []
    lighting = report.lighting
    composition = report.composition
    measurements = report.measurements
    quality = report.technical_quality

    if report.scene.primary in _SCENE_LABELS:
        points.append(
            _point(
                f"场景判定为{_SCENE_LABELS[report.scene.primary]}"
                f"（置信度 {report.scene.confidence:.0%}）。",
                ("scene.primary", "scene.confidence"),
            )
        )

    lighting_parts: list[str] = []
    lighting_refs: list[str] = []
    if lighting.type in _LIGHTING_TYPE_LABELS:
        lighting_parts.append(_LIGHTING_TYPE_LABELS[lighting.type])
        lighting_refs.append("lighting.type")
    if lighting.direction in _DIRECTION_LABELS:
        lighting_parts.append(_DIRECTION_LABELS[lighting.direction])
        lighting_refs.append("lighting.direction")
    if lighting.contrast in _CONTRAST_LABELS:
        lighting_parts.append(f"反差{_CONTRAST_LABELS[lighting.contrast]}")
        lighting_refs.append("lighting.contrast")
    if lighting_parts:
        points.append(_point("光线特点：" + "、".join(lighting_parts) + "。", tuple(lighting_refs)))

    if quality.exposure in _EXPOSURE_LABELS:
        luminance = measurements.luminance
        points.append(
            _point(
                f"曝光判定为{_EXPOSURE_LABELS[quality.exposure]}，中位亮度 "
                f"{luminance.p50:.2f}，p1–p99 = {luminance.p1:.2f}–{luminance.p99:.2f}。",
                (
                    "technicalQuality.exposure",
                    "measurement.luminance.p50",
                    "measurement.luminance.p1",
                    "measurement.luminance.p99",
                ),
            )
        )

    clipping = measurements.clipping
    points.append(
        _point(
            f"高光裁切 {clipping.highlights_pct:.1f}%，暗部裁切 {clipping.shadows_pct:.1f}%。",
            ("measurement.clipping.highlightsPct", "measurement.clipping.shadowsPct"),
        )
    )

    cast = measurements.color.cast
    color_parts: list[str] = []
    color_refs: list[str] = []
    if report.color.temperature in _COLOR_TEMPERATURE_LABELS:
        color_parts.append(
            f"色温{_COLOR_TEMPERATURE_LABELS[report.color.temperature]}"
            f"（偏移 {cast.temperature:+.3f}/{cast.tint:+.3f}）"
        )
        color_refs += ["color.temperature", "measurement.color.cast.temperature"]
    if report.color.saturation in _SATURATION_LABELS:
        color_parts.append(
            f"饱和度{_SATURATION_LABELS[report.color.saturation]}"
            f"（均值 {measurements.color.saturation_mean:.2f}）"
        )
        color_refs += ["color.saturation", "measurement.color.saturationMean"]
    if report.color.harmony in _HARMONY_LABELS:
        color_parts.append(f"色彩关系{_HARMONY_LABELS[report.color.harmony]}")
        color_refs.append("color.harmony")
    if color_parts:
        points.append(_point("色彩特点：" + "、".join(color_parts) + "。", tuple(color_refs)))

    detail = measurements.detail
    points.append(
        _point(
            f"清晰度 {detail.sharpness:.3f}"
            f"（{_SHARPNESS_LABELS.get(quality.sharpness, '未判定')}），噪声估计 "
            f"{detail.noise_estimate:.2f}（{_NOISE_LABELS.get(quality.noise, '未判定')}）。",
            (
                "measurement.detail.sharpness",
                "measurement.detail.noiseEstimate",
                "technicalQuality.sharpness",
                "technicalQuality.noise",
            ),
        )
    )

    if composition.balance in _BALANCE_LABELS:
        composition_parts = [f"重心{_BALANCE_LABELS[composition.balance]}"]
        composition_refs = ["composition.balance"]
        if composition.negative_space in _NEGATIVE_LABELS:
            composition_parts.append(f"负空间{_NEGATIVE_LABELS[composition.negative_space]}")
            composition_refs.append("composition.negativeSpace")
        if composition.subject_position in _POSITION_LABELS:
            composition_parts.append(f"主体位于{_POSITION_LABELS[composition.subject_position]}")
            composition_refs.append("composition.subjectPosition")
        points.append(
            _point(
                "构图特征：" + "、".join(composition_parts) + "。",
                tuple(composition_refs),
            )
        )
    return tuple(points[:_LIMIT])


def _problems(diagnosis: DiagnosisResult) -> tuple[CritiquePoint, ...]:
    """Stage 3 issues are inferences from measurements, so all stay advisory."""
    points = [
        _point(
            _problem_text(item, is_possible=False),
            item.evidence_refs,
        )
        for item in diagnosis.confirmed
    ]
    points += [
        _point(_problem_text(item, is_possible=True), item.evidence_refs)
        for item in diagnosis.possible
    ]
    return tuple(points[:_LIMIT])


def _problem_text(item: DiagnosisItem, *, is_possible: bool) -> str:
    label = _ISSUE_LABELS.get(item.type, item.type.value)
    tail = ""
    if not is_possible:
        tail = "；测量值支持该判断"
    elif item.confidence < _WEAK_CONFIDENCE:
        tail = "；置信度较低，仅供参考"
    else:
        tail = "；可能是刻意的创作选择，先确认意图再处理"
    return (
        f"{label}（{_SEVERITY_LABELS[item.severity]}，置信度 {item.confidence:.0%}）："
        f"{item.evidence.rstrip('。；')}{tail}。"
    )


def _creative(report: AnalysisReport) -> tuple[CritiqueCreative, ...]:
    notes = [
        _creative_note(choice.description, choice.evidence_refs)
        for choice in creative_choices(report)
    ]
    lighting = report.lighting
    composition = report.composition

    if lighting.direction in {LightingDirection.BACK, LightingDirection.SIDE_BACK}:
        notes.append(
            _creative_note(
                f"{_DIRECTION_LABELS[lighting.direction]}带来的轮廓与氛围可能是这张照片的情绪"
                "来源，不一定要把主体提亮。",
                ("lighting.direction",),
            )
        )
    if is_low_key(report) or is_high_key(report):
        notes.append(
            _creative_note(
                "暗调或亮调如果是刻意的，后续应保留这种基调，只修正真正丢失的细节。",
                ("measurement.luminance.p50", "measurement.luminance.p1"),
            )
        )
    if report.color.temperature in _COLOR_TEMPERATURE_LABELS and not is_strong_color_cast(report):
        notes.append(
            _creative_note(
                f"整体{_COLOR_TEMPERATURE_LABELS[report.color.temperature]}的色温可能是现场氛围"
                "的一部分，白平衡校正会直接改变它。",
                ("color.temperature", "measurement.color.cast.temperature"),
            )
        )
    if is_high_saturation(report) or is_low_saturation(report):
        notes.append(
            _creative_note(
                "当前的饱和水平本身可能是一种取舍：追求记录感还是氛围感，会得到不同的调整方向。",
                ("color.saturation", "measurement.color.saturationMean"),
            )
        )
    if composition.balance in {CompositionBalance.UNBALANCED, CompositionBalance.MODERATE}:
        notes.append(
            _creative_note(
                "重心偏移如果是刻意的，可以保留为不安定感；否则优先通过裁切而不是参数来解决。",
                ("composition.balance",),
            )
        )
    if composition.negative_space is NegativeSpace.HIGH:
        notes.append(
            _creative_note(
                "负空间充足，主体周围可以再留白，视觉重点未必需要靠加强对比来建立。",
                ("composition.negativeSpace",),
            )
        )
    if is_high_contrast(report):
        notes.append(
            _creative_note(
                "强反差可以维持戏剧感，降低对比会让画面变温和，两种方向取决于表达意图。",
                ("lighting.contrast", "measurement.luminance.std"),
            )
        )
    if is_warm_ambient(report) or is_cool_ambient(report):
        notes.append(
            _creative_note(
                "暖冷倾向已经形成基调，风格化时可以选择顺着它强化，而不是把它校正为中性。",
                ("color.temperature", "lighting.type"),
            )
        )
    return tuple(notes[:_LIMIT])


def _suggestions(
    report: AnalysisReport,
    diagnosis: DiagnosisResult,
    preferences: PhotographerPreferences,
) -> tuple[CritiqueSuggestion, ...]:
    items = [*diagnosis.confirmed, *diagnosis.possible]
    suggestions: list[CritiqueSuggestion] = []

    for item in items:
        advice = _ADVICE.get(item.type)
        if advice is None:
            continue
        category, text = advice
        patch: AdjustmentIntent = issue_adjustments(report, item.type, preferences)
        has_patch = bool(patch.model_dump(exclude_none=True))
        suggestions.append(
            CritiqueSuggestion(
                text=text,
                category=category,
                evidence_refs=item.evidence_refs,
                recipe_patch=patch if has_patch else None,
            )
        )
    return tuple(suggestions[:_LIMIT])


def _limitations(report: AnalysisReport) -> tuple[str, ...]:
    notes = [
        "点评由确定性规则生成（generatedBy=deterministic-rules），未调用语言模型。",
        "创作评价是主观判断，不代表客观质量结论。",
    ]
    if report.engine.is_mock:
        notes.append("本次分析来自模拟视觉引擎，点评只用于流程验证。")
    notes += [f"分析限制：{item}" for item in report.limitations]
    return tuple(dict.fromkeys(notes))[:_LIMIT]


def _point(text: str, refs: tuple[str, ...]) -> CritiquePoint:
    return CritiquePoint(text=text, evidence_refs=refs[:_LIMIT])


def _creative_note(text: str, refs: tuple[str, ...]) -> CritiqueCreative:
    return CritiqueCreative(text=text, evidence_refs=refs[:_LIMIT], subjective=True)


__all__ = ["CRITIQUE_GENERATED_BY", "build_critique"]
