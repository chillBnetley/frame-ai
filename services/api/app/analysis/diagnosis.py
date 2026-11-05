from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.ai.contracts import (
    AnalysisOptions,
    CompositionBalance,
    EvidenceRef,
    IssueCandidate,
    IssueType,
    LightingDirection,
    MeasurementSummary,
    NegativeSpace,
    SceneLabel,
    Severity,
    SubjectRole,
    SubjectType,
    VisionResult,
)
from app.analysis.regions import RegionAssignment, bbox_to_pixels
from app.imaging.loader import LoadedImage
from app.imaging.tone import luma_srgb

DIAGNOSIS_VERSION = "diagnosis/2"

HIGHLIGHT_CLIP_PCT = 1.0
SHADOW_CLIP_PCT = 1.0
OVEREXPOSURE_P50 = 0.80
OVEREXPOSURE_HIGHLIGHTS_PCT = 5.0
OVEREXPOSURE_SEVERE_P50 = 0.90
UNDEREXPOSURE_P50 = 0.18
UNDEREXPOSURE_SHADOWS_PCT = 5.0
UNDEREXPOSURE_SEVERE_P50 = 0.08

SUBJECT_UNDEREXPOSURE_GAP = 0.08
SUBJECT_UNDEREXPOSURE_MEDIUM_GAP = 0.12
SUBJECT_UNDEREXPOSURE_HIGH_GAP = 0.20
BACKGROUND_BRIGHT_LUMINANCE = 0.70
BACKGROUND_OVEREXPOSURE_GAP = 0.15

CAST_TEMPERATURE_THRESHOLD = 8.0
CAST_TINT_THRESHOLD = 8.0
CAST_SEVERE_THRESHOLD = 15.0

HORIZON_TILT_THRESHOLD_DEG = 2.0
HORIZON_TILT_MEDIUM_DEG = 5.0

FOCUS_SHARPNESS_THRESHOLD = 0.08
FOCUS_SHARPNESS_LOW = 0.04
HIGH_TEXTURE_EDGE_DENSITY = 0.18
MOTION_BLUR_ANISOTROPY = 0.6
LOW_DETAIL_EDGE_DENSITY = 0.02

NOISE_THRESHOLD = 0.35
NOISE_HIGH_THRESHOLD = 0.55

HARSH_CONTRAST_STD = 0.30
HARSH_CONTRAST_RANGE = 0.85
HARSH_CONTRAST_SEVERE_STD = 0.38
FLAT_LIGHTING_STD = 0.06
FLAT_LIGHTING_RANGE = 0.15

SUBJECT_EDGE_MARGIN = 0.01
SUBJECT_PLACEMENT_MIN_AREA = 0.10
NEGATIVE_SPACE_SUBJECT_AREA = 0.35
COMPOSITION_CONFIDENCE_FLOOR = 0.50

HIGH_TEXTURE_LIMITATION = "画面纹理较强，清晰度诊断可能不可靠，未生成对焦问题。"
HORIZON_UNAVAILABLE_LIMITATION = "无法可靠检测地平线，未评估画面倾斜。"

_BACKLIGHT_DIRECTIONS = frozenset({LightingDirection.BACK, LightingDirection.SIDE_BACK})
_HORIZON_SCENES = frozenset({SceneLabel.LANDSCAPE, SceneLabel.ARCHITECTURE, SceneLabel.STREET})


@dataclass(frozen=True, slots=True)
class RegionSample:
    region_id: str
    role: SubjectRole
    type: SubjectType
    luminance: float


@dataclass(frozen=True, slots=True)
class RegionSamples:
    samples: tuple[RegionSample, ...] = ()
    background_luminance: float | None = None


@dataclass(frozen=True, slots=True)
class DiagnosisContext:
    vision: VisionResult
    measurements: MeasurementSummary
    options: AnalysisOptions
    assignment: RegionAssignment
    region_samples: RegionSamples


