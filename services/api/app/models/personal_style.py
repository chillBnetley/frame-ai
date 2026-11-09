from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.ai.contracts import SceneLabel, Text
from app.models.photographer import DirectionConstraint, ShortName
from app.models.style_profile import (
    StyleColorTraits,
    StyleCompositionTraits,
    StyleKind,
    StyleLightTraits,
    StyleProfile,
    StyleProfileVersion,
    StyleSceneFit,
    StyleSource,
    StyleTextureTraits,
)

PERSONAL_STYLE_ID_PATTERN = r"^personal_[a-z0-9]{6,32}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"

PersonalStyleId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=PERSONAL_STYLE_ID_PATTERN),
]
BoundedTarget = Annotated[float, Field(ge=-100.0, le=100.0)]

PERSONAL_TARGET_FIELDS: tuple[str, ...] = (
    "exposureEv",
    "contrast",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "temperature",
    "tint",
    "saturation",
    "vibrance",
    "clarity",
    "sharpen",
    "denoise",
    "vignette",
    "grain",
)
PERSONAL_STABILITY_FIELDS: tuple[str, ...] = ("color", "tone", "light", "texture", "scene")


class _PersonalModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class PersonalStyleSource(StrEnum):
    PHOTOS = "photos"
    CUSTOM = "custom"
    MIXED = "mixed"
    EVOLUTION = "evolution"


class PersonalStyleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DISABLED = "disabled"


class PersonalStyleChangeSource(StrEnum):
    ANALYSIS = "analysis"
    USER = "user"
    CUSTOM = "custom"
    MIX = "mix"
    EVOLUTION = "evolution"
    RESTORE = "restore"


class PersonalStyleReferenceStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"
    MISSING = "missing"


class PersonalStyleConsentScope(StrEnum):
    ANALYSIS_ONLY = "analysis_only"


class PersonalAvoidEffect(StrEnum):
    OVERSATURATED = "oversaturated"
    CRUSHED_BLACKS = "crushed_blacks"
    CLIPPED_HIGHLIGHTS = "clipped_highlights"
    COLOR_CAST = "color_cast"
    UNNATURAL_SKIN = "unnatural_skin"
    HEAVY_FILTER = "heavy_filter"
    OVER_SHARPENED = "over_sharpened"
    FLAT_CONTRAST = "flat_contrast"


def _check_targets(targets: dict[str, float]) -> None:
    unknown = sorted(set(targets) - set(PERSONAL_TARGET_FIELDS))
    if unknown:
        raise ValueError(f"unknown personal style target fields: {', '.join(unknown)}")


