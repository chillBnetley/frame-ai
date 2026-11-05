from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

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
    Priority,
    RecommendationCategory,
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
    RecommendationReport,
    RegionInfo,
    ReportImage,
    SubjectInfo,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
BBOX = BBox(x=0.1, y=0.1, width=0.4, height=0.5)


def _measurements() -> MeasurementsReport:
    return MeasurementsReport(
        luminance=LuminanceMeasurement(
            mean=0.4,
            std=0.2,
            p1=0.01,
            p5=0.05,
            p50=0.4,
            p95=0.9,
            p99=0.99,
            histogram32=(0.5, 0.5) + (0.0,) * 30,
        ),
        clipping=ClippingMeasurement(highlights_pct=1.0, shadows_pct=2.0),
        color=ColorMeasurement(
            mean_rgb=(0.2, 0.3, 0.4),
            cast=CastMeasurement(temperature=0.1, tint=-0.1),
            saturation_mean=0.3,
            saturation_p95=0.6,
        ),
        detail=DetailMeasurement(sharpness=0.3, noise_estimate=0.1),
        composition=CompositionMeasurement(
            edge_density_grid_3x3=(0.1,) * 9,
            brightness_centroid=(0.5, 0.5),
            horizon_tilt_deg=1.0,
        ),
    )


def _report(**overrides: object) -> AnalysisReport:
    data: dict[str, object] = {
        "analysis_id": uuid4(),
        "image": ReportImage(
            id=uuid4(),
            width=1000,
            height=800,
            aspect_ratio=1.25,
            sha256="a" * 64,
        ),
        "engine": EngineInfo(
            vision_provider="mock",
            vision_model="mock-vision",
            decision_provider="mock",
            decision_model="mock-decision",
            prompt_version="stage3/1",
            analyzer_version="frame-analyzer/1",
            is_mock=True,
        ),
        "scene": SceneResult(
            primary=SceneLabel.PORTRAIT,
            secondary=(SceneLabel.STREET,),
            confidence=0.5,
        ),
        "subjects": (
            SubjectInfo(
                id="subject_001",
                type=SubjectType.PERSON,
                role=SubjectRole.PRIMARY,
                confidence=0.5,
                bbox=BBOX,
                region_id="region_001",
            ),
        ),
        "regions": (
            RegionInfo(
                id="region_001",
                type=SubjectType.PERSON,
                source="vision",
                confidence=0.5,
                bbox=BBOX,
            ),
        ),
        "lighting": LightingResult(
            direction=LightingDirection.UNKNOWN,
            type=LightingType.UNKNOWN,
            contrast=ContrastLevel.UNKNOWN,
            confidence=0.0,
        ),
        "color": ColorResult(
            temperature=ColorTemperature.UNKNOWN,
            saturation=SaturationLevel.UNKNOWN,
            confidence=0.0,
        ),
        "composition": CompositionReport(
            balance=CompositionBalance.UNKNOWN,
            subject_position=SubjectPosition.UNKNOWN,
            negative_space=NegativeSpace.UNKNOWN,
            horizon_tilt_deg=None,
            confidence=0.0,
        ),
        "technical_quality": TechnicalQualityResult(
            exposure=ExposureQuality.UNKNOWN,
            sharpness=SharpnessQuality.UNKNOWN,
            noise=NoiseLevel.UNKNOWN,
            confidence=0.0,
        ),
        "measurements": _measurements(),
        "issues": (),
        "recommendations": (),
        "limitations": (),
        "created_at": NOW,
        "completed_at": NOW,
    }
    data.update(overrides)
    return AnalysisReport(**data)


def test_report_serializes_with_camel_case_aliases():
    payload = _report().model_dump(mode="json", by_alias=True)

    assert payload["schemaVersion"] == "stage3/1"
    assert payload["technicalQuality"]["exposure"] == "unknown"
    assert payload["measurements"]["composition"]["edgeDensityGrid3x3"] == [0.1] * 9
    assert payload["subjects"][0]["regionId"] == "region_001"
    assert payload["regions"][0]["mask"] is None
    assert payload["createdAt"].startswith("2026-11-03T12:00:00")


def test_subject_must_reference_an_existing_region():
    with pytest.raises(ValidationError, match="subject regionId"):
        _report(regions=())


def test_region_ids_must_be_unique():
    region = RegionInfo(
        id="region_001",
        type=SubjectType.PERSON,
        source="vision",
        confidence=0.5,
        bbox=BBOX,
    )
    with pytest.raises(ValidationError, match="region ids must be unique"):
        _report(regions=(region, region))


def test_issue_and_recommendation_regions_must_exist():
    issue = IssueReport(
        id="issue_001",
        type=IssueType.HIGHLIGHT_CLIPPING,
        severity=Severity.MEDIUM,
        confidence=0.5,
        evidence="高光裁切占比 1.0%。",
        region_ids=("region_999",),
    )
    with pytest.raises(ValidationError, match="issue regionIds"):
        _report(issues=(issue,))

    recommendation = RecommendationReport(
        category=RecommendationCategory.EXPOSURE,
        priority=Priority.MEDIUM,
        description="降低曝光以保护主体高光。",
        target_regions=("region_999",),
    )
    with pytest.raises(ValidationError, match="recommendation targetRegions"):
        _report(recommendations=(recommendation,))


def test_mask_must_stay_null():
    with pytest.raises(ValidationError):
        RegionInfo(
            id="region_001",
            type=SubjectType.PERSON,
            source="vision",
            confidence=0.5,
            bbox=BBOX,
            mask="rle:abc",  # type: ignore[arg-type]
        )


def test_histogram_must_be_normalized():
    with pytest.raises(ValidationError, match="histogram32 must sum to 1"):
        LuminanceMeasurement(
            mean=0.4,
            std=0.2,
            p1=0.01,
            p5=0.05,
            p50=0.4,
            p95=0.9,
            p99=0.99,
            histogram32=(0.1,) * 32,
        )


def test_completion_cannot_precede_creation():
    with pytest.raises(ValidationError, match="completedAt must not be earlier"):
        _report(completed_at=NOW - timedelta(seconds=1))


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        _report(unexpected="value")
