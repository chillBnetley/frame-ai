from __future__ import annotations

import math

from app.ai.base import (
    DecisionRequest,
    PatchRequest,
    PlannerRequest,
    StyleAuthoringRequest,
    VisionRequest,
)
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
from app.ai.prompts import PLANNER_PROMPT_VERSION
from app.models.personal_style import PersonalAvoidEffect
from app.models.photographer import (
    AdjustmentIntent,
    DirectionConstraint,
    LocalAdjustmentIntent,
    PatchDraft,
    PlannerDraft,
)
from app.models.style_authoring import StyleAuthoringDraft
from app.models.style_profile import (
    StyleColorTraits,
    StyleCompositionTraits,
    StyleLightTraits,
    StyleTextureTraits,
)
from app.photographer.diagnosis import diagnose
from app.photographer.direction import determine_direction
from app.photographer.local_strategy import semantic_local_intent
from app.photographer.rules import round2, suggest_adjustments
from app.photographer.style_generation import dynamic_style_adjustments
from app.styles.vocabulary import SCENE_NAMES

MOCK_LIMITATION = "模拟数据：未调用真实视觉模型。"
MOCK_DECISION_LIMITATION = "模拟数据：未调用真实决策模型。"
MOCK_PLANNER_LIMITATION = "模拟数据：未调用真实规划模型。"
MOCK_PLANNER_MASK_LIMITATION = "阶段三没有语义蒙版；未自动生成局部调整。"
MOCK_PLANNER_MASK_LOCAL_LIMITATION = "局部调整只作用于你已有的蒙版；阶段三无法识别蒙版内容。"
MOCK_PLANNER_BOUNDARY_LIMITATION = "模拟规划器只识别常见曝光、色彩与细节指令。"
MOCK_AUTHORING_LIMITATION = "模拟数据：自然语言风格由关键词规则解析，未调用真实语言模型。"
MOCK_AUTHORING_BOUNDARY = "只生成色彩、影调、光线、质感与场景约束，不包含生成式修改。"


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


def _planner_adjustments(request: PlannerRequest, dynamic: dict[str, float]) -> AdjustmentIntent:
    base = suggest_adjustments(
        request.analysis,
        request.preferences,
        request.style,
    ).model_dump(by_alias=True, exclude_none=True)
    if not dynamic:
        return AdjustmentIntent(**base)
    merged: dict[str, float] = {field: float(value) for field, value in base.items()}
    for field, delta in dynamic.items():
        merged[field] = merged.get(field, 0.0) + delta
    return AdjustmentIntent(
        **{field: round2(value) for field, value in merged.items() if abs(value) >= 0.005}
    )


def _semantic_local_adjustments(
    request: PlannerRequest,
) -> tuple[LocalAdjustmentIntent, ...]:
    context = request.style_context
    if context is None:
        return ()
    intents: list[LocalAdjustmentIntent] = []
    for mask in request.recipe.masks:
        if mask.source != "semantic" or mask.semantic_class is None:
            continue
        values = semantic_local_intent(
            mask.semantic_class,
            context.strength,
            context.conversion_mode,
        )
        if values:
            intents.append(
                LocalAdjustmentIntent(
                    mask_id=mask.id,
                    adjustments=AdjustmentIntent(**values),
                )
            )
    return tuple(intents)


