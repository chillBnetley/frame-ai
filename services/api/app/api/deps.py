from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.errors import AppError
from app.services.analysis_service import AnalysisService
from app.services.image_service import ImageService
from app.services.session_service import SessionService


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


def get_analysis_service(request: Request) -> AnalysisService:
    service = getattr(request.app.state, "analysis_service", None)
    if not isinstance(service, AnalysisService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if not isinstance(service, SessionService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service