def _check_unique(values: tuple[Any, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique.")


class PersonalStyleHints(_PersonalModel):
    """Structured personal bias used by the existing style decision chain.

    These values are bounded suggestions, not recipe parameters: the stage 5
    generator still applies the profile envelope, conversion-mode scaling, and
    the stage 4 validator before anything reaches the renderer.
    """

    schema_version: Literal["personal/1"] = "personal/1"
    source: PersonalStyleSource
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    stability: dict[str, float] = Field(default_factory=dict)
    targets: dict[str, BoundedTarget] = Field(default_factory=dict)
    scene_targets: dict[SceneLabel, dict[str, BoundedTarget]] = Field(default_factory=dict)
    protected: tuple[DirectionConstraint, ...] = Field(default=(), max_length=11)
    avoid: tuple[PersonalAvoidEffect, ...] = Field(default=(), max_length=8)
    user_overrides: tuple[str, ...] = Field(default=(), max_length=40)
    sample_count: int = Field(default=0, ge=0)
    anomaly_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _values_are_consistent(self) -> Self:
        _check_targets(self.targets)
        if len(self.targets) > len(PERSONAL_TARGET_FIELDS):
            raise ValueError("targets contains too many fields.")
        if len(self.scene_targets) > 9:
            raise ValueError("sceneTargets supports at most 9 scenes.")
        for targets in self.scene_targets.values():
            _check_targets(targets)
        unknown_stability = sorted(set(self.stability) - set(PERSONAL_STABILITY_FIELDS))
        if unknown_stability:
            raise ValueError(
                "unknown personal style stability fields: " + ", ".join(unknown_stability)
            )
        if any(not 0.0 <= value <= 1.0 for value in self.stability.values()):
            raise ValueError("stability values must be between 0 and 1.")
        _check_unique(self.protected, "protected")
        _check_unique(self.avoid, "avoid")
        _check_unique(self.user_overrides, "userOverrides")
        if self.anomaly_count > self.sample_count:
            raise ValueError("anomalyCount must not exceed sampleCount.")
        return self


class PersonalStyleProfile(StyleProfile):
    """A personal style snapshot that can enter the V6.1 style pipeline."""

    kind: Literal[StyleKind.PERSONAL] = StyleKind.PERSONAL
    personal: PersonalStyleHints

    @model_validator(mode="after")
    def _personal_id_namespace(self) -> Self:
        if not self.id.startswith("personal_"):
            raise ValueError("personal style ids must start with 'personal_'.")
        return self


class PersonalStyleDefinition(_PersonalModel):
    """Editable metadata kept beside the immutable profile snapshot."""

    schema_version: Literal["personal-definition/1"] = "personal-definition/1"
    user_overrides: dict[str, Any] = Field(default_factory=dict)
    note: Text | None = None


class PersonalStyleReference(_PersonalModel):
    id: UUID
    image_id: UUID | None = None
    image_sha256: str = Field(pattern=SHA256_PATTERN)
    original_name: str = Field(min_length=1, max_length=255)
    status: PersonalStyleReferenceStatus = PersonalStyleReferenceStatus.ACTIVE
    consent_scope: PersonalStyleConsentScope = PersonalStyleConsentScope.ANALYSIS_ONLY
    consent_at: datetime
    added_at: datetime
    analysis_id: UUID | None = None


class PersonalStyleItem(_PersonalModel):
    id: PersonalStyleId
    name: ShortName
    description: Text
    source: PersonalStyleSource
    status: PersonalStyleStatus
    version: StyleProfileVersion
    favorite: bool
    confidence: float = Field(ge=0.0, le=1.0)
    sample_count: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    updated_at: datetime


class PersonalStyleListResponse(_PersonalModel):
    styles: tuple[PersonalStyleItem, ...] = Field(default=(), max_length=64)


class PersonalStyleDetailResponse(_PersonalModel):
    style: PersonalStyleProfile
    definition: PersonalStyleDefinition
    status: PersonalStyleStatus
    source: PersonalStyleSource
    favorite: bool
    references: tuple[PersonalStyleReference, ...] = Field(default=(), max_length=20)
    created_at: datetime
    updated_at: datetime


class PersonalStyleCreateRequest(_PersonalModel):
    name: ShortName
    description: Text
    source: PersonalStyleSource = PersonalStyleSource.PHOTOS
    suitable_scenes: tuple[SceneLabel, ...] = Field(default=(), max_length=9)
    targets: dict[str, BoundedTarget] = Field(default_factory=dict)
    avoid: tuple[PersonalAvoidEffect, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _request_is_consistent(self) -> Self:
        if self.source not in {PersonalStyleSource.PHOTOS, PersonalStyleSource.CUSTOM}:
            raise ValueError("a personal style is created from photos or a custom description.")
        _check_targets(self.targets)
        _check_unique(self.suitable_scenes, "suitableScenes")
        _check_unique(self.avoid, "avoid")
        return self


class PersonalStyleUpdateRequest(_PersonalModel):
    name: ShortName | None = None
    description: Text | None = None
    suitable_scenes: tuple[SceneLabel, ...] | None = Field(default=None, max_length=9)
    targets: dict[str, BoundedTarget] | None = None
    avoid: tuple[PersonalAvoidEffect, ...] | None = Field(default=None, max_length=8)
    note: Text | None = None

    @model_validator(mode="after")
    def _request_changes_something(self) -> Self:
        if all(
            value is None
            for value in (
                self.name,
                self.description,
                self.suitable_scenes,
                self.targets,
                self.avoid,
                self.note,
            )
        ):
            raise ValueError("at least one editable field must be provided.")
        if self.targets is not None:
            _check_targets(self.targets)
        if self.suitable_scenes is not None:
            _check_unique(self.suitable_scenes, "suitableScenes")
        if self.avoid is not None:
            _check_unique(self.avoid, "avoid")
        return self


class PersonalStyleStatusRequest(_PersonalModel):
    status: PersonalStyleStatus


class PersonalStyleStatusResponse(_PersonalModel):
    style_id: PersonalStyleId
    status: PersonalStyleStatus


class PersonalStyleFavoriteResponse(_PersonalModel):
    style_id: PersonalStyleId
    favorite: bool


class PersonalStyleReferenceAddRequest(_PersonalModel):
    image_ids: tuple[UUID, ...] = Field(min_length=1, max_length=20)
    consent: bool

    @model_validator(mode="after")
    def _consent_is_explicit(self) -> Self:
        if not self.consent:
            raise ValueError("consent must be true before reference photos are analysed.")
        _check_unique(self.image_ids, "imageIds")
        return self


class PersonalStyleReferenceListResponse(_PersonalModel):
    style_id: PersonalStyleId
    references: tuple[PersonalStyleReference, ...] = Field(default=(), max_length=64)


class PersonalStyleVersionSummary(_PersonalModel):
    version: StyleProfileVersion
    change_source: PersonalStyleChangeSource
    change_note: Text | None = None
    created_at: datetime


class PersonalStyleVersionListResponse(_PersonalModel):
    style_id: PersonalStyleId
    versions: tuple[PersonalStyleVersionSummary, ...] = Field(default=(), max_length=64)


class PersonalStyleVersionDetailResponse(_PersonalModel):
    style_id: PersonalStyleId
    version: StyleProfileVersion
    profile: PersonalStyleProfile
    definition: PersonalStyleDefinition
    change_source: PersonalStyleChangeSource
    change_note: Text | None = None
    created_at: datetime


class PersonalStyleFieldChange(_PersonalModel):
    path: str = Field(min_length=1, max_length=200)
    before: Any = None
    after: Any = None


class PersonalStyleCompareResponse(_PersonalModel):
    style_id: PersonalStyleId
    from_version: StyleProfileVersion
    to_version: StyleProfileVersion
    changes: tuple[PersonalStyleFieldChange, ...] = Field(default=(), max_length=100)


def build_default_personal_profile(
    *,
    style_id: str,
    name: str,
    description: str,
    source: PersonalStyleSource,
    suitable_scenes: tuple[SceneLabel, ...] = (),
    targets: dict[str, float] | None = None,
    avoid: tuple[PersonalAvoidEffect, ...] = (),
) -> PersonalStyleProfile:
    """Create an empty draft profile that later analysis or editing fills in."""

    scenes = suitable_scenes or (SceneLabel.OTHER,)
    return PersonalStyleProfile(
        id=style_id,
        version="1.0",
        name=name,
        description=description,
        philosophy="由用户主动创建的个人视觉风格草稿，等待参考照片分析或进一步编辑。",
        color=StyleColorTraits(
            tendency="待分析",
            relationships="待分析",
            saturation="待分析",
        ),
        light=StyleLightTraits(
            contrast="待分析",
            shadows="待分析",
            highlights="待分析",
            expression="待分析",
        ),
        composition=StyleCompositionTraits(
            space="待分析",
            geometry="待分析",
            negative_space="待分析",
            subject_relation="待分析",
        ),
        texture=StyleTextureTraits(
            grain="待分析",
            sharpness="待分析",
            detail="待分析",
        ),
        scene_fit=StyleSceneFit(
            suitable=scenes,
            suitable_notes="待分析。",
            unsuitable_notes="待分析。",
        ),
        post_strategy="待分析。",
        capture_techniques="用户提供的参考照片或个人描述。",
        preserve_notes="参考照片仅用于分析，不用于模型训练。",
        sources=(
            StyleSource(
                title="用户创建的个人风格",
                license="用户私有，不用于模型训练",
            ),
        ),
        engine_style="natural",
        default_strength=0.45,
        enabled=False,
        personal=PersonalStyleHints(
            source=source,
            targets=targets or {},
            avoid=avoid,
        ),
    )


__all__ = [
    "PERSONAL_STABILITY_FIELDS",
    "PERSONAL_STYLE_ID_PATTERN",
    "PERSONAL_TARGET_FIELDS",
    "BoundedTarget",
    "PersonalAvoidEffect",
    "PersonalStyleChangeSource",
    "PersonalStyleCompareResponse",
    "PersonalStyleConsentScope",
    "PersonalStyleCreateRequest",
    "PersonalStyleDefinition",
    "PersonalStyleDetailResponse",
    "PersonalStyleFavoriteResponse",
    "PersonalStyleFieldChange",
    "PersonalStyleHints",
    "PersonalStyleId",
    "PersonalStyleItem",
    "PersonalStyleListResponse",
    "PersonalStyleProfile",
    "PersonalStyleReference",
    "PersonalStyleReferenceAddRequest",
    "PersonalStyleReferenceListResponse",
    "PersonalStyleReferenceStatus",
    "PersonalStyleSource",
    "PersonalStyleStatus",
    "PersonalStyleStatusRequest",
    "PersonalStyleStatusResponse",
    "PersonalStyleUpdateRequest",
    "PersonalStyleVersionDetailResponse",
    "PersonalStyleVersionListResponse",
    "PersonalStyleVersionSummary",
    "build_default_personal_profile",
]
