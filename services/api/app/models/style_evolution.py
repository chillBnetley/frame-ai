from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.ai.contracts import Text
from app.models.personal_style import (
    PersonalStyleDefinition,
    PersonalStyleFieldChange,
    PersonalStyleId,
    PersonalStyleProfile,
)
from app.models.style_profile import StyleProfileVersion

EVOLUTION_SCHEMA_VERSION = "style-evolution/1"


class StyleFeedbackType(StrEnum):
    LIKE_RESULT = "like_result"
    DISLIKE_RESULT = "dislike_result"
    COLOR_TOO_STRONG = "color_too_strong"
    CONTRAST_TOO_STRONG = "contrast_too_strong"
    SHADOWS_TOO_DARK = "shadows_too_dark"
    SKIN_UNNATURAL = "skin_unnatural"
    STYLE_SUBTLE = "style_subtle"
    STYLE_OVERDONE = "style_overdone"
    KEEP_ORIGINAL = "keep_original"


class StyleFeedbackScope(StrEnum):
    SINGLE_EDIT = "single_edit"
    PROFILE = "profile"


class StyleEvolutionStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"


FEEDBACK_TYPE_LABELS: dict[StyleFeedbackType, str] = {
    StyleFeedbackType.LIKE_RESULT: "喜欢当前结果",
    StyleFeedbackType.DISLIKE_RESULT: "不喜欢当前结果",
    StyleFeedbackType.COLOR_TOO_STRONG: "色彩太浓",
    StyleFeedbackType.CONTRAST_TOO_STRONG: "对比度太强",
    StyleFeedbackType.SHADOWS_TOO_DARK: "暗部太黑",
    StyleFeedbackType.SKIN_UNNATURAL: "肤色不自然",
    StyleFeedbackType.STYLE_SUBTLE: "风格不明显",
    StyleFeedbackType.STYLE_OVERDONE: "风格过度",
    StyleFeedbackType.KEEP_ORIGINAL: "希望保留更多原始质感",
}


class _EvolutionModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class StyleFeedbackRecord(_EvolutionModel):
    id: UUID
    style_id: PersonalStyleId
    style_version: StyleProfileVersion
    feedback_type: StyleFeedbackType
    note: Text | None = None
    scope: StyleFeedbackScope
    applied_version: StyleProfileVersion | None = None
    created_at: datetime


class StyleFeedbackCreateRequest(_EvolutionModel):
    feedback_type: StyleFeedbackType
    note: Text | None = None
    scope: StyleFeedbackScope = StyleFeedbackScope.SINGLE_EDIT
    style_version: StyleProfileVersion | None = None


class StyleFeedbackListResponse(_EvolutionModel):
    style_id: PersonalStyleId
    feedbacks: tuple[StyleFeedbackRecord, ...] = Field(default=(), max_length=200)


class StyleEvolutionRecord(_EvolutionModel):
    """An immutable proposal snapshot plus its confirmation outcome.

    The candidate profile is frozen at preview time so the user confirms exactly
    what was shown; ``new_version`` and ``confirmed_at`` stay empty until the
    user actively applies the proposal.
    """

    schema_version: Literal["style-evolution/1"] = "style-evolution/1"
    id: UUID
    style_id: PersonalStyleId
    base_version: StyleProfileVersion
    new_version: StyleProfileVersion | None = None
    feedback_ids: tuple[UUID, ...] = Field(default=(), max_length=200)
    reason: Text
    summary: Text
    candidate: PersonalStyleProfile
    definition: PersonalStyleDefinition
    status: StyleEvolutionStatus
    created_at: datetime
    confirmed_at: datetime | None = None


class StyleEvolutionPreviewRequest(_EvolutionModel):
    feedback_ids: tuple[UUID, ...] | None = Field(default=None, max_length=200)
    note: Text | None = None

    @model_validator(mode="after")
    def _feedback_ids_unique(self) -> Self:
        if self.feedback_ids is not None and len(set(self.feedback_ids)) != len(self.feedback_ids):
            raise ValueError("feedbackIds must be unique.")
        return self


class StyleEvolutionAdjustment(_EvolutionModel):
    """One bounded, human-readable change produced by the evolution engine."""

    field: str = Field(min_length=1, max_length=120)
    label: Text
    before: Any = None
    after: Any = None


class StyleEvolutionPreviewResponse(_EvolutionModel):
    evolution: StyleEvolutionRecord
    changes: tuple[PersonalStyleFieldChange, ...] = Field(default=(), max_length=100)
    adjustments: tuple[StyleEvolutionAdjustment, ...] = Field(default=(), max_length=40)
    limitations: tuple[Text, ...] = Field(default=(), max_length=12)
    feedback_count: int = Field(ge=0)


class StyleEvolutionApplyRequest(_EvolutionModel):
    confirm: bool
    note: Text | None = None


class StyleEvolutionListResponse(_EvolutionModel):
    style_id: PersonalStyleId
    evolutions: tuple[StyleEvolutionRecord, ...] = Field(default=(), max_length=64)


__all__ = [
    "EVOLUTION_SCHEMA_VERSION",
    "FEEDBACK_TYPE_LABELS",
    "StyleEvolutionAdjustment",
    "StyleEvolutionApplyRequest",
    "StyleEvolutionListResponse",
    "StyleEvolutionPreviewRequest",
    "StyleEvolutionPreviewResponse",
    "StyleEvolutionRecord",
    "StyleEvolutionStatus",
    "StyleFeedbackCreateRequest",
    "StyleFeedbackListResponse",
    "StyleFeedbackRecord",
    "StyleFeedbackScope",
    "StyleFeedbackType",
]
