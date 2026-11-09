from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.ai.contracts import Text
from app.models.conversion import ConversionMode
from app.models.photographer import EvidenceReference, PhotographerStyleId, ShortName
from app.models.style_profile import StyleKind, StyleProfileVersion

STYLE_FIT_SCHEMA_VERSION: Literal["stage6/1"] = "stage6/1"
STYLE_FIT_ENGINE_VERSION: Literal["style-fit/1"] = "style-fit/1"


class _StyleFitModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class FitDimension(StrEnum):
    COLOR = "color"
    LIGHT = "light"
    SCENE = "scene"
    COMPOSITION = "composition"
    SUBJECT = "subject"


class FitLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSUITABLE = "unsuitable"


class DimensionFit(_StyleFitModel):
    dimension: FitDimension
    level: FitLevel
    score: float = Field(ge=0.0, le=100.0)
    basis: Text
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=8)


class StyleFitConflict(_StyleFitModel):
    """One concrete obstacle between the photo and the target style."""

    dimension: FitDimension
    description: Text
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=8)
    improvable: bool


class StyleFitAlternative(_StyleFitModel):
    style_id: PhotographerStyleId
    name: ShortName
    kind: StyleKind
    score: float = Field(ge=0.0, le=100.0)
    level: FitLevel
    reason: Text


class RecommendedStrength(_StyleFitModel):
    minimum: float = Field(ge=0.0, le=1.0)
    maximum: float = Field(ge=0.0, le=1.0)
    default: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordering_is_valid(self) -> Self:
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError("recommended strength must satisfy minimum <= default <= maximum.")
        return self


class StyleFitResponse(_StyleFitModel):
    schema_version: Literal["stage6/1"] = STYLE_FIT_SCHEMA_VERSION
    engine_version: Literal["style-fit/1"] = STYLE_FIT_ENGINE_VERSION
    image_id: UUID
    analysis_id: UUID
    is_mock: bool
    style_id: PhotographerStyleId
    style_name: ShortName
    style_kind: StyleKind
    style_version: StyleProfileVersion
    overall_score: float = Field(ge=0.0, le=100.0)
    overall_level: FitLevel
    summary: Text
    dimensions: tuple[DimensionFit, ...] = Field(min_length=5, max_length=5)
    conflicts: tuple[StyleFitConflict, ...] = Field(default=(), max_length=8)
    achievable: tuple[Text, ...] = Field(default=(), max_length=8)
    unachievable: tuple[Text, ...] = Field(default=(), max_length=8)
    recommended_mode: ConversionMode
    recommended_strength: RecommendedStrength
    alternatives: tuple[StyleFitAlternative, ...] = Field(default=(), max_length=5)
    limitations: tuple[Text, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _dimensions_are_unique(self) -> Self:
        dimensions = [item.dimension for item in self.dimensions]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("fit dimensions must be unique.")
        return self


__all__ = [
    "ConversionMode",
    "DimensionFit",
    "FitDimension",
    "FitLevel",
    "RecommendedStrength",
    "STYLE_FIT_ENGINE_VERSION",
    "STYLE_FIT_SCHEMA_VERSION",
    "StyleFitAlternative",
    "StyleFitConflict",
    "StyleFitResponse",
]
