from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
BBOX_TOLERANCE = 1e-6


HISTOGRAM_BINS = 32
EDGE_GRID_CELLS = 9


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
Text = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
HexColor = Annotated[
    str,
    StringConstraints(pattern=HEX_COLOR_PATTERN, to_upper=True),
]


class SceneLabel(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"
    STREET = "street"
    ARCHITECTURE = "architecture"
    NIGHT = "night"
    INDOOR = "indoor"
    FOOD = "food"
    NATURE = "nature"
    OTHER = "other"


class SubjectType(StrEnum):
    PERSON = "person"
    BUILDING = "building"
    SKY = "sky"
    ROAD = "road"
    PLANT = "plant"
    ANIMAL = "animal"
    FOOD = "food"
    VEHICLE = "vehicle"
    OTHER = "other"


class SubjectRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class LightingDirection(StrEnum):
    FRONT = "front"
    SIDE = "side"
    BACK = "back"
    SIDE_BACK = "side_back"
    DIFFUSE = "diffuse"
    OVERCAST = "overcast"
    ARTIFICIAL = "artificial"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class LightingType(StrEnum):
    NATURAL = "natural"
    ARTIFICIAL = "artificial"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ContrastLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class ColorTemperature(StrEnum):
    WARM = "warm"
    NEUTRAL = "neutral"
    COOL = "cool"
    UNKNOWN = "unknown"


class ColorHarmony(StrEnum):
    HARMONIOUS = "harmonious"
    MODERATE = "moderate"
    CLASHING = "clashing"
    UNKNOWN = "unknown"


class SaturationLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class CompositionBalance(StrEnum):
    BALANCED = "balanced"
    MODERATE = "moderate"
    UNBALANCED = "unbalanced"
    UNKNOWN = "unknown"


class SubjectPosition(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"
    TOP = "top"
    BOTTOM = "bottom"
    UNKNOWN = "unknown"


class NegativeSpace(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class Occlusion(StrEnum):
    NONE = "none"
    MINOR = "minor"
    SIGNIFICANT = "significant"
    UNKNOWN = "unknown"


class ExposureQuality(StrEnum):
    UNDEREXPOSED = "underexposed"
    SLIGHTLY_UNDEREXPOSED = "slightly_underexposed"
    BALANCED = "balanced"
    SLIGHTLY_OVEREXPOSED = "slightly_overexposed"
    OVEREXPOSED = "overexposed"
    UNKNOWN = "unknown"


class SharpnessQuality(StrEnum):
    POOR = "poor"
    SOFT = "soft"
    GOOD = "good"
    UNKNOWN = "unknown"


class NoiseLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class IssueType(StrEnum):
    OVEREXPOSURE = "overexposure"
    UNDEREXPOSURE = "underexposure"
    HIGHLIGHT_CLIPPING = "highlight_clipping"
    SHADOW_CLIPPING = "shadow_clipping"
    SUBJECT_UNDEREXPOSURE = "subject_underexposure"
    BACKGROUND_OVEREXPOSURE = "background_overexposure"
    COLOR_CAST = "color_cast"
    TEMPERATURE_MISMATCH = "temperature_mismatch"
    SATURATION_ISSUE = "saturation_issue"
    COLOR_HIERARCHY_ISSUE = "color_hierarchy_issue"
    SUBJECT_PLACEMENT = "subject_placement"
    BALANCE_ISSUE = "balance_issue"
    NEGATIVE_SPACE_ISSUE = "negative_space_issue"
    HORIZON_TILT = "horizon_tilt"
    FOCUS_ISSUE = "focus_issue"
    MOTION_BLUR = "motion_blur"
    HIGH_NOISE = "high_noise"
    LOW_DETAIL = "low_detail"
    HARSH_CONTRAST = "harsh_contrast"
    FLAT_LIGHTING = "flat_lighting"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendationCategory(StrEnum):
    EXPOSURE = "exposure"
    COLOR = "color"
    COMPOSITION = "composition"
    SHARPNESS = "sharpness"
    LIGHTING = "lighting"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnalysisOptions(_ContractModel):
    scene_recognition: bool = True
    subject_detection: bool = True
    lighting_analysis: bool = True
    color_analysis: bool = True
    composition_analysis: bool = True
    quality_diagnosis: bool = True

    @model_validator(mode="after")
    def _at_least_one(self) -> Self:
        if not any(self.model_dump().values()):
            raise ValueError("At least one analysis option must be enabled.")
        return self


class BBox(_ContractModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _within_unit_square(self) -> Self:
        if self.x + self.width > 1.0 + BBOX_TOLERANCE:
            raise ValueError("bbox x + width must not exceed 1.")
        if self.y + self.height > 1.0 + BBOX_TOLERANCE:
            raise ValueError("bbox y + height must not exceed 1.")
        return self


class SceneResult(_ContractModel):
    primary: SceneLabel
    secondary: tuple[SceneLabel, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _no_duplicate_secondary(self) -> Self:
        if len(set(self.secondary)) != len(self.secondary):
            raise ValueError("secondary scenes must be unique.")
        if self.primary in self.secondary:
            raise ValueError("primary scene must not appear in secondary scenes.")
        return self


class SubjectResult(_ContractModel):
    type: SubjectType
    role: SubjectRole
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox


class LightingResult(_ContractModel):
    direction: LightingDirection
    type: LightingType
    contrast: ContrastLevel
    confidence: float = Field(ge=0.0, le=1.0)


class ColorResult(_ContractModel):
    temperature: ColorTemperature
    saturation: SaturationLevel
    harmony: ColorHarmony = ColorHarmony.UNKNOWN
    dominant_colors: tuple[HexColor, ...] = Field(default=(), max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)


class CompositionResult(_ContractModel):
    balance: CompositionBalance
    subject_position: SubjectPosition
    negative_space: NegativeSpace
    occlusion: Occlusion = Occlusion.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0)


class UsageInfo(_ContractModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
    )

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class VisionResult(_ContractModel):
    scene: SceneResult
    subjects: tuple[SubjectResult, ...] = Field(default=(), max_length=20)
    lighting: LightingResult
    color: ColorResult
    composition: CompositionResult
    limitations: tuple[Text, ...] = Field(default=(), max_length=20)
    usage: UsageInfo | None = None


class MeasurementSummary(_ContractModel):
    feature_set_version: str = Field(min_length=1, max_length=64)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    aspect_ratio: float = Field(gt=0.0)
    luminance_mean: float = Field(ge=0.0, le=1.0)
    luminance_std: float = Field(ge=0.0, le=1.0)
    luminance_p1: float = Field(ge=0.0, le=1.0)
    luminance_p5: float = Field(ge=0.0, le=1.0)
    luminance_p50: float = Field(ge=0.0, le=1.0)
    luminance_p95: float = Field(ge=0.0, le=1.0)
    luminance_p99: float = Field(ge=0.0, le=1.0)
    histogram32: tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...] = Field(
        min_length=HISTOGRAM_BINS,
        max_length=HISTOGRAM_BINS,
    )
    highlights_pct: float = Field(ge=0.0, le=100.0)
    shadows_pct: float = Field(ge=0.0, le=100.0)
    mean_rgb_linear: tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...] = Field(
        min_length=3,
        max_length=3,
    )
    cast_temperature: float
    cast_tint: float
    saturation_mean: float = Field(ge=0.0, le=1.0)
    saturation_p95: float = Field(ge=0.0, le=1.0)
    color_richness: float = Field(ge=0.0, le=1.0)
    sharpness: float = Field(ge=0.0)
    noise_estimate: float = Field(ge=0.0, le=1.0)
    horizon_tilt_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    brightness_centroid_x: float = Field(ge=0.0, le=1.0)
    brightness_centroid_y: float = Field(ge=0.0, le=1.0)
    edge_density_grid_3x3: tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...] = Field(
        min_length=EDGE_GRID_CELLS,
        max_length=EDGE_GRID_CELLS,
    )
    dominant_colors: tuple[HexColor, ...] = Field(default=(), max_length=5)
    rgb_histogram: tuple[tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...], ...] = Field(
        default=(),
        max_length=3,
    )
    hsv_histogram: tuple[tuple[Annotated[float, Field(ge=0.0, le=1.0)], ...], ...] = Field(
        default=(),
        max_length=3,
    )
    saturation_p10: float = Field(default=0.0, ge=0.0, le=1.0)
    saturation_p50: float = Field(default=0.0, ge=0.0, le=1.0)
    saturation_p90: float = Field(default=0.0, ge=0.0, le=1.0)
    color_concentration: float = Field(default=0.0, ge=0.0, le=1.0)
    gradient_anisotropy: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _histogram_is_normalized(self) -> Self:
        if abs(sum(self.histogram32) - 1.0) > 1e-6:
            raise ValueError("histogram32 must sum to 1.")
        return self