class MockPlannerProvider:
    name = "mock"
    model = "mock-planner"
    is_mock = True
    prompt_version = PLANNER_PROMPT_VERSION

    def plan(self, request: PlannerRequest) -> PlannerDraft:
        diagnosis = diagnose(request.analysis)
        direction = determine_direction(
            request.analysis,
            diagnosis,
            request.preferences,
            request.style,
            style_strength=request.style_strength,
        )
        context = request.style_context
        dynamic = (
            dynamic_style_adjustments(
                context.profile,
                request.analysis,
                mode=context.conversion_mode,
                strength=context.strength,
                preferences=request.preferences,
            )
            if context is not None
            else {}
        )
        adjustments = _planner_adjustments(request, dynamic)
        local_adjustments = _semantic_local_adjustments(request)
        if context is not None:
            fit = context.fit
            rationale = [
                f"依据「{context.profile.name}」档案与阶段三证据制定方案。",
                f"适配度 {fit.overall_score:.0f}（{fit.overall_level.value}）：{fit.summary}",
                f"转换模式 {context.conversion_mode.value}，强度 {context.strength:.2f}。",
            ]
        else:
            rationale = [
                "根据阶段三的诊断证据与场景规则生成方案。",
                "参数幅度受自然度、调整强度与风格包络共同限制。",
            ]
        if diagnosis.creative_choices:
            rationale.append("低曝光、低饱和或暖色等表现被视为创作选择，未机械纠正。")
        if local_adjustments:
            rationale.append("局部调整只作用于已准备好的真实语义蒙版。")

        warnings: list[str] = []
        if not request.analysis.issues and context is None:
            warnings.append("阶段三未提供明确问题，方案以保持自然观感为主。")
        if not adjustments.model_dump(exclude_none=True):
            warnings.append("当前画面已接近自然平衡，未生成参数调整。")

        limitations = [MOCK_PLANNER_LIMITATION, MOCK_PLANNER_MASK_LIMITATION]
        if context is not None and dynamic:
            limitations.append("模拟规划器以确定性规则近似档案特征，真实效果需由真实模型生成。")

        return PlannerDraft(
            diagnosis=diagnosis,
            direction=direction,
            adjustments=adjustments,
            local_adjustments=local_adjustments,
            rationale=tuple(rationale),
            warnings=tuple(warnings),
            limitations=tuple(limitations),
            confidence=diagnosis.confidence,
        )

    def adjust(self, request: PatchRequest) -> PatchDraft:
        instruction = request.instruction
        unsupported = _unsupported_capability(instruction)
        if unsupported is not None:
            return PatchDraft(
                supported=False,
                adjustments=None,
                reason="当前版本不支持该项操作，配方保持不变。",
                warnings=(),
                limitations=(MOCK_PLANNER_LIMITATION,),
                unsupported=(unsupported,),
                confidence=0.3,
            )

        if _targets_local_region(instruction):
            return _region_patch(request, instruction)

        if _needs_channel_control(instruction):
            return PatchDraft(
                supported=True,
                adjustments=None,
                reason="该指令针对单个颜色通道，对话调整不修改 HSL 与曲线。",
                warnings=("请在 HSL 面板手动调整对应色相、饱和度与明度。",),
                limitations=(MOCK_PLANNER_LIMITATION, MOCK_PLANNER_BOUNDARY_LIMITATION),
                unsupported=(),
                confidence=0.3,
            )

        values, notes = _patch_values(instruction)
        values, notes = _protect_skin_tone(instruction, values, notes)
        if not values:
            return PatchDraft(
                supported=True,
                adjustments=None,
                reason="未识别到可执行的参数调整，配方保持不变。",
                warnings=("只能调整曝光、色彩、清晰度与降噪等常见参数。", *notes),
                limitations=(MOCK_PLANNER_LIMITATION, MOCK_PLANNER_BOUNDARY_LIMITATION),
                unsupported=(),
                confidence=0.3,
            )

        adjustments = AdjustmentIntent(
            **{field: round(value + 0.0, 2) for field, value in values.items()}
        )
        labels = "、".join(_INTENT_LABELS[field] for field in values)
        return PatchDraft(
            supported=True,
            adjustments=adjustments,
            reason=f"只调整{labels}，保留其他编辑。",
            warnings=tuple(notes),
            limitations=(MOCK_PLANNER_LIMITATION,),
            unsupported=(),
            confidence=0.6,
        )

    def author_style(self, request: StyleAuthoringRequest) -> StyleAuthoringDraft:
        return _mock_author_style(request)

    def check_connection(self, *, timeout: float | None = None) -> int:
        del timeout
        return 0


