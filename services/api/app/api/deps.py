from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.errors import AppError
from app.core.identity import OwnerScope
from app.imaging.semantic_models import SemanticModelRegistry
from app.photographer.service import PhotographerService
from app.services.analysis_task_service import AnalysisTaskService
from app.services.custom_style_service import CustomStyleService
from app.services.deletion_service import DeletionService
from app.services.export_jobs import ExportJobManager
from app.services.export_service import ExportService
from app.services.image_service import ImageService
from app.services.personal_style_analysis_service import PersonalStyleAnalysisService
from app.services.personal_style_service import PersonalStyleService
from app.services.provider_settings_service import ProviderSettingsService
from app.services.render_service import RenderService
from app.services.semantic_mask_service import SemanticMaskService
from app.services.session_service import SessionService
from app.services.style_fusion_service import StyleFusionService
from app.services.style_library_service import StyleLibraryService
from app.services.style_matching_service import StyleMatchingService


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return settings


def get_semantic_registry(request: Request) -> SemanticModelRegistry:
    registry = getattr(request.app.state, "semantic_registry", None)
    if not isinstance(registry, SemanticModelRegistry):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return registry


def get_semantic_mask_service(request: Request) -> SemanticMaskService:
    service = getattr(request.app.state, "semantic_mask_service", None)
    if not isinstance(service, SemanticMaskService):
        raise AppError(503, "semantic_mask_unavailable", "Semantic masks are not available.")
    return service


def get_owner_scope(request: Request) -> OwnerScope:
    scope = getattr(request.app.state, "owner_scope", None)
    if not isinstance(scope, OwnerScope):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return scope


def get_custom_style_service(request: Request) -> CustomStyleService:
    service = getattr(request.app.state, "custom_style_service", None)
    if not isinstance(service, CustomStyleService):
        raise AppError(
            503,
            "style_authoring_unavailable",
            "The custom style service is not available.",
        )
    return service


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


def get_export_job_manager(request: Request) -> ExportJobManager:
    manager = getattr(request.app.state, "export_jobs", None)
    if not isinstance(manager, ExportJobManager):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return manager


def get_style_library_service(request: Request) -> StyleLibraryService:
    service = getattr(request.app.state, "style_library_service", None)
    if not isinstance(service, StyleLibraryService):
        raise AppError(503, "style_library_unavailable", "The style library is not available.")
    return service


def get_personal_style_service(request: Request) -> PersonalStyleService:
    service = getattr(request.app.state, "personal_style_service", None)
    if not isinstance(service, PersonalStyleService):
        raise AppError(
            503,
            "personal_style_unavailable",
            "The personal style service is not available.",
        )
    return service


def get_personal_style_analysis_service(request: Request) -> PersonalStyleAnalysisService:
    service = getattr(request.app.state, "personal_style_analysis_service", None)
    if not isinstance(service, PersonalStyleAnalysisService):
        raise AppError(
            503,
            "personal_style_unavailable",
            "The personal style analysis service is not available.",
        )
    return service


def get_style_matching_service(request: Request) -> StyleMatchingService:
    service = getattr(request.app.state, "style_matching_service", None)
    if not isinstance(service, StyleMatchingService):
        raise AppError(503, "style_matching_unavailable", "Style fit analysis is not available.")
    return service


def get_style_fusion_service(request: Request) -> StyleFusionService:
    service = getattr(request.app.state, "style_fusion_service", None)
    if not isinstance(service, StyleFusionService):
        raise AppError(503, "personal_style_unavailable", "The fusion service is not available.")
    return service


def get_photographer_service(request: Request) -> PhotographerService:
    service = getattr(request.app.state, "photographer_service", None)
    if not isinstance(service, PhotographerService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service


def get_deletion_service(request: Request) -> DeletionService:
    service = getattr(request.app.state, "deletion_service", None)
    if not isinstance(service, DeletionService):
        raise AppError(503, "service_unavailable", "The service is not ready.")
    return service