@dataclass(frozen=True, slots=True)
class CandidateSet:
    candidates: tuple[IssueCandidate, ...] = ()
    limitations: tuple[str, ...] = field(default=())


def sample_regions(image: LoadedImage, assignment: RegionAssignment) -> RegionSamples:
    luminance = luma_srgb(np.clip(image.rgb, 0.0, 1.0))
    height, width = luminance.shape
    roles = {subject.region_id: subject.role for subject in assignment.subjects}

    samples: list[RegionSample] = []
    for region in assignment.regions:
        role = roles.get(region.id)
        if role is None:
            continue
        x, y, box_width, box_height = bbox_to_pixels(region.bbox, width, height)
        tile = luminance[y : y + box_height, x : x + box_width]
        if tile.size == 0:
            continue
        samples.append(
            RegionSample(
                region_id=region.id,
                role=role,
                type=region.type,
                luminance=round(float(tile.mean()), 3),
            )
        )

    return RegionSamples(
        samples=tuple(samples),
        background_luminance=_background_luminance(luminance, assignment),
    )


def _background_luminance(
    luminance: np.ndarray,
    assignment: RegionAssignment,
) -> float | None:
    primary = next(
        (subject for subject in assignment.subjects if subject.role is SubjectRole.PRIMARY),
        None,
    )
    if primary is None:
        return None
    height, width = luminance.shape
    x, y, box_width, box_height = bbox_to_pixels(primary.bbox, width, height)
    mask = np.ones((height, width), dtype=bool)
    mask[y : y + box_height, x : x + box_width] = False
    if not mask.any():
        return None
    return round(float(luminance[mask].mean()), 3)


def build_candidates(context: DiagnosisContext) -> CandidateSet:
    if not context.options.quality_diagnosis:
        return CandidateSet()

    measurements = context.measurements
    vision = context.vision
    limitations: list[str] = []
    candidates: list[IssueCandidate] = []

    _exposure_candidates(candidates, measurements)
    if context.options.color_analysis:
        _color_candidates(candidates, measurements)
    _detail_candidates(candidates, measurements, limitations)
    if context.options.subject_detection:
        _subject_candidates(candidates, vision, context.region_samples)
    if context.options.composition_analysis:
        _composition_candidates(
            candidates,
            vision,
            context.assignment,
            context.region_samples,
            measurements,
            limitations,
        )
    if context.options.lighting_analysis:
        _lighting_candidates(candidates, measurements)

    return CandidateSet(tuple(_sorted_candidates(candidates)), tuple(limitations))


