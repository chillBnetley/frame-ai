from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.ai.contracts import (
    ColorHarmony,
    ColorTemperature,
    CompositionBalance,
    ContrastLevel,
    HexColor,
    LightingDirection,
    LightingType,
    NegativeSpace,
    Occlusion,
    SaturationLevel,
    SceneLabel,
    SubjectPosition,
    Text,
)
from app.models.analysis_task import TaskStage
from app.models.personal_style import PersonalStyleId

SHA256_PATTERN = r"^[0-9a-f]{64}$"
FEATURE_KEY_PATTERN = r"^[a-z][a-zA-Z0-9.]{1,63}$"
PHOTO_FEATURE_SCHEMA_VERSION: Literal["visual-dna-photo/1"] = "visual-dna-photo/1"
UnitValue = Annotated[float, Field(ge=0.0, le=1.0)]
SignedUnitValue = Annotated[float, Field(ge=-1.0, le=1.0)]


class _DnaModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class FeatureCategory(StrEnum):
    COLOR = "color"
    TONE = "tone"
    LIGHT = "light"
    TEXTURE = "texture"
    SCENE = "scene"
    COMPOSITION = "composition"


class FeatureOrigin(StrEnum):
    """Where a feature value came from, so objective and subjective data stay distinct."""

    MEASUREMENT = "measurement"
    MODEL = "model"
    DERIVED = "derived"


class FeatureSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"


class PersonalStyleAnalysisStatus(StrEnum):
    COMPLETED = "completed"
    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"
    MISSING = "missing"
    ANALYSIS_REQUIRED = "analysis_required"


class PhotoFeatureAnomaly(_DnaModel):
    code: str = Field(min_length=1, max_length=64)
    category: FeatureCategory
    severity: FeatureSeverity = FeatureSeverity.WARNING
    message: Text
    evidence: tuple[str, ...] = Field(default=(), max_length=10)


