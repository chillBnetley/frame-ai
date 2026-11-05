from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.ai.contracts import (
    EDGE_GRID_CELLS,
    HISTOGRAM_BINS,
    BBox,
    ColorResult,
    CompositionBalance,
    IssueType,
    LightingResult,
    NegativeSpace,
    Occlusion,
    Priority,
    RecommendationCategory,
    SceneResult,
    Severity,
    SubjectPosition,
    SubjectRole,
    SubjectType,
    TechnicalQualityResult,
    Text,
)
from app.ai.contracts import Identifier as ContractIdentifier

REPORT_SCHEMA_VERSION: Literal["stage3/1"] = "stage3/1"
REPORT_PROMPT_VERSION = "stage3/2"
REPORT_LIMITATION_LIMIT = 60
REPORT_COLLECTION_LIMIT = 20
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _ReportModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


Identifier = ContractIdentifier


class ReportImage(_ReportModel):
    id: UUID
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    aspect_ratio: float = Field(gt=0.0)
    sha256: str = Field(pattern=SHA256_PATTERN)


class EngineInfo(_ReportModel):
    vision_provider: str = Field(min_length=1, max_length=64)
    vision_model: str = Field(min_length=1, max_length=128)
    decision_provider: str = Field(min_length=1, max_length=64)
    decision_model: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=64)
    analyzer_version: str = Field(min_length=1, max_length=64)
    is_mock: bool


class SubjectInfo(_ReportModel):
    id: Identifier
    type: SubjectType
    role: SubjectRole
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox
    region_id: Identifier


class RegionInfo(_ReportModel):
    id: Identifier
    type: SubjectType
    source: Literal["vision", "detector"]
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox
    mask: None = None


class CompositionReport(_ReportModel):
    balance: CompositionBalance
    subject_position: SubjectPosition
    negative_space: NegativeSpace
    occlusion: Occlusion = Occlusion.UNKNOWN
    subject_area_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    horizon_tilt_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    confidence: float = Field(ge=0.0, le=1.0)


class LuminanceMeasurement(_ReportModel):
    mean: float = Field(ge=0.0, le=1.0)
    std: float = Field(ge=0.0, le=1.0)
    p1: float = Field(ge=0.0, le=1.0)
    p5: float = Field(ge=0.0, le=1.0)
    p50: float = Field(ge=0.0, le=1.0)
    p95: float = Field(ge=0.0, le=1.0)
    p99: float = Field(ge=0.0, le=1.0)
    histogram32: tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...] = Field(
        min_length=HISTOGRAM_BINS,
        max_length=HISTOGRAM_BINS,
    )

    @model_validator(mode="after")
    def _histogram_is_normalized(self) -> Self:
        if abs(sum(self.histogram32) - 1.0) > 1e-6:
            raise ValueError("histogram32 must sum to 1.")
        return self


class ClippingMeasurement(_ReportModel):
    highlights_pct: float = Field(ge=0.0, le=100.0)
    shadows_pct: float = Field(ge=0.0, le=100.0)


class CastMeasurement(_ReportModel):
    temperature: float
    tint: float


class ColorMeasurement(_ReportModel):
    mean_rgb: tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...] = Field(
        min_length=3,
        max_length=3,
    )
    cast: CastMeasurement
    saturation_mean: float = Field(ge=0.0, le=1.0)
    saturation_p95: float = Field(ge=0.0, le=1.0)
    saturation_p10: float = Field(default=0.0, ge=0.0, le=1.0)
    saturation_p50: float = Field(default=0.0, ge=0.0, le=1.0)
    saturation_p90: float = Field(default=0.0, ge=0.0, le=1.0)
    color_concentration: float = Field(default=0.0, ge=0.0, le=1.0)
    rgb_histogram: tuple[tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...], ...] = Field(
        default=(),
        max_length=3,
    )
    hsv_histogram: tuple[tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...], ...] = Field(
        default=(),
        max_length=3,
    )