def _exposure_candidates(
    candidates: list[IssueCandidate],
    measurements: MeasurementSummary,
) -> None:
    if measurements.highlights_pct >= HIGHLIGHT_CLIP_PCT:
        severity = _severity_from(
            measurements.highlights_pct,
            medium=5.0,
            high=15.0,
        )
        candidates.append(
            IssueCandidate(
                id="c_highlight_clipping",
                type=IssueType.HIGHLIGHT_CLIPPING,
                severity=severity,
                confidence=_confidence(
                    HIGHLIGHT_CLIP_PCT,
                    measurements.highlights_pct,
                    span=12.0,
                ),
                evidence=(
                    f"高光裁切比例为 {measurements.highlights_pct:.1f}%，"
                    f"超过 {HIGHLIGHT_CLIP_PCT:.1f}% 阈值，亮部细节可能已丢失。"
                ),
                evidence_refs=(_measurement_ref("highlightsPct", measurements.highlights_pct),),
            )
        )

    if measurements.shadows_pct >= SHADOW_CLIP_PCT:
        severity = _severity_from(
            measurements.shadows_pct,
            medium=5.0,
            high=15.0,
        )
        candidates.append(
            IssueCandidate(
                id="c_shadow_clipping",
                type=IssueType.SHADOW_CLIPPING,
                severity=severity,
                confidence=_confidence(
                    SHADOW_CLIP_PCT,
                    measurements.shadows_pct,
                    span=12.0,
                ),
                evidence=(
                    f"暗部裁切比例为 {measurements.shadows_pct:.1f}%，"
                    f"超过 {SHADOW_CLIP_PCT:.1f}% 阈值，阴影细节可能不足。"
                ),
                evidence_refs=(_measurement_ref("shadowsPct", measurements.shadows_pct),),
            )
        )

    if (
        measurements.luminance_p50 >= OVEREXPOSURE_P50
        and measurements.highlights_pct >= OVEREXPOSURE_HIGHLIGHTS_PCT
    ):
        severity = (
            Severity.HIGH
            if measurements.luminance_p50 >= OVEREXPOSURE_SEVERE_P50
            else Severity.MEDIUM
        )
        candidates.append(
            IssueCandidate(
                id="c_overexposure",
                type=IssueType.OVEREXPOSURE,
                severity=severity,
                confidence=_confidence(
                    OVEREXPOSURE_P50,
                    measurements.luminance_p50,
                    span=0.12,
                    base=0.6,
                ),
                evidence=(
                    f"中位亮度 {measurements.luminance_p50:.2f} 且高光裁切 "
                    f"{measurements.highlights_pct:.1f}%，整体曝光偏高。"
                ),
                evidence_refs=(
                    _measurement_ref("luminanceP50", measurements.luminance_p50),
                    _measurement_ref("highlightsPct", measurements.highlights_pct),
                ),
            )
        )

    if (
        measurements.luminance_p50 <= UNDEREXPOSURE_P50
        and measurements.shadows_pct >= UNDEREXPOSURE_SHADOWS_PCT
    ):
        severity = (
            Severity.HIGH
            if measurements.luminance_p50 <= UNDEREXPOSURE_SEVERE_P50
            else Severity.MEDIUM
        )
        candidates.append(
            IssueCandidate(
                id="c_underexposure",
                type=IssueType.UNDEREXPOSURE,
                severity=severity,
                confidence=_inverse_confidence(
                    UNDEREXPOSURE_P50,
                    measurements.luminance_p50,
                    span=0.14,
                    base=0.6,
                ),
                evidence=(
                    f"中位亮度 {measurements.luminance_p50:.2f} 且暗部裁切 "
                    f"{measurements.shadows_pct:.1f}%，整体曝光偏低。"
                ),
                evidence_refs=(
                    _measurement_ref("luminanceP50", measurements.luminance_p50),
                    _measurement_ref("shadowsPct", measurements.shadows_pct),
                ),
            )
        )


def _color_candidates(
    candidates: list[IssueCandidate],
    measurements: MeasurementSummary,
) -> None:
    temperature = measurements.cast_temperature
    tint = measurements.cast_tint
    magnitude = max(abs(temperature), abs(tint))
    if magnitude < CAST_TEMPERATURE_THRESHOLD and magnitude < CAST_TINT_THRESHOLD:
        return

    parts: list[str] = []
    if abs(temperature) >= CAST_TEMPERATURE_THRESHOLD:
        direction = "偏暖" if temperature > 0 else "偏冷"
        parts.append(f"色温偏差 {temperature:+.1f}（{direction}）")
    if abs(tint) >= CAST_TINT_THRESHOLD:
        direction = "偏洋红" if tint > 0 else "偏绿"
        parts.append(f"绿色-洋红偏差 {tint:+.1f}（{direction}）")

    candidates.append(
        IssueCandidate(
            id="c_color_cast",
            type=IssueType.COLOR_CAST,
            severity=(Severity.MEDIUM if magnitude >= CAST_SEVERE_THRESHOLD else Severity.LOW),
            confidence=_confidence(
                CAST_TEMPERATURE_THRESHOLD,
                magnitude,
                span=12.0,
                base=0.5,
                cap=0.85,
            ),
            evidence="画面存在色彩偏移：" + "，".join(parts) + "。",
            evidence_refs=(
                _measurement_ref("castTemperature", temperature),
                _measurement_ref("castTint", tint),
            ),
        )
    )


