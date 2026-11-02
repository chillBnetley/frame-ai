from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.imaging.decoder import SUPPORTED_MIME_TYPES
from app.models.schemas import RuntimeConfigResponse

router = APIRouter(tags=["system"])


@router.get("/config", response_model=RuntimeConfigResponse)
def runtime_config(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> RuntimeConfigResponse:
    return RuntimeConfigResponse(
        max_upload_bytes=settings.max_upload_bytes,
        max_image_pixels=settings.max_image_pixels,
        allowed_mime_types=list(SUPPORTED_MIME_TYPES),
    )