_MOCK_SCENE_WORDS: tuple[tuple[tuple[str, ...], SceneLabel], ...] = (
    (("街头", "street", "纪实"), SceneLabel.STREET),
    (("人像", "portrait", "人物"), SceneLabel.PORTRAIT),
    (("建筑", "architecture"), SceneLabel.ARCHITECTURE),
    (("风光", "风景", "landscape"), SceneLabel.LANDSCAPE),
    (("夜景", "night"), SceneLabel.NIGHT),
    (("室内", "indoor"), SceneLabel.INDOOR),
    (("美食", "food"), SceneLabel.FOOD),
    (("自然风光", "自然景观", "nature scene", "wilderness", "森林", "山野"), SceneLabel.NATURE),
)
_MOCK_AVOID_WORDS: tuple[tuple[tuple[str, ...], PersonalAvoidEffect], ...] = (
    (("过饱和", "太浓", "too saturated"), PersonalAvoidEffect.OVERSATURATED),
    (("压黑", "死黑", "暗部太黑", "crushed black"), PersonalAvoidEffect.CRUSHED_BLACKS),
    (("高光", "过曝", "爆掉", "clipped highlight"), PersonalAvoidEffect.CLIPPED_HIGHLIGHTS),
    (("偏色", "色偏", "偏冷", "偏暖", "color cast"), PersonalAvoidEffect.COLOR_CAST),
    (("肤色", "skin"), PersonalAvoidEffect.UNNATURAL_SKIN),
    (("滤镜", "filter"), PersonalAvoidEffect.HEAVY_FILTER),
    (("锐化", "over sharp", "过度锐"), PersonalAvoidEffect.OVER_SHARPENED),
    (("反差太强", "对比太强", "flat contrast"), PersonalAvoidEffect.FLAT_CONTRAST),
)
_AVOID_CONSTRAINTS = {
    PersonalAvoidEffect.OVERSATURATED: DirectionConstraint.AVOID_EXTREME_SATURATION,
    PersonalAvoidEffect.CRUSHED_BLACKS: DirectionConstraint.PRESERVE_SHADOW_DETAIL,
    PersonalAvoidEffect.CLIPPED_HIGHLIGHTS: DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL,
    PersonalAvoidEffect.COLOR_CAST: DirectionConstraint.AVOID_COLOR_CAST,
    PersonalAvoidEffect.UNNATURAL_SKIN: DirectionConstraint.PRESERVE_SKIN_TONE,
    PersonalAvoidEffect.HEAVY_FILTER: DirectionConstraint.NATURAL_LOOK,
    PersonalAvoidEffect.OVER_SHARPENED: DirectionConstraint.NATURAL_LOOK,
    PersonalAvoidEffect.FLAT_CONTRAST: DirectionConstraint.AVOID_EXTREME_CONTRAST,
}


