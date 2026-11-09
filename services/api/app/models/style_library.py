from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.ai.contracts import SceneLabel, Text
from app.models.photographer import (
    PhotographerStyleId,
    ShortName,
    StyleCategory,
)
from app.models.recipe import StyleId
from app.models.style_profile import StyleKind, StyleProfile, StyleProfileVersion

RecommendationBasis = Literal["scene", "library"]


class _StyleLibraryModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class StyleLibraryItem(_StyleLibraryModel):
    """Card-sized projection of one archive; the full archive lives in the detail view."""

    id: PhotographerStyleId
    kind: StyleKind
    version: StyleProfileVersion
    name: ShortName
    description: Text
    category: StyleCategory
    signature: tuple[Text, ...] = Field(min_length=1, max_length=3)
    suitable_scenes: tuple[SceneLabel, ...] = Field(min_length=1, max_length=9)
    engine_style: StyleId
    default_strength: float = Field(ge=0.0, le=1.0)
    enabled: bool
    favorite: bool

    @classmethod
    def from_profile(cls, profile: StyleProfile, *, favorite: bool) -> Self:
        return cls(
            id=profile.id,
            kind=profile.kind,
            version=profile.version,
            name=profile.name,
            description=profile.description,
            category=(
                StyleCategory.CREATIVE
                if profile.kind in {StyleKind.MASTER, StyleKind.PERSONAL}
                else StyleCategory.SCENE
            ),
            signature=(
                profile.color.tendency,
                profile.light.expression,
                profile.composition.geometry,
            ),
            suitable_scenes=profile.scene_fit.suitable,
            engine_style=profile.engine_style,
            default_strength=profile.default_strength,
            enabled=profile.enabled,
            favorite=favorite,
        )


class StyleLibraryListResponse(_StyleLibraryModel):
    styles: tuple[StyleLibraryItem, ...] = Field(default=(), max_length=64)


class StyleDetailResponse(_StyleLibraryModel):
    style: StyleProfile
    favorite: bool


class StyleVersionListResponse(_StyleLibraryModel):
    style_id: PhotographerStyleId
    versions: tuple[StyleProfileVersion, ...] = Field(default=(), max_length=64)


class StyleFavoriteResponse(_StyleLibraryModel):
    style_id: PhotographerStyleId
    favorite: bool


class StyleEnabledRequest(_StyleLibraryModel):
    enabled: bool


class StyleEnabledResponse(_StyleLibraryModel):
    style_id: PhotographerStyleId
    enabled: bool


class StyleRecommendation(_StyleLibraryModel):
    style: StyleLibraryItem
    reason: Text


class StyleRecommendedResponse(_StyleLibraryModel):
    basis: RecommendationBasis
    scene: SceneLabel | None = None
    styles: tuple[StyleRecommendation, ...] = Field(default=(), max_length=20)


class StyleRecentItem(_StyleLibraryModel):
    style: StyleLibraryItem
    last_used_at: datetime


class StyleRecentResponse(_StyleLibraryModel):
    styles: tuple[StyleRecentItem, ...] = Field(default=(), max_length=50)


__all__ = [
    "RecommendationBasis",
    "StyleDetailResponse",
    "StyleEnabledRequest",
    "StyleEnabledResponse",
    "StyleFavoriteResponse",
    "StyleLibraryItem",
    "StyleLibraryListResponse",
    "StyleRecentItem",
    "StyleRecentResponse",
    "StyleRecommendation",
    "StyleRecommendedResponse",
    "StyleVersionListResponse",
]
