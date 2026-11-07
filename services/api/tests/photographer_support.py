from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.ai.base import PatchRequest, PlannerRequest
from app.ai.contracts import (
    BBox,
    ColorResult,
    ColorTemperature,
    CompositionBalance,
    ContrastLevel,
    ExposureQuality,
    IssueType,
    LightingDirection,
    LightingResult,
    LightingType,
    NegativeSpace,
    NoiseLevel,
    Occlusion,
    SaturationLevel,
    SceneLabel,
    SceneResult,
    Severity,
    SharpnessQuality,
    SubjectPosition,
    SubjectRole,
    SubjectType,
    TechnicalQualityResult,
)
from app.models.analysis_report import (
    AnalysisReport,
    CastMeasurement,
    ClippingMeasurement,
    ColorMeasurement,
    CompositionMeasurement,
    CompositionReport,
    DetailMeasurement,
    EngineInfo,
    IssueReport,
    LuminanceMeasurement,
    MeasurementsReport,
    RegionInfo,
    ReportImage,
    SubjectInfo,
)
from app.models.photographer import PhotographerPreferences, PlannerMode
from app.models.recipe import EditRecipe

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
BBOX = BBox(x=0.2, y=0.1, width=0.4, height=0.7)


def issue(
    issue_id: str = "issue_001",
    *,
    issue_type: IssueType = IssueType.HIGHLIGHT_CLIPPING,
    severity: Severity = Severity.MEDIUM,
    confidence: float = 0.8,
    evidence: str = "高光裁切占比 1.5%。",
    region_ids: tuple[str, ...] = ("region_001",),
) -> IssueReport:
    return IssueReport(
        id=issue_id,
        type=issue_type,
        severity=severity,
        confidence=confidence,
        evidence=evidence,
        region_ids=region_ids,
    )


def measurements(
    *,
    luminance_p50: float = 0.42,
    luminance_std: float = 0.18,
    luminance_p1: float = 0.05,
    luminance_p99: float = 0.98,
    highlights_pct: float = 1.5,
    shadows_pct: float = 2.5,
    saturation_mean: float = 0.35,
    cast_temperature: float = 0.0,
    cast_tint: float = 0.0,
    sharpness: float = 0.3,
    noise_estimate: float = 0.12,
) -> MeasurementsReport:
    return MeasurementsReport(
        luminance=LuminanceMeasurement(
            mean=0.45,
            std=luminance_std,
            p1=luminance_p1,
            p5=0.12,
            p50=luminance_p50,
            p95=0.9,
            p99=luminance_p99,
            histogram32=(0.0,) * 14 + (0.5, 0.5) + (0.0,) * 16,
        ),
        clipping=ClippingMeasurement(highlights_pct=highlights_pct, shadows_pct=shadows_pct),
        color=ColorMeasurement(
            mean_rgb=(0.18, 0.19, 0.2),
            cast=CastMeasurement(temperature=cast_temperature, tint=cast_tint),
            saturation_mean=saturation_mean,
            saturation_p95=0.62,
        ),
        detail=DetailMeasurement(sharpness=sharpness, noise_estimate=noise_estimate),
        composition=CompositionMeasurement(
            edge_density_grid_3x3=(0.1,) * 9,
            brightness_centroid=(0.5, 0.5),
            horizon_tilt_deg=None,
        ),
    )


