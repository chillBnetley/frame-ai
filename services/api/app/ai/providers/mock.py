from __future__ import annotations

from app.ai.base import DecisionRequest, VisionRequest
from app.ai.contracts import (
    BBox,
    ColorHarmony,
    ColorResult,
    ColorTemperature,
    CompositionBalance,
    CompositionResult,
    ContrastLevel,
    DecisionResult,
    ExposureQuality,
    IssueCandidate,
    IssueSelection,
    IssueType,
    LightingDirection,
    LightingResult,
    LightingType,
    MeasurementSummary,
    NegativeSpace,
    NoiseLevel,
    Occlusion,
    Priority,
    RecommendationCategory,
    RecommendationResult,
    SaturationLevel,
    SceneLabel,
    SceneResult,
    Severity,
    SharpnessQuality,
    SubjectPosition,
    SubjectResult,
    SubjectRole,
    SubjectType,
    TechnicalQualityResult,
    VisionResult,
)

MOCK_LIMITATION = "模拟数据：未调用真实视觉模型。"
MOCK_DECISION_LIMITATION = "模拟数据：未调用真实决策模型。"


def _unknown_lighting() -> LightingResult:
    return LightingResult(
        direction=LightingDirection.UNKNOWN,
        type=LightingType.UNKNOWN,
        contrast=ContrastLevel.UNKNOWN,
        confidence=0.0,
    )


def _unknown_color() -> ColorResult:
    return ColorResult(
        temperature=ColorTemperature.UNKNOWN,
        saturation=SaturationLevel.UNKNOWN,
        confidence=0.0,
    )


def _unknown_composition() -> CompositionResult:
    return CompositionResult(
        balance=CompositionBalance.UNKNOWN,
        subject_position=SubjectPosition.UNKNOWN,
        negative_space=NegativeSpace.UNKNOWN,
        confidence=0.0,
    )


_GENERIC = VisionResult(
    scene=SceneResult(primary=SceneLabel.OTHER, confidence=0.0),
    subjects=(),
    lighting=_unknown_lighting(),
    color=_unknown_color(),
    composition=_unknown_composition(),
    limitations=(MOCK_LIMITATION, "未配置模拟场景，返回空语义结果。"),
)

_PORTRAIT = VisionResult(
    scene=SceneResult(
        primary=SceneLabel.PORTRAIT,
        secondary=(SceneLabel.STREET,),
        confidence=0.5,
    ),
    subjects=(
        SubjectResult(
            type=SubjectType.PERSON,
            role=SubjectRole.PRIMARY,
            confidence=0.5,
            bbox=BBox(x=0.22, y=0.12, width=0.42, height=0.78),
        ),
    ),
    lighting=LightingResult(
        direction=LightingDirection.SIDE,
        type=LightingType.NATURAL,
        contrast=ContrastLevel.MODERATE,
        confidence=0.4,
    ),
    color=ColorResult(
        temperature=ColorTemperature.WARM,
        saturation=SaturationLevel.MODERATE,
        harmony=ColorHarmony.HARMONIOUS,
        dominant_colors=("#C58B6A", "#44525C"),
        confidence=0.4,
    ),
    composition=CompositionResult(
        balance=CompositionBalance.MODERATE,
        subject_position=SubjectPosition.CENTER,
        negative_space=NegativeSpace.MODERATE,
        occlusion=Occlusion.NONE,
        confidence=0.4,
    ),
    limitations=(MOCK_LIMITATION,),
)

_LANDSCAPE = VisionResult(
    scene=SceneResult(
        primary=SceneLabel.LANDSCAPE,
        secondary=(SceneLabel.NATURE,),
        confidence=0.5,
    ),
    subjects=(
        SubjectResult(
            type=SubjectType.SKY,
            role=SubjectRole.PRIMARY,
            confidence=0.5,
            bbox=BBox(x=0.0, y=0.0, width=1.0, height=0.45),
        ),
        SubjectResult(
            type=SubjectType.PLANT,
            role=SubjectRole.SECONDARY,
            confidence=0.4,
            bbox=BBox(x=0.0, y=0.5, width=1.0, height=0.5),
        ),
    ),
    lighting=LightingResult(
        direction=LightingDirection.FRONT,
        type=LightingType.NATURAL,
        contrast=ContrastLevel.LOW,
        confidence=0.4,
    ),
    color=ColorResult(
        temperature=ColorTemperature.NEUTRAL,
        saturation=SaturationLevel.MODERATE,
        harmony=ColorHarmony.HARMONIOUS,
        dominant_colors=("#5B7FA6", "#6E7B4F"),
        confidence=0.4,
    ),
    composition=CompositionResult(
        balance=CompositionBalance.BALANCED,
        subject_position=SubjectPosition.CENTER,
        negative_space=NegativeSpace.HIGH,
        occlusion=Occlusion.NONE,
        confidence=0.4,
    ),
    limitations=(MOCK_LIMITATION,),
)

