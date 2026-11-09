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

from app.ai.contracts import SceneLabel, Text
from app.models.photographer import (
    DirectionConstraint,
    PhotographerStyleId,
    ShortName,
    StyleCategory,
    StyleDefinition,
    StyleEnvelope,
)
from app.models.recipe import StyleId

StyleProfileVersion = Annotated[
    str,
    StringConstraints(pattern=r"^\d+\.\d+$"),
]
StyleSourceUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^https?://[^\s]+$"),
]
StyleSourceTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]


class _StyleProfileModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class StyleKind(StrEnum):
    MASTER = "master"
    GENRE = "genre"
    PERSONAL = "personal"


class StyleColorTraits(_StyleProfileModel):
    tendency: Text
    relationships: Text
    saturation: Text


class StyleLightTraits(_StyleProfileModel):
    contrast: Text
    shadows: Text
    highlights: Text
    expression: Text


class StyleCompositionTraits(_StyleProfileModel):
    space: Text
    geometry: Text
    negative_space: Text
    subject_relation: Text


class StyleTextureTraits(_StyleProfileModel):
    grain: Text
    sharpness: Text
    detail: Text


class StyleSceneFit(_StyleProfileModel):
    suitable: tuple[SceneLabel, ...] = Field(min_length=1, max_length=9)
    suitable_notes: Text
    unsuitable_notes: Text

    @model_validator(mode="after")
    def _unique_suitable(self) -> Self:
        if len(set(self.suitable)) != len(self.suitable):
            raise ValueError("sceneFit.suitable must be unique.")
        return self


class StyleSource(_StyleProfileModel):
    title: StyleSourceTitle
    url: StyleSourceUrl | None = None
    license: Text


class StyleProfile(_StyleProfileModel):
    """A master or genre style archive.

    The archive is understanding material for AI decisions, not a fixed
    parameter table: ``envelope``/``engineStyle`` only bound what the stage 4
    engine may realise, while the trait sections describe the visual language.
    """

    id: PhotographerStyleId
    kind: StyleKind
    version: StyleProfileVersion = "1.0"
    name: ShortName
    description: Text
    philosophy: Text
    color: StyleColorTraits
    light: StyleLightTraits
    composition: StyleCompositionTraits
    texture: StyleTextureTraits
    scene_fit: StyleSceneFit
    post_strategy: Text
    capture_techniques: Text
    constraints: tuple[DirectionConstraint, ...] = Field(default=(), max_length=11)
    preserve_notes: Text
    sources: tuple[StyleSource, ...] = Field(min_length=1, max_length=8)
    engine_style: StyleId = "natural"
    envelope: StyleEnvelope = Field(default_factory=StyleEnvelope)
    default_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    enabled: bool = True

    @model_validator(mode="after")
    def _unique_constraints(self) -> Self:
        if len(set(self.constraints)) != len(self.constraints):
            raise ValueError("constraints must be unique.")
        return self

    def to_style_definition(self) -> StyleDefinition:
        """Project the archive onto the stage 5 style contract."""
        return StyleDefinition(
            id=self.id,
            version=self.version,
            name=self.name,
            category=(
                StyleCategory.CREATIVE
                if self.kind in {StyleKind.MASTER, StyleKind.PERSONAL}
                else StyleCategory.SCENE
            ),
            description=self.description,
            supported_scenes=self.scene_fit.suitable,
            default_strength=self.default_strength,
            envelope=self.envelope,
            constraints=self.constraints,
            engine_style=self.engine_style,
            enabled=self.enabled,
        )


__all__ = [
    "StyleColorTraits",
    "StyleCompositionTraits",
    "StyleKind",
    "StyleLightTraits",
    "StyleProfile",
    "StyleProfileVersion",
    "StyleSceneFit",
    "StyleSource",
    "StyleSourceTitle",
    "StyleSourceUrl",
    "StyleTextureTraits",
]