def _detail_candidates(
    candidates: list[IssueCandidate],
    measurements: MeasurementSummary,
    limitations: list[str],
) -> None:
    texture = max(measurements.edge_density_grid_3x3, default=0.0)
    if measurements.sharpness < FOCUS_SHARPNESS_THRESHOLD:
        if texture >= HIGH_TEXTURE_EDGE_DENSITY:
            limitations.append(HIGH_TEXTURE_LIMITATION)
        else:
            severity = (
                Severity.MEDIUM if measurements.sharpness < FOCUS_SHARPNESS_LOW else Severity.LOW
            )
            if measurements.gradient_anisotropy >= MOTION_BLUR_ANISOTROPY:
                candidates.append(
                    IssueCandidate(
                        id="c_motion_blur",
                        type=IssueType.MOTION_BLUR,
                        severity=severity,
                        confidence=_inverse_confidence(
                            FOCUS_SHARPNESS_THRESHOLD,
                            measurements.sharpness,
                            span=0.06,
                            base=0.55,
                            cap=0.85,
                        ),
                        evidence=(
                            f"清晰度指标 {measurements.sharpness:.3f} 偏低，"
                            f"梯度方向性 {measurements.gradient_anisotropy:.2f} 偏强，"
                            "画面可能存在运动模糊。"
                        ),
                        evidence_refs=(
                            _measurement_ref("sharpness", measurements.sharpness),
                            _measurement_ref(
                                "gradientAnisotropy",
                                measurements.gradient_anisotropy,
                            ),
                        ),
                    )
                )
            elif texture <= LOW_DETAIL_EDGE_DENSITY:
                candidates.append(
                    IssueCandidate(
                        id="c_low_detail",
                        type=IssueType.LOW_DETAIL,
                        severity=severity,
                        confidence=_inverse_confidence(
                            FOCUS_SHARPNESS_THRESHOLD,
                            measurements.sharpness,
                            span=0.06,
                            base=0.5,
                            cap=0.8,
                        ),
                        evidence=(
                            f"清晰度指标 {measurements.sharpness:.3f} 偏低，"
                            f"边缘密度 {texture:.3f} 很低，画面细节不足。"
                        ),
                        evidence_refs=(
                            _measurement_ref("sharpness", measurements.sharpness),
                            _measurement_ref("edgeDensityMax", texture),
                        ),
                    )
                )
            else:
                candidates.append(
                    IssueCandidate(
                        id="c_focus_issue",
                        type=IssueType.FOCUS_ISSUE,
                        severity=severity,
                        confidence=_inverse_confidence(
                            FOCUS_SHARPNESS_THRESHOLD,
                            measurements.sharpness,
                            span=0.06,
                            base=0.55,
                            cap=0.85,
                        ),
                        evidence=(
                            f"清晰度指标 {measurements.sharpness:.3f}，低于 "
                            f"{FOCUS_SHARPNESS_THRESHOLD:.3f} 阈值，画面可能未准确对焦。"
                        ),
                        evidence_refs=(
                            _measurement_ref("sharpness", measurements.sharpness),
                            _measurement_ref("edgeDensityMax", texture),
                        ),
                    )
                )

    if measurements.noise_estimate >= NOISE_THRESHOLD:
        severity = (
            Severity.HIGH
            if measurements.noise_estimate >= NOISE_HIGH_THRESHOLD
            else Severity.MEDIUM
        )
        candidates.append(
            IssueCandidate(
                id="c_high_noise",
                type=IssueType.HIGH_NOISE,
                severity=severity,
                confidence=_confidence(
                    NOISE_THRESHOLD,
                    measurements.noise_estimate,
                    span=0.3,
                ),
                evidence=(
                    f"噪声估计 {measurements.noise_estimate:.2f}，超过 "
                    f"{NOISE_THRESHOLD:.2f} 阈值，暗部可能出现明显噪点。"
                ),
                evidence_refs=(_measurement_ref("noiseEstimate", measurements.noise_estimate),),
            )
        )


