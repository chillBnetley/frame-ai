from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings, get_image_service
from app.core.config import Settings
from app.models.schemas import HealthResponse, StorageHealth
from app.services.image_service import ImageService

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Annotated[Settings, Depends(get_app_settings)],
    service: Annotated[ImageService, Depends(get_image_service)],
) -> HealthResponse:
    storage = service.storage_status()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        storage=StorageHealth(ok=storage.ok, writable=storage.writable),
    )
