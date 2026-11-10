from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.ai.contracts import SceneLabel, Text, UsageInfo
from app.models.personal_style import (
    PERSONAL_TARGET_FIELDS,
    BoundedTarget,
    PersonalAvoidEffect,
    PersonalStyleId,
)
from app.models.photographer import DirectionConstraint, ShortName
from app.models.style_profile import (
    StyleColorTraits,
    StyleCompositionTraits,
    StyleLightTraits,
    StyleProfileVersion,
    StyleTextureTraits,
)


class _AuthoringModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


def _check_targets(targets: dict[str, float]) -> None:
    unknown = sorted(set(targets) - set(PERSONAL_TARGET_FIELDS))
    if unknown:
        raise ValueError("unknown style target fields: " + ", ".join(unknown))


def _check_unique(values: tuple[object, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique.")


class StyleAuthoringDraft(_AuthoringModel):
    """Validated structured style proposal produced by the authoring provider."""

    name: ShortName
    description: Text
    color: StyleColorTraits
    light: StyleLightTraits
    composition: StyleCompositionTraits
    texture: StyleTextureTraits
    suitable_scenes: tuple[SceneLabel, ...] = Field(min_length=1, max_length=9)
    unsuitable_notes: Text
    targets: dict[str, BoundedTarget] = Field(default_factory=dict)
    protected: tuple[DirectionConstraint, ...] = Field(default=(), max_length=11)
    avoid: tuple[PersonalAvoidEffect, ...] = Field(default=(), max_length=8)
    summary: Text
    rationale: tuple[Text, ...] = Field(default=(), max_length=8)
    warnings: tuple[Text, ...] = Field(default=(), max_length=8)
    limitations: tuple[Text, ...] = Field(default=(), max_length=8)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    usage: UsageInfo | None = None

    @model_validator(mode="after")
    def _draft_is_consistent(self) -> Self:
        _check_targets(self.targets)
        _check_unique(self.suitable_scenes, "suitableScenes")
        _check_unique(self.protected, "protected")
        _check_unique(self.avoid, "avoid")
        return self


class StyleAuthoringProviderInfo(_AuthoringModel):
    name: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=64)
    is_mock: bool


class CustomStyleParseRequest(_AuthoringModel):
    name: ShortName
    description: Text
    avoid: Text | None = None
    suitable_scenes: tuple[SceneLabel, ...] = Field(default=(), max_length=9)

    @field_validator("avoid", mode="before")
    @classmethod
    def _blank_avoid_is_absent(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _scenes_are_unique(self) -> Self:
        _check_unique(self.suitable_scenes, "suitableScenes")
        return self


class CustomStyleParseResponse(_AuthoringModel):
    draft: StyleAuthoringDraft
    provider: StyleAuthoringProviderInfo


class CustomStyleSaveRequest(_AuthoringModel):
    draft: StyleAuthoringDraft
    note: Text | None = None


class CustomStyleRefineRequest(_AuthoringModel):
    instruction: Text


class CustomStyleRefineResponse(_AuthoringModel):
    style_id: PersonalStyleId
    current_version: StyleProfileVersion
    draft: StyleAuthoringDraft
    provider: StyleAuthoringProviderInfo


class CustomStyleRefineApplyRequest(_AuthoringModel):
    draft: StyleAuthoringDraft
    note: Text | None = None


__all__ = [
    "CustomStyleParseRequest",
    "CustomStyleParseResponse",
    "CustomStyleRefineApplyRequest",
    "CustomStyleRefineRequest",
    "CustomStyleRefineResponse",
    "CustomStyleSaveRequest",
    "StyleAuthoringDraft",
    "StyleAuthoringProviderInfo",
]