def _contains(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _clamp_target(value: float) -> float:
    return round(min(max(value, -100.0), 100.0), 2)


def _detect_scenes(text: str, hints: tuple[SceneLabel, ...]) -> tuple[SceneLabel, ...]:
    if hints:
        return hints
    detected = [scene for words, scene in _MOCK_SCENE_WORDS if _contains(text, *words)]
    return tuple(dict.fromkeys(detected)) or (SceneLabel.OTHER,)


def _detect_avoid(text: str) -> tuple[PersonalAvoidEffect, ...]:
    if not text:
        return ()
    return tuple(
        dict.fromkeys(effect for words, effect in _MOCK_AVOID_WORDS if _contains(text, *words))
    )


def _avoid_constraints(effects: tuple[PersonalAvoidEffect, ...]) -> set[DirectionConstraint]:
    return {_AVOID_CONSTRAINTS[effect] for effect in effects}


def _set_target(targets: dict[str, float], field: str, value: float) -> None:
    targets[field] = _clamp_target(value)


def _mock_author_style(request: StyleAuthoringRequest) -> StyleAuthoringDraft:
    if request.base_profile is not None and request.instruction:
        return _mock_refine_style(request)
    text = f"{request.name} {request.description} {request.avoid_text or ''}"
    low_saturation = _contains(
        text, "低饱和", "克制", "去饱和", "淡", "less saturated", "restrained"
    )
    high_saturation = _contains(text, "高饱和", "鲜艳", "浓郁", "vivid", "saturated")
    monochrome = _contains(text, "黑白", "单色", "monochrome", "black and white")
    cool = _contains(text, "冷", "冷色", "偏冷", "cool", "blue")
    warm = _contains(text, "暖", "暖色", "偏暖", "warm", "golden")
    soft_contrast = _contains(text, "柔和", "低对比", "克制反差", "soft", "gentle")
    strong_contrast = _contains(text, "高对比", "强反差", "dramatic", "hard light")
    low_key = _contains(text, "低调", "暗调", "low key")
    high_key = _contains(text, "高调", "明亮", "high key")
    soft_light = _contains(text, "柔光", "漫射", "柔和光", "diffuse", "soft light")
    directional = _contains(text, "硬光", "方向光", "侧光", "逆光", "directional")
    grainy = _contains(text, "颗粒", "胶片", "grain", "film")
    clean = _contains(text, "细腻", "干净", "smooth", "clean")
    crisp = _contains(text, "锐", "清晰", "sharp", "crisp")
    minimal = _contains(text, "留白", "极简", "minimal", "negative space")
    symmetrical = _contains(text, "对称", "几何", "symmetry", "geometric")
    natural_skin = _contains(text, "肤色", "skin")
    avoid_requested = _detect_avoid(request.avoid_text or "")
    scenes = _detect_scenes(text, request.suitable_scenes)

    targets: dict[str, float] = {}
    if monochrome:
        _set_target(targets, "saturation", -100)
        _set_target(targets, "vibrance", 0)
    elif low_saturation:
        _set_target(targets, "saturation", -12)
    elif high_saturation:
        _set_target(
            targets,
            "saturation",
            3 if PersonalAvoidEffect.OVERSATURATED in avoid_requested else 6,
        )
    if cool and not warm:
        _set_target(targets, "temperature", -8)
    elif warm and not cool:
        _set_target(targets, "temperature", 8)
    if soft_contrast and not strong_contrast:
        _set_target(targets, "contrast", -6)
    elif strong_contrast and not soft_contrast:
        _set_target(targets, "contrast", 10)
    if grainy:
        _set_target(targets, "grain", 8)
    if crisp and not clean:
        _set_target(targets, "clarity", 5)

    protected = set(_avoid_constraints(avoid_requested))
    if natural_skin:
        protected.add(DirectionConstraint.PRESERVE_SKIN_TONE)
    if clean or _contains(text, "自然", "natural"):
        protected.add(DirectionConstraint.NATURAL_LOOK)
    if low_key:
        protected.add(DirectionConstraint.KEEP_LOW_KEY)

    saturation_text = (
        "去饱和至单色"
        if monochrome
        else "低饱和"
        if low_saturation
        else "高饱和"
        if high_saturation
        else "饱和度适中"
    )
    temperature_text = (
        "整体偏冷" if cool and not warm else "整体偏暖" if warm and not cool else "色温中性"
    )
    contrast_text = (
        "柔和反差"
        if soft_contrast and not strong_contrast
        else "强反差"
        if strong_contrast and not soft_contrast
        else "中等反差"
    )
    light_text = (
        "柔和漫射光"
        if soft_light and not directional
        else "方向性光线"
        if directional and not soft_light
        else "自然光优先"
    )
    grain_text = "颗粒感明显" if grainy else "颗粒克制"
    sharp_text = "清晰锐利" if crisp and not clean else "画面柔和" if clean else "清晰度自然"
    scene_names = "、".join(SCENE_NAMES[scene] for scene in scenes)

    rationale: list[str] = []
    if monochrome:
        rationale.append("识别到黑白或单色影调。")
    elif low_saturation:
        rationale.append("识别到低饱和或克制的色彩倾向。")
    if high_saturation:
        rationale.append("识别到高饱和或鲜明色彩倾向。")
    if cool or warm:
        rationale.append("识别到偏冷或偏暖的色温倾向。")
    if soft_contrast or strong_contrast:
        rationale.append("识别到明确的影调反差倾向。")
    if soft_light or directional:
        rationale.append("识别到光线柔和程度或方向性描述。")
    if grainy or clean or crisp:
        rationale.append("识别到颗粒、锐度或细节偏好。")
    if avoid_requested:
        rationale.append("识别到用户不希望出现的效果，已转换为保护约束。")
    warnings: list[str] = []
    if not rationale:
        warnings.append("未识别到明确的视觉偏好，已生成中性风格草稿。")
    if low_saturation and high_saturation:
        warnings.append("描述同时包含低饱和与高饱和倾向，已优先采用更克制的一侧。")
    if PersonalAvoidEffect.OVERSATURATED in avoid_requested and high_saturation:
        warnings.append("描述同时要求鲜明色彩并避免过饱和，已采用保守饱和度。")
    if request.avoid_text and not avoid_requested:
        warnings.append("回避描述未能映射到具体风格约束，请在确认前检查。")

    summary = (
        f"色彩：{temperature_text}，{saturation_text}；"
        f"影调：{contrast_text}；"
        f"光线：{light_text}；"
        f"质感：{grain_text}，{sharp_text}；"
        f"适用场景：{scene_names}。"
    )
    confidence = min(0.8, 0.4 + 0.05 * len(rationale)) if rationale else 0.35
    limitations = [MOCK_AUTHORING_LIMITATION, MOCK_AUTHORING_BOUNDARY]
    if _contains(text, "移除", "扩图", "替换天空", "生成式", "remove", "inpaint"):
        limitations.append("自然语言风格不包含物体移除、扩图或生成式内容修改。")

    return StyleAuthoringDraft(
        name=request.name,
        description=request.description,
        color=StyleColorTraits(
            tendency=f"{temperature_text}，{saturation_text}",
            relationships=(
                "避免明显偏色，保留环境色关系"
                if PersonalAvoidEffect.COLOR_CAST in avoid_requested
                else "环境色自然，主色与辅助色关系克制"
            ),
            saturation=saturation_text,
        ),
        light=StyleLightTraits(
            contrast=contrast_text,
            shadows=(
                "保留暗部层次"
                if PersonalAvoidEffect.CRUSHED_BLACKS in avoid_requested or low_key
                else "暗部开放"
                if high_key
                else "暗部自然"
            ),
            highlights=(
                "保护高光细节"
                if PersonalAvoidEffect.CLIPPED_HIGHLIGHTS in avoid_requested
                else "高光柔和"
            ),
            expression=light_text,
        ),
        composition=StyleCompositionTraits(
            space="负空间较多，画面留白清晰" if minimal else "负空间适中",
            geometry="对称或几何结构清晰" if symmetrical else "平衡构图",
            negative_space="较多" if minimal else "适中",
            subject_relation=(
                "主体与环境关系自然" if SceneLabel.PORTRAIT in scenes else "主体与环境保持克制关系"
            ),
        ),
        texture=StyleTextureTraits(
            grain=grain_text,
            sharpness=sharp_text,
            detail="保留较多细节" if crisp else "细节自然",
        ),
        suitable_scenes=scenes,
        unsuitable_notes="未覆盖场景需要重新适配；不包含物体移除、扩图或生成式修改。",
        targets=targets,
        protected=tuple(sorted(protected, key=lambda item: item.value))[:11],
        avoid=avoid_requested,
        summary=summary[:500],
        rationale=tuple(rationale),
        warnings=tuple(warnings),
        limitations=tuple(limitations),
        confidence=confidence,
    )


def _mock_refine_style(request: StyleAuthoringRequest) -> StyleAuthoringDraft:
    base = request.base_profile
    if base is None:
        raise ValueError("refine requires a base profile")
    instruction = request.instruction or ""
    color = base.color
    light = base.light
    texture = base.texture
    targets = dict(base.personal.targets)
    protected = set(base.personal.protected)
    avoid = set(base.personal.avoid)
    rationale: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    skin_adjusted = False

    if _contains(instruction, "更克制", "克制一点", "降低饱和", "淡一点", "less saturated"):
        _set_target(targets, "saturation", targets.get("saturation", 0.0) - 4)
        color = color.model_copy(update={"saturation": "更克制，饱和度降低"})
        rationale.append("已降低饱和度，使色彩表达更克制。")
    if _contains(instruction, "高光"):
        _set_target(targets, "highlights", targets.get("highlights", 0.0) - 4)
        protected.add(DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL)
        light = light.model_copy(update={"highlights": "保留更多高光细节"})
        rationale.append("已增加高光保护。")
    if _contains(instruction, "暗部") or _contains(instruction, "不要压黑"):
        _set_target(targets, "shadows", targets.get("shadows", 0.0) + 4)
        protected.add(DirectionConstraint.PRESERVE_SHADOW_DETAIL)
        light = light.model_copy(update={"shadows": "保留更多暗部层次"})
        rationale.append("已增加暗部层次保护。")
    if _contains(instruction, "肤色"):
        protected.add(DirectionConstraint.PRESERVE_SKIN_TONE)
        skin_adjusted = True
        if _contains(instruction, "冷", "偏冷"):
            _set_target(targets, "temperature", targets.get("temperature", 0.0) + 2)
            color = color.model_copy(update={"tendency": "保留自然肤色，避免偏冷"})
        else:
            color = color.model_copy(update={"tendency": "保留自然肤色"})
        rationale.append("已加入肤色保护。")
    if _contains(instruction, "背景") and _contains(instruction, "饱和"):
        _set_target(targets, "saturation", targets.get("saturation", 0.0) - 5)
        notes.append("无法区分背景与主体，背景饱和度调整已近似为全局调整。")
        rationale.append("已降低全局饱和度以近似背景色彩需求。")
    if _contains(instruction, "对比", "反差"):
        if _contains(instruction, "降低", "太强", "弱", "soft"):
            _set_target(targets, "contrast", targets.get("contrast", 0.0) - 5)
            light = light.model_copy(update={"contrast": "反差更柔和"})
        else:
            _set_target(targets, "contrast", targets.get("contrast", 0.0) + 5)
            light = light.model_copy(update={"contrast": "反差更明确"})
        rationale.append("已按指令调整整体反差。")
    if _contains(instruction, "颗粒"):
        if _contains(instruction, "少", "降低", "不要"):
            _set_target(targets, "grain", max(0.0, targets.get("grain", 0.0) - 4))
        else:
            _set_target(targets, "grain", targets.get("grain", 0.0) + 4)
        rationale.append("已调整颗粒倾向。")
    if not skin_adjusted and _contains(instruction, "暖"):
        _set_target(targets, "temperature", targets.get("temperature", 0.0) + 5)
        rationale.append("已增加暖色倾向。")
    elif not skin_adjusted and _contains(instruction, "冷"):
        _set_target(targets, "temperature", targets.get("temperature", 0.0) - 5)
        rationale.append("已增加冷色倾向。")
    if _contains(instruction, "更明显", "更强烈", "更风格化"):
        _set_target(targets, "saturation", targets.get("saturation", 0.0) + 3)
        _set_target(targets, "contrast", targets.get("contrast", 0.0) + 3)
        rationale.append("已增强风格表达。")
    if _contains(instruction, "自然", "原始质感"):
        protected.add(DirectionConstraint.NATURAL_LOOK)
        texture = texture.model_copy(update={"detail": "保留原始质感"})
        rationale.append("已加强自然质感保护。")

    if not rationale:
        warnings.append("未识别到明确的可执行修改，草稿保持当前风格。")
    return StyleAuthoringDraft(
        name=base.name,
        description=base.description,
        color=color,
        light=light,
        composition=base.composition,
        texture=texture,
        suitable_scenes=base.scene_fit.suitable,
        unsuitable_notes=base.scene_fit.unsuitable_notes,
        targets={key: value for key, value in targets.items() if abs(value) >= 0.5},
        protected=tuple(sorted(protected, key=lambda item: item.value))[:11],
        avoid=tuple(sorted(avoid, key=lambda item: item.value))[:8],
        summary=f"{base.description}；调整：{instruction}"[:500],
        rationale=tuple(rationale),
        warnings=tuple(warnings),
        limitations=(MOCK_AUTHORING_LIMITATION, *notes),
        confidence=0.65 if rationale else 0.4,
    )


_UNSUPPORTED_FEATURES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("删除", "移除", "去掉", "擦除"), "删除或擦除画面中的物体"),
    (("换背景", "替换背景", "生成背景", "重建背景"), "生成或替换背景"),
    (("扩图", "扩展画面", "补齐画面"), "扩展画面"),
    (("换天空", "替换天空", "天空替换"), "替换天空"),
    (("瘦脸", "液化", "重塑面部", "改变脸型"), "面部或身体重塑"),
    (("磨皮", "美颜", "去皱纹"), "皮肤重塑或美颜"),
)

