from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class StorageHealth(CamelModel):
    ok: bool
    writable: bool


class HealthResponse(CamelModel):
    status: Literal["ok"]
    service: str
    version: str
    storage: StorageHealth


class RuntimeConfigResponse(CamelModel):
    max_upload_bytes: int
    max_image_pixels: int
    allowed_mime_types: list[str]


class UploadImageResponse(CamelModel):
    image_id: UUID
    original_name: str
    width: int
    height: int
    exif_orientation: int
    mime_type: str
    bytes: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_content(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}
