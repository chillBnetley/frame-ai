"""Deterministic Visual DNA extraction from a completed stage 3 report.

Only measured image facts and the report's grounded semantic fields are used.
No second vision call is made here: colour/tone/texture statistics come from
the stage 3 measurements, while scene, light, colour harmony and composition
reuse the report's validated model output.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai.contracts import ContrastLevel, LightingDirection, SceneLabel
from app.models.analysis_report import AnalysisReport
from app.models.visual_dna import (
    FeatureCategory,
    FeatureOrigin,
    FeatureSeverity,
    PhotoColorFeatures,
    PhotoCompositionFeatures,
    PhotoFeatureAnomaly,
    PhotoFeatureReading,
    PhotoLightFeatures,
    PhotoSceneFeatures,
    PhotoTextureFeatures,
    PhotoToneFeatures,
    PhotoVisualFeatures,
)

EXTRACTOR_VERSION = "visual-dna/1"

LOW_CONFIDENCE = 0.5
HIGH_CLIP_PCT = 10.0
LOW_SHARPNESS = 0.08
HIGH_NOISE = 0.35
MONOCHROME_SATURATION = 0.03
HIGH_KEY_P50 = 0.70
LOW_KEY_P95 = 0.60
LOW_LIGHT_P50 = 0.20
CONTRAST_FULL_SCALE = 0.35

_DIRECTIONAL = {
    LightingDirection.SIDE,
    LightingDirection.BACK,
    LightingDirection.SIDE_BACK,
}
_SOFT_DIRECTIONS = {LightingDirection.DIFFUSE, LightingDirection.OVERCAST}


def _clamp01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _signed(value: float) -> float:
    return min(max(float(value), -1.0), 1.0)


def _softness(direction: LightingDirection, contrast: ContrastLevel) -> float:
    if direction in _SOFT_DIRECTIONS:
        base = 0.85
    elif direction in _DIRECTIONAL:
        base = 0.30
    elif direction is LightingDirection.ARTIFICIAL:
        base = 0.55
    else:
        base = 0.50
    if contrast is ContrastLevel.LOW:
        base = max(base, 0.75)
    elif contrast is ContrastLevel.HIGH:
        base = min(base, 0.30)
    return _clamp01(base)


def _temperature_direction(offset: float) -> str:
    if offset > 0:
        return "偏暖"
    if offset < 0:
        return "偏冷"
    return "中性"


def _saturation_intent(mean: float) -> tuple[str, str]:
    if mean <= 0.22:
        return "restrained", "饱和度整体偏低，色彩表达倾向于克制。"
    if mean <= 0.45:
        return "balanced", "饱和度处于中等范围，色彩表达自然。"
    return "vivid", "饱和度整体偏高，色彩表达较鲜明。"


def _contrast_intent(strength: float) -> tuple[str, str]:
    if strength <= 0.45:
        return "soft", "明暗反差较柔和，影调过渡平缓。"
    if strength <= 0.75:
        return "moderate", "明暗反差中等，影调层次清晰。"
    return "strong", "明暗反差强烈，光影层次突出。"


def _texture_intent(sharpness: float, noise: float) -> tuple[str, str]:
    if noise >= HIGH_NOISE:
        return "grainy", "噪声估计偏高，画面呈现出颗粒感。"
    if sharpness >= 0.55:
        return "crisp", "清晰度较高，细节表现锐利。"
    if sharpness <= LOW_SHARPNESS:
        return "soft_detail", "清晰度偏低，画面更柔和、细节较少。"
    return "natural", "清晰度与噪声处于自然范围，质感克制。"


def _reading(
    *,
    category: FeatureCategory,
    key: str,
    label: str,
    value: float | str | bool,
    description: str,
    evidence: tuple[str, ...],
    confidence: float,
    origin: FeatureOrigin,
    editable: bool,
    normalized: float | None = None,
) -> PhotoFeatureReading:
    return PhotoFeatureReading(
        category=category,
        key=key,
        label=label,
        value=value,
        normalized=normalized,
        description=description,
        evidence=evidence,
        confidence=confidence,
        origin=origin,
        editable=editable,
    )


def _anomalies(
    report: AnalysisReport,
    *,
    contrast_strength: float,
) -> tuple[PhotoFeatureAnomaly, ...]:
    measurements = report.measurements
    anomalies: list[PhotoFeatureAnomaly] = []

    def add(
        code: str,
        category: FeatureCategory,
        message: str,
        evidence: tuple[str, ...],
        severity: FeatureSeverity = FeatureSeverity.WARNING,
    ) -> None:
        anomalies.append(
            PhotoFeatureAnomaly(
                code=code,
                category=category,
                severity=severity,
                message=message,
                evidence=evidence,
            )
        )

    if report.scene.primary is SceneLabel.OTHER:
        add(
            "scene_unknown",
            FeatureCategory.SCENE,
            "未能识别明确场景，场景相关特征需要人工确认。",
            ("scene.primary",),
            FeatureSeverity.INFO,
        )
    if report.scene.confidence < LOW_CONFIDENCE:
        add(
            "low_scene_confidence",
            FeatureCategory.SCENE,
            "场景判断置信度较低，不宜据此形成强结论。",
            ("scene.confidence",),
        )
    if report.lighting.confidence < LOW_CONFIDENCE:
        add(
            "low_light_confidence",
            FeatureCategory.LIGHT,
            "光线判断置信度较低，光线偏好需要更多参考照片验证。",
            ("lighting.confidence",),
        )
    if report.color.confidence < LOW_CONFIDENCE:
        add(
            "low_color_confidence",
            FeatureCategory.COLOR,
            "色彩判断置信度较低，色彩偏好需要更多参考照片验证。",
            ("color.confidence",),
        )
    if measurements.clipping.highlights_pct > HIGH_CLIP_PCT:
        add(
            "highlights_clipped",
            FeatureCategory.TONE,
            f"高光裁切约 {measurements.clipping.highlights_pct:.1f}%，可能影响高光层次判断。",
            ("measurement.clipping.highlightsPct",),
        )
    if measurements.clipping.shadows_pct > HIGH_CLIP_PCT:
        add(
            "shadows_clipped",
            FeatureCategory.TONE,
            f"暗部裁切约 {measurements.clipping.shadows_pct:.1f}%，暗部细节可能不足。",
            ("measurement.clipping.shadowsPct",),
        )
    if measurements.detail.sharpness < LOW_SHARPNESS:
        add(
            "low_sharpness",
            FeatureCategory.TEXTURE,
            "清晰度偏低，质感倾向可能受对焦或运动模糊影响。",
            ("measurement.detail.sharpness",),
        )
    if measurements.detail.noise_estimate >= HIGH_NOISE:
        add(
            "high_noise",
            FeatureCategory.TEXTURE,
            "噪声估计偏高，颗粒倾向可能来自设备或高感光度。",
            ("measurement.detail.noiseEstimate",),
        )
    if contrast_strength >= 0.95:
        add(
            "extreme_contrast",
            FeatureCategory.TONE,
            "明暗反差极高，需注意高光与暗部细节是否被压缩。",
            ("measurement.luminance.std",),
            FeatureSeverity.INFO,
        )
    return tuple(anomalies)


def extract_photo_features(report: AnalysisReport) -> PhotoVisualFeatures:
    measurements = report.measurements
    luminance = measurements.luminance
    color_measurement = measurements.color
    detail = measurements.detail
    clipping = measurements.clipping

    temperature_offset = _signed(color_measurement.cast.temperature / 100.0)
    tint_offset = _signed(color_measurement.cast.tint / 100.0)
    contrast_strength = _clamp01(luminance.std / CONTRAST_FULL_SCALE)
    high_key = luminance.p50 >= HIGH_KEY_P50
    low_key = luminance.p95 <= LOW_KEY_P95
    low_light = luminance.p50 <= LOW_LIGHT_P50
    monochrome = color_measurement.saturation_mean < MONOCHROME_SATURATION
    softness = _softness(report.lighting.direction, report.lighting.contrast)

    saturation_intent, saturation_description = _saturation_intent(
        color_measurement.saturation_mean
    )
    contrast_intent, contrast_description = _contrast_intent(contrast_strength)
    texture_intent, texture_description = _texture_intent(
        detail.sharpness,
        detail.noise_estimate,
    )

    readings: list[PhotoFeatureReading] = [
        _reading(
            category=FeatureCategory.COLOR,
            key="castTemperature",
            label="色温偏色",
            value=color_measurement.cast.temperature,
            normalized=temperature_offset,
            description=(
                f"色温偏色 {color_measurement.cast.temperature:+.1f}"
                f"（{_temperature_direction(temperature_offset)}）。"
            ),
            evidence=("measurement.color.cast.temperature",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.COLOR,
            key="castTint",
            label="色调偏色",
            value=color_measurement.cast.tint,
            normalized=tint_offset,
            description=f"绿色-洋红偏色 {color_measurement.cast.tint:+.1f}。",
            evidence=("measurement.color.cast.tint",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.COLOR,
            key="saturationMean",
            label="平均饱和度",
            value=color_measurement.saturation_mean,
            normalized=color_measurement.saturation_mean,
            description=f"平均饱和度 {color_measurement.saturation_mean:.2f}。",
            evidence=("measurement.color.saturationMean",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.COLOR,
            key="saturationIntent",
            label="色彩浓度倾向",
            value=saturation_intent,
            normalized=color_measurement.saturation_mean,
            description=saturation_description,
            evidence=("measurement.color.saturationMean",),
            confidence=1.0,
            origin=FeatureOrigin.DERIVED,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.COLOR,
            key="harmony",
            label="色彩关系",
            value=report.color.harmony.value,
            description=f"视觉模型判断色彩关系为 {report.color.harmony.value}。",
            evidence=("color.harmony",),
            confidence=report.color.confidence,
            origin=FeatureOrigin.MODEL,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.TONE,
            key="luminanceStd",
            label="明暗标准差",
            value=luminance.std,
            normalized=contrast_strength,
            description=f"亮度标准差 {luminance.std:.2f}，用于衡量整体反差。",
            evidence=("measurement.luminance.std",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.TONE,
            key="highlightsPct",
            label="高光裁切",
            value=clipping.highlights_pct,
            description=f"高光裁切约 {clipping.highlights_pct:.1f}%。",
            evidence=("measurement.clipping.highlightsPct",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.TONE,
            key="shadowsPct",
            label="暗部裁切",
            value=clipping.shadows_pct,
            description=f"暗部裁切约 {clipping.shadows_pct:.1f}%。",
            evidence=("measurement.clipping.shadowsPct",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.TONE,
            key="contrastIntent",
            label="影调反差倾向",
            value=contrast_intent,
            normalized=contrast_strength,
            description=contrast_description,
            evidence=("measurement.luminance.std",),
            confidence=1.0,
            origin=FeatureOrigin.DERIVED,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.LIGHT,
            key="direction",
            label="光线方向",
            value=report.lighting.direction.value,
            description=f"视觉模型判断光线方向为 {report.lighting.direction.value}。",
            evidence=("lighting.direction",),
            confidence=report.lighting.confidence,
            origin=FeatureOrigin.MODEL,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.LIGHT,
            key="softness",
            label="光线柔和程度",
            value=round(softness, 3),
            normalized=softness,
            description=(
                "光线偏柔和漫射。"
                if softness >= 0.65
                else "光线方向性较强，明暗关系更明确。"
                if softness <= 0.45
                else "光线柔和程度中等。"
            ),
            evidence=("lighting.direction", "lighting.contrast", "measurement.luminance.std"),
            confidence=report.lighting.confidence,
            origin=FeatureOrigin.DERIVED,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.TEXTURE,
            key="sharpness",
            label="清晰度",
            value=detail.sharpness,
            normalized=detail.sharpness,
            description=f"清晰度指标 {detail.sharpness:.2f}。",
            evidence=("measurement.detail.sharpness",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.TEXTURE,
            key="noise",
            label="噪声估计",
            value=detail.noise_estimate,
            normalized=detail.noise_estimate,
            description=f"噪声估计 {detail.noise_estimate:.2f}。",
            evidence=("measurement.detail.noiseEstimate",),
            confidence=1.0,
            origin=FeatureOrigin.MEASUREMENT,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.TEXTURE,
            key="intent",
            label="质感倾向",
            value=texture_intent,
            normalized=max(detail.sharpness, detail.noise_estimate),
            description=texture_description,
            evidence=("measurement.detail.sharpness", "measurement.detail.noiseEstimate"),
            confidence=1.0,
            origin=FeatureOrigin.DERIVED,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.SCENE,
            key="primary",
            label="主要场景",
            value=report.scene.primary.value,
            description=f"视觉模型判断主要场景为 {report.scene.primary.value}。",
            evidence=("scene.primary",),
            confidence=report.scene.confidence,
            origin=FeatureOrigin.MODEL,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.SCENE,
            key="confidence",
            label="场景判断置信度",
            value=report.scene.confidence,
            normalized=report.scene.confidence,
            description=f"场景判断置信度 {report.scene.confidence:.2f}。",
            evidence=("scene.confidence",),
            confidence=report.scene.confidence,
            origin=FeatureOrigin.MODEL,
            editable=False,
        ),
        _reading(
            category=FeatureCategory.COMPOSITION,
            key="balance",
            label="构图平衡",
            value=report.composition.balance.value,
            description=f"视觉模型判断构图平衡为 {report.composition.balance.value}。",
            evidence=("composition.balance",),
            confidence=report.composition.confidence,
            origin=FeatureOrigin.MODEL,
            editable=True,
        ),
        _reading(
            category=FeatureCategory.COMPOSITION,
            key="negativeSpace",
            label="负空间",
            value=report.composition.negative_space.value,
            description=f"视觉模型判断负空间为 {report.composition.negative_space.value}。",
            evidence=("composition.negativeSpace",),
            confidence=report.composition.confidence,
            origin=FeatureOrigin.MODEL,
            editable=True,
        ),
    ]
    if report.composition.subject_area_ratio is not None:
        readings.append(
            _reading(
                category=FeatureCategory.COMPOSITION,
                key="subjectArea",
                label="主体面积",
                value=report.composition.subject_area_ratio,
                normalized=report.composition.subject_area_ratio,
                description=f"主体面积约占 {report.composition.subject_area_ratio:.1%}。",
                evidence=("composition.subjectAreaRatio",),
                confidence=1.0,
                origin=FeatureOrigin.MEASUREMENT,
                editable=False,
            )
        )

    semantic_pairs = (
        (report.scene.confidence, 0.25),
        (report.lighting.confidence, 0.20),
        (report.color.confidence, 0.20),
        (report.composition.confidence, 0.15),
        (report.technical_quality.confidence, 0.20),
    )
    semantic_confidence = sum(value * weight for value, weight in semantic_pairs) / sum(
        weight for _, weight in semantic_pairs
    )
    overall_confidence = 0.45 + 0.55 * _clamp01(semantic_confidence)
    if report.engine.is_mock:
        overall_confidence *= 0.65
    overall_confidence = _clamp01(overall_confidence)

    limitations: list[str] = []
    if report.engine.is_mock:
        limitations.append(
            "当前分析由模拟 Provider 生成，场景、光线、色彩与构图语义仅供占位。"
        )
    if not color_measurement.hsv_histogram:
        limitations.append("缺少色相直方图，主色关系仅依据模型结果。")
    if overall_confidence < LOW_CONFIDENCE:
        limitations.append("整体置信度较低，建议增加参考照片或重新分析。")
    limitations.extend(report.limitations[:6])

    return PhotoVisualFeatures(
        extractor_version=EXTRACTOR_VERSION,
        image_id=report.image.id,
        image_sha256=report.image.sha256.lower(),
        analysis_id=report.analysis_id,
        analyzed_at=datetime.now(UTC),
        is_mock=report.engine.is_mock,
        overall_confidence=overall_confidence,
        scene=PhotoSceneFeatures(
            primary=report.scene.primary,
            secondary=report.scene.secondary,
            confidence=report.scene.confidence,
        ),
        color=PhotoColorFeatures(
            temperature_offset=temperature_offset,
            tint_offset=tint_offset,
            saturation_mean=color_measurement.saturation_mean,
            saturation_p10=color_measurement.saturation_p10,
            saturation_p50=color_measurement.saturation_p50,
            saturation_p90=color_measurement.saturation_p90,
            saturation_p95=color_measurement.saturation_p95,
            color_concentration=color_measurement.color_concentration,
            dominant_colors=report.color.dominant_colors,
            hue_distribution=(
                color_measurement.hsv_histogram[0]
                if color_measurement.hsv_histogram
                else ()
            ),
            harmony=report.color.harmony,
            tendency=report.color.temperature,
            level=report.color.saturation,
            monochrome=monochrome,
            confidence=report.color.confidence,
        ),
        tone=PhotoToneFeatures(
            luminance_mean=luminance.mean,
            luminance_std=luminance.std,
            luminance_p5=luminance.p5,
            luminance_p50=luminance.p50,
            luminance_p95=luminance.p95,
            highlights_pct=clipping.highlights_pct,
            shadows_pct=clipping.shadows_pct,
            contrast_strength=contrast_strength,
            high_key=high_key,
            low_key=low_key,
            low_light=low_light,
            contrast_level=report.lighting.contrast,
        ),
        light=PhotoLightFeatures(
            direction=report.lighting.direction,
            type=report.lighting.type,
            contrast=report.lighting.contrast,
            softness=softness,
            directional=report.lighting.direction in _DIRECTIONAL,
            confidence=report.lighting.confidence,
        ),
        texture=PhotoTextureFeatures(
            sharpness=detail.sharpness,
            noise=detail.noise_estimate,
            gradient_anisotropy=detail.gradient_anisotropy,
            grain_tendency=detail.noise_estimate,
            detail_retention=detail.sharpness,
            confidence=report.technical_quality.confidence,
        ),
        composition=PhotoCompositionFeatures(
            balance=report.composition.balance,
            subject_position=report.composition.subject_position,
            negative_space=report.composition.negative_space,
            occlusion=report.composition.occlusion,
            subject_area_ratio=report.composition.subject_area_ratio,
            horizon_tilt_deg=report.composition.horizon_tilt_deg,
            edge_density_grid=measurements.composition.edge_density_grid_3x3,
            confidence=report.composition.confidence,
        ),
        readings=tuple(readings),
        anomalies=_anomalies(report, contrast_strength=contrast_strength),
        limitations=tuple(limitations[:12]),
    )


class VisualDnaExtractor:
    """Stable seam for future extractor versions and tests."""

    version = EXTRACTOR_VERSION

    def extract(self, report: AnalysisReport) -> PhotoVisualFeatures:
        return extract_photo_features(report)


__all__ = ["EXTRACTOR_VERSION", "VisualDnaExtractor", "extract_photo_features"]