class EvidenceRef(_ContractModel):
    source: str = Field(pattern=r"^(measurement|vision)$")
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=200)


class IssueCandidate(_ContractModel):
    id: Identifier
    type: IssueType
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Text
    region_ids: tuple[Identifier, ...] = Field(default=(), max_length=20)
    evidence_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=20)


class IssueSelection(_ContractModel):
    candidate_id: Identifier
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Text
    region_ids: tuple[Identifier, ...] = Field(default=(), max_length=20)


class TechnicalQualityResult(_ContractModel):
    exposure: ExposureQuality
    sharpness: SharpnessQuality
    noise: NoiseLevel
    confidence: float = Field(ge=0.0, le=1.0)


class RecommendationResult(_ContractModel):
    category: RecommendationCategory
    priority: Priority
    description: Text
    target_regions: tuple[Identifier, ...] = Field(default=(), max_length=20)


class DecisionResult(_ContractModel):
    technical_quality: TechnicalQualityResult
    issues: tuple[IssueSelection, ...] = Field(default=(), max_length=20)
    recommendations: tuple[RecommendationResult, ...] = Field(default=(), max_length=20)
    limitations: tuple[Text, ...] = Field(default=(), max_length=20)
    usage: UsageInfo | None = None


__all__ = [
    "AnalysisOptions",
    "BBox",
    "ColorResult",
    "ColorHarmony",
    "CompositionResult",
    "CompositionBalance",
    "ContrastLevel",
    "DecisionResult",
    "EDGE_GRID_CELLS",
    "EvidenceRef",
    "ExposureQuality",
    "HISTOGRAM_BINS",
    "IssueCandidate",
    "IssueSelection",
    "IssueType",
    "LightingDirection",
    "LightingResult",
    "LightingType",
    "MeasurementSummary",
    "NegativeSpace",
    "NoiseLevel",
    "Occlusion",
    "Priority",
    "RecommendationCategory",
    "RecommendationResult",
    "SceneLabel",
    "SceneResult",
    "Severity",
    "SharpnessQuality",
    "SubjectPosition",
    "SubjectResult",
    "SubjectRole",
    "SubjectType",
    "SaturationLevel",
    "TechnicalQualityResult",
    "UsageInfo",
    "VisionResult",
]