def _subject_candidates(
    candidates: list[IssueCandidate],
    vision: VisionResult,
    samples: RegionSamples,
) -> None:
    primary = _primary_sample(samples)
    if primary is None or samples.background_luminance is None:
        return
    gap = samples.background_luminance - primary.luminance

    if vision.lighting.direction in _BACKLIGHT_DIRECTIONS and gap >= SUBJECT_UNDEREXPOSURE_GAP:
        severity = _severity_from(
            gap,
            medium=SUBJECT_UNDEREXPOSURE_MEDIUM_GAP,
            high=SUBJECT_UNDEREXPOSURE_HIGH_GAP,
        )
        candidates.append(
            IssueCandidate(
                id=f"c_subject_underexposure_{primary.region_id}",
                type=IssueType.SUBJECT_UNDEREXPOSURE,
                severity=severity,
                confidence=_confidence(
                    SUBJECT_UNDEREXPOSURE_GAP,
                    gap,
                    span=0.16,
                    base=0.6,
                    cap=0.92,
                ),
                evidence=(
                    f"逆光或侧逆光（{vision.lighting.direction.value}）条件下，"
                    f"主体区域平均亮度 {primary.luminance:.2f}，背景 "
                    f"{samples.background_luminance:.2f}，相差 {gap:.2f}。"
                ),
                region_ids=(primary.region_id,),
                evidence_refs=(
                    _vision_ref("lighting.direction", vision.lighting.direction.value),
                    _measurement_ref(
                        f"regionLuminance.{primary.region_id}",
                        primary.luminance,
                    ),
                    _measurement_ref(
                        "backgroundLuminance",
                        samples.background_luminance,
                    ),
                ),
            )
        )

    if (
        vision.lighting.direction not in _BACKLIGHT_DIRECTIONS
        and samples.background_luminance >= BACKGROUND_BRIGHT_LUMINANCE
        and gap >= BACKGROUND_OVEREXPOSURE_GAP
    ):
        candidates.append(
            IssueCandidate(
                id="c_background_overexposure",
                type=IssueType.BACKGROUND_OVEREXPOSURE,
                severity=(Severity.MEDIUM if gap >= 0.25 else Severity.LOW),
                confidence=_confidence(
                    BACKGROUND_OVEREXPOSURE_GAP,
                    gap,
                    span=0.2,
                    base=0.5,
                    cap=0.85,
                ),
                evidence=(
                    f"主体区域平均亮度 {primary.luminance:.2f}，背景平均亮度 "
                    f"{samples.background_luminance:.2f}，背景明显过亮。"
                ),
                region_ids=(primary.region_id,),
                evidence_refs=(
                    _measurement_ref(
                        "backgroundLuminance",
                        samples.background_luminance,
                    ),
                    _measurement_ref(
                        f"regionLuminance.{primary.region_id}",
                        primary.luminance,
                    ),
                ),
            )
        )


