from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.ai.contracts import Text
from app.models.personal_style import (
    BoundedTarget,
    PersonalAvoidEffect,
    PersonalStyleDefinition,
    PersonalStyleProfile,
)
from app.models.photographer import PhotographerStyleId, ShortName
from app.models.style_profile import StyleProfileVersion

MixDimension = Literal["color", "tone", "light", "texture", "composition", "scene"]
MixSource = Literal["a", "b", "blend"]
ConflictResolution = Literal["a", "b", "neutral", "auto"]

MIX_DIMENSIONS: tuple[MixDimension, ...] = (
    "color",
    "tone",
    "light",
    "texture",
    "composition",
    "scene",
)

_KNOWN_CONFLICT_DIMENSIONS = frozenset(
    {
        "color.saturation",
        "color.temperature",
        "color.tint",
        "tone.contrast",
        "tone.key",
        "skin",
        "detail",
        "scene",
    }
)


class _MixModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class StyleMixSourceRef(_MixModel):
    style_id: PhotographerStyleId
    version: StyleProfileVersion | None = None


class StyleMixRequest(_MixModel):
    style_a: StyleMixSourceRef
    style_b: StyleMixSourceRef
    weight: int = Field(default=50, ge=0, le=100)
    sources: dict[MixDimension, MixSource] = Field(default_factory=dict)
    resolutions: dict[str, ConflictResolution] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _two_distinct_styles(self) -> Self:
        if self.style_a.style_id == self.style_b.style_id and (self.style_a.version or "") == (
            self.style_b.version or ""
        ):
            raise ValueError("styleA and styleB must be two different styles.")
        unknown = sorted(set(self.resolutions) - _KNOWN_CONFLICT_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown conflict dimensions: {', '.join(unknown)}")
        return self


class StyleMixSaveRequest(_MixModel):
    style_a: StyleMixSourceRef
    style_b: StyleMixSourceRef
    weight: int = Field(default=50, ge=0, le=100)
    sources: dict[MixDimension, MixSource] = Field(default_factory=dict)
    resolutions: dict[str, ConflictResolution] = Field(default_factory=dict)
    name: ShortName
    description: Text | None = None
    targets: dict[str, BoundedTarget] | None = None
    avoid: tuple[PersonalAvoidEffect, ...] | None = Field(default=None, max_length=8)
    note: Text | None = None

    @model_validator(mode="after")
    def _two_distinct_styles(self) -> Self:
        if self.style_a.style_id == self.style_b.style_id and (self.style_a.version or "") == (
            self.style_b.version or ""
        ):
            raise ValueError("styleA and styleB must be two different styles.")
        unknown = sorted(set(self.resolutions) - _KNOWN_CONFLICT_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown conflict dimensions: {', '.join(unknown)}")
        if self.avoid is not None and len(set(self.avoid)) != len(self.avoid):
            raise ValueError("avoid must be unique.")
        return self


class StyleMixProvenance(_MixModel):
    style_a_id: str
    style_a_version: StyleProfileVersion
    style_a_name: ShortName
    style_b_id: str
    style_b_version: StyleProfileVersion
    style_b_name: ShortName
    weight: int = Field(ge=0, le=100)
    sources: dict[MixDimension, MixSource]
    resolutions: dict[str, ConflictResolution] = Field(default_factory=dict)
    combination_rules: tuple[Text, ...] = Field(default=(), max_length=12)
    user_overrides: dict[str, Any] = Field(default_factory=dict)


class StyleMixConflict(_MixModel):
    dimension: str = Field(min_length=1, max_length=64)
    title: Text
    labels: tuple[str, str]
    message: Text
    suggestion: Text
    resolution: ConflictResolution
    resolved_by: Literal["weight", "source", "protection", "user"]


class StyleMixDimensionPlan(_MixModel):
    dimension: MixDimension
    title: Text
    source: MixSource
    description: Text
    from_a: Text
    from_b: Text


class StyleMixPreviewResponse(_MixModel):
    profile: PersonalStyleProfile
    definition: PersonalStyleDefinition
    weight: int = Field(ge=0, le=100)
    sources: dict[MixDimension, MixSource]
    dimensions: tuple[StyleMixDimensionPlan, ...] = Field(default=(), max_length=6)
    conflicts: tuple[StyleMixConflict, ...] = Field(default=(), max_length=8)
    protections: tuple[Text, ...] = Field(default=(), max_length=12)
    summary: Text
    limitations: tuple[Text, ...] = Field(default=(), max_length=12)
    provenance: StyleMixProvenance


__all__ = [
    "MIX_DIMENSIONS",
    "ConflictResolution",
    "MixDimension",
    "MixSource",
    "StyleMixConflict",
    "StyleMixDimensionPlan",
    "StyleMixPreviewResponse",
    "StyleMixProvenance",
    "StyleMixRequest",
    "StyleMixSaveRequest",
    "StyleMixSourceRef",
]
