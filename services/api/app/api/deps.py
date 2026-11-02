from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.errors import AppError
from app.services.image_service import ImageService


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return settings


def get_image_service(request: Request) -> ImageService:
    service = getattr(request.app.state, "image_service", None)
    if not isinstance(service, ImageService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service