class PhotoFeatureReading(_DnaModel):
    """One explainable feature value.

    ``measurement`` readings are objective and read-only. ``model`` and
    ``derived`` readings describe an interpretation and may be edited by the
    user when they are promoted into a personal style.
    """

    category: FeatureCategory
    key: str = Field(pattern=FEATURE_KEY_PATTERN)
    label: Text
    value: float | str | bool
    normalized: SignedUnitValue | None = None
    description: Text
    evidence: tuple[str, ...] = Field(default=(), max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
    origin: FeatureOrigin
    editable: bool

    @model_validator(mode="after")
    def _only_interpretations_are_editable(self) -> Self:
        if self.origin is FeatureOrigin.MEASUREMENT and self.editable:
            raise ValueError("measurement readings are objective and must not be editable.")
        return self


class PhotoSceneFeatures(_DnaModel):
    primary: SceneLabel
    secondary: tuple[SceneLabel, ...] = Field(default=(), max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)


class PhotoColorFeatures(_DnaModel):
    temperature_offset: SignedUnitValue
    tint_offset: SignedUnitValue
    saturation_mean: UnitValue
    saturation_p10: UnitValue
    saturation_p50: UnitValue
    saturation_p90: UnitValue
    saturation_p95: UnitValue
    color_concentration: UnitValue
    dominant_colors: tuple[HexColor, ...] = Field(default=(), max_length=5)
    hue_distribution: tuple[UnitValue, ...] = Field(default=(), max_length=16)
    harmony: ColorHarmony = ColorHarmony.UNKNOWN
    tendency: ColorTemperature = ColorTemperature.UNKNOWN
    level: SaturationLevel = SaturationLevel.UNKNOWN
    monochrome: bool
    confidence: float = Field(ge=0.0, le=1.0)


class PhotoToneFeatures(_DnaModel):
    luminance_mean: UnitValue
    luminance_std: UnitValue
    luminance_p5: UnitValue
    luminance_p50: UnitValue
    luminance_p95: UnitValue
    highlights_pct: float = Field(ge=0.0, le=100.0)
    shadows_pct: float = Field(ge=0.0, le=100.0)
    contrast_strength: UnitValue
    high_key: bool
    low_key: bool
    low_light: bool
    contrast_level: ContrastLevel = ContrastLevel.UNKNOWN


class PhotoLightFeatures(_DnaModel):
    direction: LightingDirection = LightingDirection.UNKNOWN
    type: LightingType = LightingType.UNKNOWN
    contrast: ContrastLevel = ContrastLevel.UNKNOWN
    softness: UnitValue
    directional: bool
    confidence: float = Field(ge=0.0, le=1.0)


class PhotoTextureFeatures(_DnaModel):
    sharpness: UnitValue
    noise: UnitValue
    gradient_anisotropy: UnitValue
    grain_tendency: UnitValue
    detail_retention: UnitValue
    confidence: float = Field(ge=0.0, le=1.0)


class PhotoCompositionFeatures(_DnaModel):
    balance: CompositionBalance = CompositionBalance.UNKNOWN
    subject_position: SubjectPosition = SubjectPosition.UNKNOWN
    negative_space: NegativeSpace = NegativeSpace.UNKNOWN
    occlusion: Occlusion = Occlusion.UNKNOWN
    subject_area_ratio: UnitValue | None = None
    horizon_tilt_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    edge_density_grid: tuple[UnitValue, ...] = Field(default=(), max_length=9)
    confidence: float = Field(ge=0.0, le=1.0)


class PhotoVisualFeatures(_DnaModel):
    schema_version: Literal["visual-dna-photo/1"] = PHOTO_FEATURE_SCHEMA_VERSION
    extractor_version: str = Field(min_length=1, max_length=64)
    image_id: UUID
    image_sha256: str = Field(pattern=SHA256_PATTERN)
    analysis_id: UUID
    analyzed_at: datetime
    is_mock: bool
    overall_confidence: float = Field(ge=0.0, le=1.0)
    scene: PhotoSceneFeatures
    color: PhotoColorFeatures
    tone: PhotoToneFeatures
    light: PhotoLightFeatures
    texture: PhotoTextureFeatures
    composition: PhotoCompositionFeatures
    readings: tuple[PhotoFeatureReading, ...] = Field(default=(), max_length=40)
    anomalies: tuple[PhotoFeatureAnomaly, ...] = Field(default=(), max_length=10)
    limitations: tuple[Text, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def _readings_are_unique(self) -> Self:
        keys = [(reading.category.value, reading.key) for reading in self.readings]
        if len(set(keys)) != len(keys):
            raise ValueError("photo feature readings must be unique per category and key.")
        return self


class PersonalStyleReferenceAnalysis(_DnaModel):
    reference_id: UUID
    image_id: UUID | None = None
    status: PersonalStyleAnalysisStatus
    stage: TaskStage | None = None
    analysis_id: UUID | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    anomaly_count: int = Field(default=0, ge=0)
    feature_available: bool = False
    error: Text | None = None


class PersonalStyleAnalysisResponse(_DnaModel):
    style_id: PersonalStyleId
    references: tuple[PersonalStyleReferenceAnalysis, ...] = Field(default=(), max_length=20)
    completed_count: int = Field(ge=0)
    total_count: int = Field(ge=0)


class PersonalStyleAnalyzeRequest(_DnaModel):
    reference_ids: tuple[UUID, ...] | None = Field(default=None, max_length=20)
    force: bool = False

    @model_validator(mode="after")
    def _reference_ids_are_unique(self) -> Self:
        if self.reference_ids is not None and len(set(self.reference_ids)) != len(
            self.reference_ids
        ):
            raise ValueError("referenceIds must be unique.")
        return self


__all__ = [
    "FEATURE_KEY_PATTERN",
    "PHOTO_FEATURE_SCHEMA_VERSION",
    "FeatureCategory",
    "FeatureOrigin",
    "FeatureSeverity",
    "PersonalStyleAnalysisResponse",
    "PersonalStyleAnalysisStatus",
    "PersonalStyleAnalyzeRequest",
    "PersonalStyleReferenceAnalysis",
    "PhotoColorFeatures",
    "PhotoCompositionFeatures",
    "PhotoFeatureAnomaly",
    "PhotoFeatureReading",
    "PhotoLightFeatures",
    "PhotoSceneFeatures",
    "PhotoTextureFeatures",
    "PhotoToneFeatures",
    "PhotoVisualFeatures",
]
