from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.ai.contracts import SceneLabel, Text
from app.models.personal_style import (
    PersonalStyleDefinition,
    PersonalStyleProfile,
    PersonalStyleStatus,
)
from app.models.style_profile import StyleProfileVersion

FusionSectionKey = Literal["color", "tone", "light", "texture", "scene", "constraints"]


class _FusionModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class PersonalStyleFusionRequest(_FusionModel):
    reference_ids: tuple[UUID, ...] | None = Field(default=None, min_length=1, max_length=20)
    note: Text | None = None

    @model_validator(mode="after")
    def _reference_ids_are_unique(self) -> Self:
        if self.reference_ids is not None and len(set(self.reference_ids)) != len(
            self.reference_ids
        ):
            raise ValueError("referenceIds must be unique.")
        return self


class PersonalStyleFusionSection(_FusionModel):
    key: FusionSectionKey
    title: Text
    description: Text
    evidence: tuple[Text, ...] = Field(default=(), max_length=12)


class PersonalStyleFusionConflict(_FusionModel):
    dimension: str = Field(min_length=1, max_length=64)
    labels: tuple[str, str]
    support: tuple[float, float]
    message: Text


class PersonalStyleFusionScene(_FusionModel):
    scene: SceneLabel
    photo_count: int = Field(ge=1)
    share: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    description: Text


class PersonalStyleReferenceContribution(_FusionModel):
    reference_id: UUID
    image_id: UUID | None = None
    scene: SceneLabel
    confidence: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    anomaly_count: int = Field(ge=0)


class PersonalStyleFusionResponse(_FusionModel):
    style: PersonalStyleProfile
    definition: PersonalStyleDefinition
    version: StyleProfileVersion
    status: PersonalStyleStatus
    favorite: bool
    summary: Text
    sections: tuple[PersonalStyleFusionSection, ...] = Field(default=(), max_length=6)
    conflicts: tuple[PersonalStyleFusionConflict, ...] = Field(default=(), max_length=8)
    scenes: tuple[PersonalStyleFusionScene, ...] = Field(default=(), max_length=9)
    contributions: tuple[PersonalStyleReferenceContribution, ...] = Field(default=(), max_length=20)
    occasional: tuple[Text, ...] = Field(default=(), max_length=8)
    stability: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    sample_count: int = Field(ge=1)
    anomaly_count: int = Field(ge=0)
    default_strength: float = Field(ge=0.0, le=1.0)
    limitations: tuple[Text, ...] = Field(default=(), max_length=12)
    created_at: datetime


__all__ = [
    "FusionSectionKey",
    "PersonalStyleFusionConflict",
    "PersonalStyleFusionRequest",
    "PersonalStyleFusionResponse",
    "PersonalStyleFusionScene",
    "PersonalStyleFusionSection",
    "PersonalStyleReferenceContribution",
]
