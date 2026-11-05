from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.models.recipe import ColorSpace
from app.models.schemas import CamelModel

ExportFormat = Literal["jpeg", "png"]

EXPORT_MAX_EDGE_MIN = 64
EXPORT_MAX_EDGE_LIMIT = 100_000


class ExportRequest(CamelModel):
    revision_id: UUID
    format: ExportFormat
    quality: int | None = Field(default=None, ge=1, le=100)
    max_edge: int | None = Field(
        default=None,
        ge=EXPORT_MAX_EDGE_MIN,
        le=EXPORT_MAX_EDGE_LIMIT,
    )
    color_space: ColorSpace = "sRGB"