def _composition_candidates(
    candidates: list[IssueCandidate],
    vision: VisionResult,
    assignment: RegionAssignment,
    samples: RegionSamples,
    measurements: MeasurementSummary,
    limitations: list[str],
) -> None:
    primary = _primary_sample(samples)
    composition = vision.composition

    if (
        composition.balance is CompositionBalance.UNBALANCED
        and composition.confidence >= COMPOSITION_CONFIDENCE_FLOOR
    ):
        candidates.append(
            IssueCandidate(
                id="c_balance_issue",
                type=IssueType.BALANCE_ISSUE,
                severity=Severity.LOW,
                confidence=composition.confidence,
                evidence="画面平衡被判断为 unbalanced，视觉重心偏向一侧。",
                evidence_refs=(_vision_ref("composition.balance", composition.balance.value),),
            )
        )

    tilt = measurements.horizon_tilt_deg
    if tilt is not None and abs(tilt) >= HORIZON_TILT_THRESHOLD_DEG:
        magnitude = abs(tilt)
        candidates.append(
            IssueCandidate(
                id="c_horizon_tilt",
                type=IssueType.HORIZON_TILT,
                severity=(
                    Severity.MEDIUM if magnitude >= HORIZON_TILT_MEDIUM_DEG else Severity.LOW
                ),
                confidence=_confidence(
                    HORIZON_TILT_THRESHOLD_DEG,
                    magnitude,
                    span=8.0,
                    base=0.55,
                    cap=0.9,
                ),
                evidence=(
                    f"画面地平线倾斜 {magnitude:.1f}°，超过 "
                    f"{HORIZON_TILT_THRESHOLD_DEG:.1f}° 阈值。"
                ),
                evidence_refs=(_measurement_ref("horizonTiltDeg", tilt),),
            )
        )

    if vision.scene.primary in _HORIZON_SCENES and tilt is None:
        limitations.append(HORIZON_UNAVAILABLE_LIMITATION)

    if primary is None:
        return

    region_area = _region_area(assignment, primary.region_id)
    if (
        composition.negative_space is NegativeSpace.LOW
        and region_area is not None
        and region_area >= NEGATIVE_SPACE_SUBJECT_AREA
        and composition.confidence >= COMPOSITION_CONFIDENCE_FLOOR
    ):
        candidates.append(
            IssueCandidate(
                id="c_negative_space_issue",
                type=IssueType.NEGATIVE_SPACE_ISSUE,
                severity=Severity.LOW,
                confidence=composition.confidence,
                evidence=(f"主要主体占比 {region_area:.2f}，负空间为 low，画面较为拥挤。"),
                region_ids=(primary.region_id,),
                evidence_refs=(
                    _vision_ref(
                        "composition.negativeSpace",
                        composition.negative_space.value,
                    ),
                    _measurement_ref("primarySubjectArea", region_area),
                ),
            )
        )

    edges = _touching_edges(assignment, primary.region_id)
    if edges and region_area is not None and region_area >= SUBJECT_PLACEMENT_MIN_AREA:
        edge_text = "、".join(edges)
        candidates.append(
            IssueCandidate(
                id=f"c_subject_placement_{primary.region_id}",
                type=IssueType.SUBJECT_PLACEMENT,
                severity=Severity.LOW,
                confidence=min(0.65, max(0.45, composition.confidence)),
                evidence=(f"主要主体紧贴画面{edge_text}边缘，取景裁切可能不完整。"),
                region_ids=(primary.region_id,),
                evidence_refs=(
                    _vision_ref(
                        "composition.subjectPosition",
                        composition.subject_position.value,
                    ),
                    _measurement_ref("primarySubjectArea", region_area),
                ),
            )
        )