_LOW_LIGHT = VisionResult(
    scene=SceneResult(
        primary=SceneLabel.NIGHT,
        secondary=(SceneLabel.STREET,),
        confidence=0.5,
    ),
    subjects=(
        SubjectResult(
            type=SubjectType.BUILDING,
            role=SubjectRole.PRIMARY,
            confidence=0.5,
            bbox=BBox(x=0.05, y=0.1, width=0.9, height=0.85),
        ),
    ),
    lighting=LightingResult(
        direction=LightingDirection.ARTIFICIAL,
        type=LightingType.MIXED,
        contrast=ContrastLevel.HIGH,
        confidence=0.4,
    ),
    color=ColorResult(
        temperature=ColorTemperature.COOL,
        saturation=SaturationLevel.HIGH,
        harmony=ColorHarmony.MODERATE,
        dominant_colors=("#1B2330", "#D9A05B"),
        confidence=0.4,
    ),
    composition=CompositionResult(
        balance=CompositionBalance.MODERATE,
        subject_position=SubjectPosition.CENTER,
        negative_space=NegativeSpace.LOW,
        occlusion=Occlusion.MINOR,
        confidence=0.4,
    ),
    limitations=(MOCK_LIMITATION,),
)

_BACKLIT = VisionResult(
    scene=SceneResult(
        primary=SceneLabel.PORTRAIT,
        secondary=(SceneLabel.NATURE,),
        confidence=0.5,
    ),
    subjects=(
        SubjectResult(
            type=SubjectType.PERSON,
            role=SubjectRole.PRIMARY,
            confidence=0.5,
            bbox=BBox(x=0.3, y=0.15, width=0.4, height=0.75),
        ),
    ),
    lighting=LightingResult(
        direction=LightingDirection.BACK,
        type=LightingType.NATURAL,
        contrast=ContrastLevel.HIGH,
        confidence=0.4,
    ),
    color=ColorResult(
        temperature=ColorTemperature.WARM,
        saturation=SaturationLevel.MODERATE,
        harmony=ColorHarmony.MODERATE,
        dominant_colors=("#E8C08A", "#3A3F4A"),
        confidence=0.4,
    ),
    composition=CompositionResult(
        balance=CompositionBalance.MODERATE,
        subject_position=SubjectPosition.CENTER,
        negative_space=NegativeSpace.MODERATE,
        occlusion=Occlusion.NONE,
        confidence=0.4,
    ),
    limitations=(MOCK_LIMITATION,),
)

_SCENARIOS: dict[str, VisionResult] = {
    "generic": _GENERIC,
    "portrait": _PORTRAIT,
    "landscape": _LANDSCAPE,
    "low_light": _LOW_LIGHT,
    "backlit": _BACKLIT,
}

_RECOMMENDATIONS: dict[IssueType, tuple[RecommendationCategory, str]] = {
    IssueType.OVEREXPOSURE: (
        RecommendationCategory.EXPOSURE,
        "降低曝光补偿，优先保护高光细节。",
    ),
    IssueType.UNDEREXPOSURE: (
        RecommendationCategory.EXPOSURE,
        "适度提高曝光，并检查暗部是否仍保留可恢复细节。",
    ),
    IssueType.HIGHLIGHT_CLIPPING: (
        RecommendationCategory.EXPOSURE,
        "优先降低高光或使用高光恢复，避免裁切区域继续扩大。",
    ),
    IssueType.SHADOW_CLIPPING: (
        RecommendationCategory.EXPOSURE,
        "在保持黑位的前提下适度提亮阴影，避免暗部细节完全丢失。",
    ),
    IssueType.SUBJECT_UNDEREXPOSURE: (
        RecommendationCategory.LIGHTING,
        "对主体区域进行局部提亮，缩小主体与背景的亮度差。",
    ),
    IssueType.BACKGROUND_OVEREXPOSURE: (
        RecommendationCategory.LIGHTING,
        "压低背景高光或调整拍摄角度，避免背景压过主体。",
    ),
    IssueType.COLOR_CAST: (
        RecommendationCategory.COLOR,
        "以中性灰或白平衡参考校正色偏，避免整体偏色。",
    ),
    IssueType.TEMPERATURE_MISMATCH: (
        RecommendationCategory.COLOR,
        "统一画面色温，避免主体与背景冷暖冲突。",
    ),
    IssueType.SATURATION_ISSUE: (
        RecommendationCategory.COLOR,
        "调整整体饱和度，优先恢复肤色和自然质感。",
    ),
    IssueType.COLOR_HIERARCHY_ISSUE: (
        RecommendationCategory.COLOR,
        "区分主体与背景的色彩层次，避免主次颜色过于接近。",
    ),
    IssueType.SUBJECT_PLACEMENT: (
        RecommendationCategory.COMPOSITION,
        "重新安排主体位置，使其避开画面边缘并留出视线空间。",
    ),
    IssueType.BALANCE_ISSUE: (
        RecommendationCategory.COMPOSITION,
        "调整主体或负空间比例，改善画面重心。",
    ),
    IssueType.NEGATIVE_SPACE_ISSUE: (
        RecommendationCategory.COMPOSITION,
        "增加或收紧负空间，让主体与背景关系更明确。",
    ),
    IssueType.HORIZON_TILT: (
        RecommendationCategory.COMPOSITION,
        "校正地平线，使水平参考保持稳定。",
    ),
    IssueType.FOCUS_ISSUE: (
        RecommendationCategory.SHARPNESS,
        "重新对焦主体，必要时缩小光圈增加景深。",
    ),
    IssueType.MOTION_BLUR: (
        RecommendationCategory.SHARPNESS,
        "提高快门速度或稳定相机，减少运动模糊。",
    ),
    IssueType.HIGH_NOISE: (
        RecommendationCategory.SHARPNESS,
        "降低 ISO 或增加后期降噪，避免细节被噪点掩盖。",
    ),
    IssueType.LOW_DETAIL: (
        RecommendationCategory.SHARPNESS,
        "检查对焦与镜头素质，必要时增加局部锐化。",
    ),
    IssueType.HARSH_CONTRAST: (
        RecommendationCategory.LIGHTING,
        "平衡高光与阴影，降低过强的明暗反差。",
    ),
    IssueType.FLAT_LIGHTING: (
        RecommendationCategory.LIGHTING,
        "增加方向光或局部对比，让主体与背景分离。",
    ),
}

