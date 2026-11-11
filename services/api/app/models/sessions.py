from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.models.conversion import ConversionMode
from app.models.generative import GenerativeBaseMode, GenerativeTaskType
from app.models.recipe import EditRecipe
from app.models.schemas import CamelModel

RevisionSource = Literal["initial", "user", "ai", "reset"]
WritableRevisionSource = Literal["user", "ai"]
REVISION_INSTRUCTION_SUMMARY_CHARS = 80


class RevisionGenerativeSummary(CamelModel):
    """Provenance of a revision created by accepting a generative result."""

    task_type: GenerativeTaskType
    instruction_summary: str
    provider: str
    model: str
    is_mock: bool
    base_mode: GenerativeBaseMode


class RevisionCreationSummary(CamelModel):
    plan_id: UUID | None = None
    style_id: str | None = None
    style_version: str | None = None
    conversion_mode: ConversionMode | None = None
    style_strength: float | None = None
    render_key: str | None = None


class CreateSessionRequest(CamelModel):
    image_id: UUID


class CreateRevisionRequest(CamelModel):
    recipe: EditRecipe
    parent_revision_id: UUID
    source: WritableRevisionSource = "user"


class UndoRequest(CamelModel):
    revision_id: UUID | None = None


class ActivateRevisionRequest(CamelModel):
    revision_id: UUID


class RevisionView(CamelModel):
    id: UUID
    revision_no: int
    parent_id: UUID | None
    source: RevisionSource
    recipe: EditRecipe
    creation: RevisionCreationSummary | None = None
    base_generated_asset_id: UUID | None = None
    # Dimensions of the base asset, not of the downscaled preview.
    base_width: int
    base_height: int
    generative_task_id: UUID | None = None
    generative: RevisionGenerativeSummary | None = None
    created_at: datetime


class SessionState(CamelModel):
    session_id: UUID
    image_id: UUID
    active_revision_id: UUID
    head_revision_id: UUID
    can_undo: bool
    can_redo: bool
    revision: RevisionView


class RevisionSummary(CamelModel):
    id: UUID
    revision_no: int
    parent_id: UUID | None
    source: RevisionSource
    recipe_hash: str
    creation: RevisionCreationSummary | None = None
    base_generated_asset_id: UUID | None = None
    generative_task_id: UUID | None = None
    generative: RevisionGenerativeSummary | None = None
    created_at: datetime


class RevisionListResponse(CamelModel):
    items: list[RevisionSummary]
    next_cursor: str | None = None