def _lighting_candidates(
    candidates: list[IssueCandidate],
    measurements: MeasurementSummary,
) -> None:
    spread = measurements.luminance_p99 - measurements.luminance_p1
    if measurements.luminance_std >= HARSH_CONTRAST_STD and spread >= HARSH_CONTRAST_RANGE:
        candidates.append(
            IssueCandidate(
                id="c_harsh_contrast",
                type=IssueType.HARSH_CONTRAST,
                severity=(
                    Severity.MEDIUM
                    if measurements.luminance_std >= HARSH_CONTRAST_SEVERE_STD
                    else Severity.LOW
                ),
                confidence=_confidence(
                    HARSH_CONTRAST_STD,
                    measurements.luminance_std,
                    span=0.15,
                    base=0.5,
                ),
                evidence=(
                    f"亮度标准差 {measurements.luminance_std:.2f}，明暗跨度 "
                    f"{spread:.2f}，画面反差偏大。"
                ),
                evidence_refs=(
                    _measurement_ref("luminanceStd", measurements.luminance_std),
                    _measurement_ref("luminanceSpread", spread),
                ),
            )
        )

    if measurements.luminance_std <= FLAT_LIGHTING_STD and spread <= FLAT_LIGHTING_RANGE:
        candidates.append(
            IssueCandidate(
                id="c_flat_lighting",
                type=IssueType.FLAT_LIGHTING,
                severity=Severity.LOW,
                confidence=_inverse_confidence(
                    FLAT_LIGHTING_STD,
                    measurements.luminance_std,
                    span=0.06,
                    base=0.45,
                    cap=0.75,
                ),
                evidence=(
                    f"亮度标准差 {measurements.luminance_std:.2f}，明暗跨度 "
                    f"{spread:.2f}，光线较为平淡。"
                ),
                evidence_refs=(
                    _measurement_ref("luminanceStd", measurements.luminance_std),
                    _measurement_ref("luminanceSpread", spread),
                ),
            )
        )


def _primary_sample(samples: RegionSamples) -> RegionSample | None:
    return next(
        (sample for sample in samples.samples if sample.role is SubjectRole.PRIMARY),
        None,
    )


def _region_area(assignment: RegionAssignment, region_id: str) -> float | None:
    for region in assignment.regions:
        if region.id == region_id:
            return region.bbox.width * region.bbox.height
    return None


def _touching_edges(
    assignment: RegionAssignment,
    region_id: str,
) -> tuple[str, ...]:
    region = next(
        (candidate for candidate in assignment.regions if candidate.id == region_id),
        None,
    )
    if region is None:
        return ()
    bbox = region.bbox
    edges: list[str] = []
    if bbox.x <= SUBJECT_EDGE_MARGIN:
        edges.append("左侧")
    if bbox.y <= SUBJECT_EDGE_MARGIN:
        edges.append("顶部")
    if bbox.x + bbox.width >= 1.0 - SUBJECT_EDGE_MARGIN:
        edges.append("右侧")
    if bbox.y + bbox.height >= 1.0 - SUBJECT_EDGE_MARGIN:
        edges.append("底部")
    return tuple(edges)


def _measurement_ref(key: str, value: float) -> EvidenceRef:
    return EvidenceRef(source="measurement", key=key, value=f"{value:.3f}")


def _vision_ref(key: str, value: str) -> EvidenceRef:
    return EvidenceRef(source="vision", key=key, value=value)


def _severity_from(value: float, *, medium: float, high: float) -> Severity:
    if value >= high:
        return Severity.HIGH
    if value >= medium:
        return Severity.MEDIUM
    return Severity.LOW


def _confidence(
    threshold: float,
    value: float,
    *,
    span: float,
    base: float = 0.55,
    cap: float = 0.9,
) -> float:
    ratio = 0.0 if span <= 0.0 else min(max((value - threshold) / span, 0.0), 1.0)
    return round(min(max(base + (cap - base) * ratio, 0.0), 1.0), 3)


def _inverse_confidence(
    threshold: float,
    value: float,
    *,
    span: float,
    base: float = 0.55,
    cap: float = 0.9,
) -> float:
    ratio = 0.0 if span <= 0.0 else min(max((threshold - value) / span, 0.0), 1.0)
    return round(min(max(base + (cap - base) * ratio, 0.0), 1.0), 3)


_SEVERITY_RANK = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


def _sorted_candidates(candidates: list[IssueCandidate]) -> list[IssueCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            _SEVERITY_RANK[candidate.severity],
            -candidate.confidence,
            candidate.type.value,
            candidate.id,
        ),
    )


__all__ = [
    "CandidateSet",
    "DIAGNOSIS_VERSION",
    "DiagnosisContext",
    "RegionSample",
    "RegionSamples",
    "build_candidates",
    "sample_regions",
]
