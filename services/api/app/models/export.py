from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.models.recipe import ColorSpace
from app.models.schemas import CamelModel

ExportFormat = Literal["jpeg", "png", "tiff"]
ExportBitDepth = Literal[8, 16]

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
    bit_depth: ExportBitDepth = 8
    color_space: ColorSpace = "sRGB"

    @model_validator(mode="after")
    def _reject_sixteen_bit_jpeg(self) -> ExportRequest:
        # Rejected during request validation so an async job never starts with
        # a combination the encoder cannot represent.
        if self.bit_depth == 16 and self.format == "jpeg":
            raise ValueError("JPEG does not support 16-bit output")
        return self


ExportJobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ExportJobRequest(ExportRequest):
    session_id: UUID


class ExportJobError(CamelModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ExportJobResponse(CamelModel):
    job_id: str
    status: ExportJobStatus
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    bit_depth: ExportBitDepth = 8
    warnings: list[str] = Field(default_factory=list)
    error: ExportJobError | None = None
    created_at: datetime
    updated_at: datetime
