from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.errors import AppError
from app.photographer.service import PhotographerService
from app.services.analysis_task_service import AnalysisTaskService
from app.services.export_service import ExportService
from app.services.image_service import ImageService
from app.services.provider_settings_service import ProviderSettingsService
from app.services.render_service import RenderService
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


def get_analysis_task_service(request: Request) -> AnalysisTaskService:
    service = getattr(request.app.state, "analysis_task_service", None)
    if not isinstance(service, AnalysisTaskService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service


def get_provider_settings_service(request: Request) -> ProviderSettingsService:
    service = getattr(request.app.state, "provider_settings_service", None)
    if not isinstance(service, ProviderSettingsService):
        raise AppError(503, "provider_settings_unavailable", "The service is not ready.")
    return service


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if not isinstance(service, SessionService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service


def get_render_service(request: Request) -> RenderService:
    service = getattr(request.app.state, "render_service", None)
    if not isinstance(service, RenderService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service


def get_export_service(request: Request) -> ExportService:
    service = getattr(request.app.state, "export_service", None)
    if not isinstance(service, ExportService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service


def get_photographer_service(request: Request) -> PhotographerService:
    service = getattr(request.app.state, "photographer_service", None)
    if not isinstance(service, PhotographerService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service