_INTENT_LABELS: dict[str, str] = {
    "exposureEv": "曝光",
    "contrast": "对比度",
    "highlights": "高光",
    "shadows": "阴影",
    "whites": "白色色阶",
    "blacks": "黑色色阶",
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

_LOCAL_TARGETS = ("主体", "人物", "人脸", "局部", "单独处理")
_SKIN_TONE_DELTA_CAP = 6.0
_REGION_INTENT: dict[str, float] = {"exposureEv": 0.3, "shadows": 10.0, "clarity": 6.0}
_LOCAL_INTENT_FIELDS: frozenset[str] = frozenset(
    {
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
    }
)


def _unsupported_capability(instruction: str) -> str | None:
    for keywords, description in _UNSUPPORTED_FEATURES:
        if any(keyword in instruction for keyword in keywords):
            return description
    return None


def _targets_local_region(instruction: str) -> bool:
    return any(keyword in instruction for keyword in _LOCAL_TARGETS)


_CHANNEL_TARGETS = ("天空", "蓝色", "绿色", "红色", "肤色通道", "通道")


def _needs_channel_control(instruction: str) -> bool:
    return any(keyword in instruction for keyword in _CHANNEL_TARGETS)


def _protect_skin_tone(
    instruction: str,
    values: dict[str, float],
    notes: tuple[str, ...],
) -> tuple[dict[str, float], tuple[str, ...]]:
    if not any(keyword in instruction for keyword in ("肤色", "皮肤", "人像肤色")):
        return values, notes
    guarded = dict(values)
    changed = False
    for field in ("temperature", "tint", "saturation", "vibrance"):
        value = guarded.get(field)
        if value is not None and abs(value) > _SKIN_TONE_DELTA_CAP:
            guarded[field] = math.copysign(_SKIN_TONE_DELTA_CAP, value)
            changed = True
    if changed:
        notes = (*notes, "肤色保护：色彩相关参数的调整幅度已收紧。")
    return guarded, notes


def _region_patch(request: PatchRequest, instruction: str) -> PatchDraft:
    values, notes = _patch_values(instruction)
    if not values:
        values = dict(_REGION_INTENT)
    mask_id = next((mask.id for mask in request.recipe.masks), None)

    if mask_id is not None:
        local = {
            field: round(value + 0.0, 2)
            for field, value in values.items()
            if field in _LOCAL_INTENT_FIELDS
        }
        if not local:
            return PatchDraft(
                supported=True,
                adjustments=None,
                reason="该指令涉及的参数不支持局部调整，配方保持不变。",
                warnings=tuple(notes),
                limitations=(MOCK_PLANNER_LIMITATION, MOCK_PLANNER_BOUNDARY_LIMITATION),
                unsupported=(),
                confidence=0.3,
            )
        labels = "、".join(_INTENT_LABELS[field] for field in local)
        return PatchDraft(
            supported=True,
            adjustments=None,
            local_adjustments=(
                LocalAdjustmentIntent(
                    mask_id=mask_id,
                    adjustments=AdjustmentIntent(**local),
                ),
            ),
            reason=f"只在你已有的蒙版上调整{labels}，画面其余部分保持不变。",
            warnings=(
                "蒙版由你手动绘制，模拟规划器无法确认它覆盖的正是人物主体。",
                *notes,
            ),
            limitations=(MOCK_PLANNER_LIMITATION, MOCK_PLANNER_MASK_LOCAL_LIMITATION),
            confidence=0.55,
        )

    labels = "、".join(_INTENT_LABELS[field] for field in values)
    return PatchDraft(
        supported=True,
        adjustments=AdjustmentIntent(
            **{field: round(value + 0.0, 2) for field, value in values.items()}
        ),
        reason=f"没有可用蒙版，已改为全局调整{labels}。",
        warnings=("当前画面没有蒙版，背景会随主体一起变化；请先绘制蒙版再重试。", *notes),
        limitations=(MOCK_PLANNER_LIMITATION, MOCK_PLANNER_MASK_LIMITATION),
        confidence=0.45,
    )


def _patch_values(instruction: str) -> tuple[dict[str, float], tuple[str, ...]]:
    values: dict[str, float] = {}
    notes: list[str] = []

    if any(
        key in instruction
        for key in ("曝光", "亮度", "亮一点", "暗一点", "整体亮", "整体暗", "太亮", "太暗")
    ):
        if any(
            key in instruction
            for key in ("太亮", "过亮", "过曝", "压暗", "降低曝光", "减少曝光", "降低亮度")
        ):
            values["exposureEv"] = -0.3
        elif any(
            key in instruction
            for key in ("太暗", "偏暗", "欠曝", "提亮", "提高曝光", "增加曝光", "提高亮度")
        ):
            values["exposureEv"] = 0.3

    if any(key in instruction for key in ("电影感", "胶片感", "cinematic")):
        values["contrast"] = 12.0
        values["highlights"] = -10.0
        values["shadows"] = 8.0
        values["saturation"] = -6.0
        notes.append("对话调整只改全局参数，不会覆盖你的曲线与色彩分级。")

    if "对比" in instruction:
        if any(key in instruction for key in ("降低", "减少", "太强", "过强", "柔和")):
            values["contrast"] = -10.0
        else:
            values["contrast"] = 10.0

    if "自然饱和" in instruction or "鲜艳度" in instruction:
        if any(key in instruction for key in ("降低", "减少", "太艳", "过艳")):
            values["vibrance"] = -8.0
        else:
            values["vibrance"] = 8.0
    elif "饱和" in instruction:
        if any(key in instruction for key in ("降低", "减少", "太艳", "过饱和")):
            values["saturation"] = -8.0
        else:
            values["saturation"] = 8.0

    if any(key in instruction for key in ("色温", "暖", "冷", "偏黄", "偏蓝")):
        if any(
            key in instruction
            for key in ("偏黄", "太黄", "降暖", "冷一点", "更冷", "调冷", "偏暖", "太暖")
        ):
            values["temperature"] = -10.0
        elif any(
            key in instruction
            for key in ("暖一点", "更暖", "偏蓝", "太蓝", "偏冷", "太冷", "变暖", "加暖")
        ):
            values["temperature"] = 10.0

    if any(key in instruction for key in ("偏绿", "发绿")):
        values["tint"] = 10.0
    elif any(key in instruction for key in ("偏紫", "洋红", "偏品")):
        values["tint"] = -10.0

    if "高光" in instruction:
        if any(key in instruction for key in ("降低", "压低", "压暗", "恢复", "太亮", "过曝")):
            values["highlights"] = -15.0
        else:
            values["highlights"] = 10.0

    if any(key in instruction for key in ("阴影", "暗部")):
        if any(key in instruction for key in ("提亮", "提高", "增加", "太暗")):
            values["shadows"] = 15.0
        elif any(key in instruction for key in ("压暗", "降低", "减少")):
            values["shadows"] = -10.0

    if "白色" in instruction:
        values["whites"] = (
            -8.0 if any(key in instruction for key in ("降低", "压低", "减少")) else 8.0
        )
    if "黑位" in instruction or "黑色" in instruction:
        values["blacks"] = (
            -8.0 if any(key in instruction for key in ("降低", "压低", "减少")) else 8.0
        )

    if any(key in instruction for key in ("清晰", "通透", "层次")):
        values["clarity"] = 10.0
    elif any(key in instruction for key in ("柔和", "柔化", "雾")):
        values["clarity"] = -8.0

    if "噪" in instruction:
        values["denoise"] = 20.0
    if any(key in instruction for key in ("锐化", "更锐", "锐一点")):
        values["sharpen"] = 15.0

    if "暗角" in instruction:
        if any(key in instruction for key in ("去除", "减少", "取消", "去掉")):
            values["vignette"] = -12.0
        else:
            values["vignette"] = 12.0

    if "颗粒" in instruction:
        if any(key in instruction for key in ("去除", "减少", "取消")):
            notes.append("模拟规划器不能保证去除颗粒，未修改颗粒参数。")
        else:
            values["grain"] = 12.0

    return values, tuple(notes)


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
    "MOCK_PLANNER_LIMITATION",
    "MockDecisionProvider",
    "MockPlannerProvider",
    "MockVisionProvider",
]