class DetailMeasurement(_ReportModel):
    sharpness: float = Field(ge=0.0)
    noise_estimate: float = Field(ge=0.0, le=1.0)
    gradient_anisotropy: float = Field(default=0.0, ge=0.0, le=1.0)


class CompositionMeasurement(_ReportModel):
    edge_density_grid_3x3: tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...] = Field(
        min_length=EDGE_GRID_CELLS,
        max_length=EDGE_GRID_CELLS,
        validation_alias=AliasChoices("edge_density_grid_3x3", "edgeDensityGrid3x3"),
        serialization_alias="edgeDensityGrid3x3",
    )
    brightness_centroid: tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...] = Field(
        min_length=2,
        max_length=2,
    )
    horizon_tilt_deg: float | None = Field(default=None, ge=-90.0, le=90.0)


class MeasurementsReport(_ReportModel):
    luminance: LuminanceMeasurement
    clipping: ClippingMeasurement
    color: ColorMeasurement
    detail: DetailMeasurement
    composition: CompositionMeasurement


class IssueReport(_ReportModel):
    id: Identifier
    type: IssueType
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Text
    suggestion: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
        ]
        | None
    ) = None
    region_ids: tuple[Identifier, ...] = Field(
        default=(),
        max_length=REPORT_COLLECTION_LIMIT,
    )


class RecommendationReport(_ReportModel):
    category: RecommendationCategory
    priority: Priority
    description: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]
    target_regions: tuple[Identifier, ...] = Field(
        default=(),
        max_length=REPORT_COLLECTION_LIMIT,
    )


class AnalysisReport(_ReportModel):
    analysis_id: UUID
    schema_version: Literal["stage3/1"] = REPORT_SCHEMA_VERSION
    status: Literal["completed"] = "completed"
    image: ReportImage
    engine: EngineInfo
    scene: SceneResult
    subjects: tuple[SubjectInfo, ...] = Field(
        default=(),
        max_length=REPORT_COLLECTION_LIMIT,
    )
    regions: tuple[RegionInfo, ...] = Field(
        default=(),
        max_length=REPORT_COLLECTION_LIMIT,
    )
    lighting: LightingResult
    color: ColorResult
    composition: CompositionReport
    technical_quality: TechnicalQualityResult
    measurements: MeasurementsReport
    issues: tuple[IssueReport, ...] = Field(
        default=(),
        max_length=REPORT_COLLECTION_LIMIT,
    )
    recommendations: tuple[RecommendationReport, ...] = Field(
        default=(),
        max_length=REPORT_COLLECTION_LIMIT,
    )
    limitations: tuple[Text, ...] = Field(
        default=(),
        max_length=REPORT_LIMITATION_LIMIT,
    )
    created_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def _references_are_consistent(self) -> Self:
        region_ids = [region.id for region in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("region ids must be unique.")
        known_regions = set(region_ids)

        subject_ids = [subject.id for subject in self.subjects]
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("subject ids must be unique.")
        for subject in self.subjects:
            if subject.region_id not in known_regions:
                raise ValueError("subject regionId must reference an existing region.")

        issue_ids = [issue.id for issue in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("issue ids must be unique.")
        for issue in self.issues:
            if not set(issue.region_ids) <= known_regions:
                raise ValueError("issue regionIds must reference existing regions.")

        for recommendation in self.recommendations:
            if not set(recommendation.target_regions) <= known_regions:
                raise ValueError("recommendation targetRegions must reference existing regions.")

        if self.completed_at < self.created_at:
            raise ValueError("completedAt must not be earlier than createdAt.")
        return self


__all__ = [
    "AnalysisReport",
    "CastMeasurement",
    "ClippingMeasurement",
    "ColorMeasurement",
    "CompositionMeasurement",
    "CompositionReport",
    "DetailMeasurement",
    "EngineInfo",
    "IssueReport",
    "LuminanceMeasurement",
    "MeasurementsReport",
    "REPORT_PROMPT_VERSION",
    "REPORT_SCHEMA_VERSION",
    "RecommendationReport",
    "RegionInfo",
    "ReportImage",
    "SubjectInfo",
]