def report(
    *,
    scene: SceneLabel = SceneLabel.PORTRAIT,
    issues: tuple[IssueReport, ...] = (),
    saturation: SaturationLevel = SaturationLevel.MODERATE,
    temperature: ColorTemperature = ColorTemperature.NEUTRAL,
    contrast: ContrastLevel = ContrastLevel.MODERATE,
    **measurement_overrides: Any,
) -> AnalysisReport:
    return AnalysisReport(
        analysis_id=uuid4(),
        image=ReportImage(
            id=uuid4(),
            width=1024,
            height=768,
            aspect_ratio=4 / 3,
            sha256="a" * 64,
        ),
        engine=EngineInfo(
            vision_provider="mock",
            vision_model="mock-vision",
            decision_provider="mock",
            decision_model="mock-decision",
            prompt_version="stage3/1",
            analyzer_version="frame-analyzer/1",
            is_mock=True,
        ),
        scene=SceneResult(primary=scene, confidence=0.6),
        subjects=(
            SubjectInfo(
                id="subject_001",
                type=SubjectType.PERSON,
                role=SubjectRole.PRIMARY,
                confidence=0.6,
                bbox=BBOX,
                region_id="region_001",
            ),
        ),
        regions=(
            RegionInfo(
                id="region_001",
                type=SubjectType.PERSON,
                source="vision",
                confidence=0.6,
                bbox=BBOX,
            ),
        ),
        lighting=LightingResult(
            direction=LightingDirection.SIDE,
            type=LightingType.NATURAL,
            contrast=contrast,
            confidence=0.5,
        ),
        color=ColorResult(
            temperature=temperature,
            saturation=saturation,
            confidence=0.5,
        ),
        composition=CompositionReport(
            balance=CompositionBalance.MODERATE,
            subject_position=SubjectPosition.CENTER,
            negative_space=NegativeSpace.MODERATE,
            occlusion=Occlusion.NONE,
            confidence=0.5,
        ),
        technical_quality=TechnicalQualityResult(
            exposure=ExposureQuality.BALANCED,
            sharpness=SharpnessQuality.GOOD,
            noise=NoiseLevel.LOW,
            confidence=0.5,
        ),
        measurements=measurements(**measurement_overrides),
        issues=issues,
        recommendations=(),
        limitations=(),
        created_at=NOW,
        completed_at=NOW,
    )


def recipe() -> EditRecipe:
    return EditRecipe()


def planner_request(
    *,
    analysis: AnalysisReport | None = None,
    current_recipe: EditRecipe | None = None,
    preferences: PhotographerPreferences | None = None,
    mode: PlannerMode = PlannerMode.AUTO,
) -> PlannerRequest:
    return PlannerRequest(
        analysis=analysis or report(),
        recipe=current_recipe or recipe(),
        preferences=preferences or PhotographerPreferences(),
        mode=mode,
    )


def patch_request(
    instruction: str,
    *,
    analysis: AnalysisReport | None = None,
    current_recipe: EditRecipe | None = None,
    preferences: PhotographerPreferences | None = None,
) -> PatchRequest:
    return PatchRequest(
        analysis=analysis or report(),
        recipe=current_recipe or recipe(),
        instruction=instruction,
        preferences=preferences or PhotographerPreferences(),
    )


def planner_draft_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "diagnosis": {
            "confirmed": [
                {
                    "issueId": "issue_001",
                    "type": "highlight_clipping",
                    "severity": "medium",
                    "confidence": 0.8,
                    "evidence": "高光裁切占比 1.5%。",
                    "evidenceRefs": ["issue_001", "region_001"],
                }
            ],
            "possible": [],
            "creativeChoices": [],
            "confidence": 0.8,
            "confidenceNote": "启发式置信度，不是校准概率。",
        },
        "direction": {
            "id": "natural_portrait",
            "name": "自然人像",
            "category": "scene",
            "description": "保留自然肤色，平衡人物曝光。",
            "strength": 0.5,
            "constraints": ["preserve_skin_tone", "preserve_highlight_detail"],
        },
        "adjustments": {"highlights": -20.0, "whites": -8.0},
        "localAdjustments": [],
        "rationale": ["压低高光以保留层次。"],
        "warnings": [],
        "limitations": [],
        "confidence": 0.8,
    }
    payload.update(overrides)
    return payload


def patch_draft_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "supported": True,
        "adjustments": {"saturation": -8.0},
        "localAdjustments": [],
        "reason": "只降低饱和度，保留其他编辑。",
        "warnings": [],
        "limitations": [],
        "unsupported": [],
        "confidence": 0.6,
    }
    payload.update(overrides)
    return payload
