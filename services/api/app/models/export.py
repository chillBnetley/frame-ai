from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.models.schemas import CamelModel

ExportFormat = Literal["jpeg", "png"]


class ExportRequest(CamelModel):
    revision_id: UUID
    format: ExportFormat
    quality: int | None = Field(default=None, ge=1, le=100)
