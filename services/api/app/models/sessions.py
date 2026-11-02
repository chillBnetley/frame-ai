from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.models.recipe import EditRecipe
from app.models.schemas import CamelModel

RevisionSource = Literal["initial", "user", "ai", "reset"]
WritableRevisionSource = Literal["user", "ai"]


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
    created_at: datetime


class RevisionListResponse(CamelModel):
    items: list[RevisionSummary]
    next_cursor: str | None = None