_SEVERITY_RANK = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
_PRIORITY = {
    Severity.HIGH: Priority.HIGH,
    Severity.MEDIUM: Priority.MEDIUM,
    Severity.LOW: Priority.LOW,
}


class MockVisionProvider:
    name = "mock"
    model = "mock-vision"
    is_mock = True

    def __init__(self, scenario: str = "generic") -> None:
        self.scenario = scenario if scenario in _SCENARIOS else "generic"

    def analyze(self, request: VisionRequest) -> VisionResult:
        del request
        return _SCENARIOS[self.scenario]

    def check_connection(self, *, timeout: float | None = None) -> int:
        del timeout
        return 0


class MockDecisionProvider:
    name = "mock"
    model = "mock-decision"
    is_mock = True

    def diagnose(self, request: DecisionRequest) -> DecisionResult:
        selected = _select_candidates(request.candidates)
        issues = tuple(
            IssueSelection(
                candidate_id=candidate.id,
                severity=candidate.severity,
                confidence=candidate.confidence,
                evidence=candidate.evidence,
                region_ids=candidate.region_ids,
            )
            for candidate in selected
        )
        recommendations = tuple(_recommendation(candidate) for candidate in selected)
        return DecisionResult(
            technical_quality=_technical_quality(request.measurements),
            issues=issues,
            recommendations=recommendations,
            limitations=(
                MOCK_DECISION_LIMITATION,
                "建议由确定性候选生成，仅用于开发和测试。",
            ),
        )

    def check_connection(self, *, timeout: float | None = None) -> int:
        del timeout
        return 0


def _select_candidates(candidates: tuple[IssueCandidate, ...]) -> tuple[IssueCandidate, ...]:
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            _SEVERITY_RANK[candidate.severity],
            -candidate.confidence,
            candidate.id,
        ),
    )
    return tuple(ordered[:3])


def _recommendation(candidate: IssueCandidate) -> RecommendationResult:
    category, action = _RECOMMENDATIONS[candidate.type]
    return RecommendationResult(
        category=category,
        priority=_PRIORITY[candidate.severity],
        description=f"{action}（依据：{candidate.evidence}）",
        target_regions=candidate.region_ids,
    )


def _technical_quality(measurements: MeasurementSummary) -> TechnicalQualityResult:
    if measurements.luminance_p50 < 0.18:
        exposure = ExposureQuality.SLIGHTLY_UNDEREXPOSED
    elif measurements.luminance_p50 > 0.82:
        exposure = ExposureQuality.SLIGHTLY_OVEREXPOSED
    else:
        exposure = ExposureQuality.BALANCED

    if measurements.sharpness < 0.08:
        sharpness = SharpnessQuality.POOR
    elif measurements.sharpness < 0.2:
        sharpness = SharpnessQuality.SOFT
    else:
        sharpness = SharpnessQuality.GOOD

    if measurements.noise_estimate > 0.5:
        noise = NoiseLevel.HIGH
    elif measurements.noise_estimate > 0.25:
        noise = NoiseLevel.MODERATE
    else:
        noise = NoiseLevel.LOW

    return TechnicalQualityResult(
        exposure=exposure,
        sharpness=sharpness,
        noise=noise,
        confidence=0.3,
    )


__all__ = [
    "MOCK_DECISION_LIMITATION",
    "MOCK_LIMITATION",
    "MockDecisionProvider",
    "MockVisionProvider",
]
