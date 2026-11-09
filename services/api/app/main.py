from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.factory import ProviderBundle
from app.api.errors import register_exception_handlers
from app.api.routes import analysis, config, exports, health, images, previews, sessions
from app.api.routes import personal_styles as personal_style_routes
from app.api.routes import photographer as photographer_routes
from app.api.routes import settings as settings_routes
from app.api.routes import styles as style_routes
from app.core.auth import ApiTokenService
from app.core.config import Settings, get_settings
from app.core.identity import LOCAL_OWNER_ID, OwnerScope
from app.core.logging import configure_logging
from app.core.middleware import (
    ApiAuthMiddleware,
    CorsPreflightGuardMiddleware,
    LocalOriginGuardMiddleware,
    RequestContextMiddleware,
)
from app.core.upload_limit import RequestBodyLimitMiddleware
from app.imaging.local_masks import configure_mask_cache, configure_semantic_mattes
from app.imaging.semantic_models import SemanticModelRegistry
from app.photographer.service import PhotographerService
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.repositories.personal_style_repo import SqlitePersonalStyleRepository
from app.repositories.photographer_repo import (
    SqlitePhotographerFeedbackRepository,
    SqlitePhotographerPlanRepository,
)
from app.repositories.style_repo import SqliteStyleProfileRepository
from app.services.analysis_task_service import AnalysisTaskService
from app.services.deletion_service import DeletionService
from app.services.export_jobs import ExportJobManager
from app.services.export_service import ExportService
from app.services.image_service import ImageService
from app.services.personal_style_analysis_service import PersonalStyleAnalysisService
from app.services.personal_style_service import PersonalStyleService
from app.services.preview_store import PreviewStore
from app.services.provider_settings_service import ProviderSettingsService
from app.services.render_service import RenderService
from app.services.semantic_mask_service import SemanticMaskService
from app.services.session_service import SessionService
from app.services.style_library_service import StyleLibraryService
from app.services.style_matching_service import StyleMatchingService
from app.styles.library import seed_style_library

logger = logging.getLogger("frame_ai.main")
API_PREFIX = "/api/v1"
ALLOWED_CORS_METHODS = ["GET", "POST", "DELETE", "OPTIONS"]


async def _cleanup_previews(store: PreviewStore, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(store.cleanup)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    configure_mask_cache(resolved_settings.mask_cache_mb * 1024 * 1024)
    token_service = ApiTokenService(resolved_settings.api_token_path)
    semantic_registry = SemanticModelRegistry(resolved_settings.data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if resolved_settings.api_auth_enabled:
            token_service.ensure_token()
        service = ImageService(resolved_settings)
        service.ensure_ready()
        service.scan_consistency()
        style_profiles = SqliteStyleProfileRepository(resolved_settings.database_path)
        seeded = seed_style_library(style_profiles)
        if seeded.created:
            logger.info("style_library_seeded created=%s", len(seeded.created))
        configure_semantic_mattes(resolved_settings.mattes_dir)
        semantic_mask_service = SemanticMaskService(
            resolved_settings,
            service,
            semantic_registry,
        )
        app.state.semantic_mask_service = semantic_mask_service
        session_service = SessionService(resolved_settings, service)
        render_service = RenderService(resolved_settings, service, session_service)
        render_service.previews.ensure_ready()
        await asyncio.to_thread(render_service.previews.cleanup)
        app.state.settings = resolved_settings
        app.state.image_service = service
        app.state.session_service = session_service
        app.state.render_service = render_service
        export_service = ExportService(
            resolved_settings,
            service,
            session_service,
        )
        app.state.export_service = export_service
        export_jobs = ExportJobManager(
            export_service,
            directory=resolved_settings.export_dir,
            ttl_seconds=resolved_settings.export_job_ttl_seconds,
            queue_max=resolved_settings.export_queue_max,
            max_workers=resolved_settings.export_max_concurrency,
        )
        export_jobs.ensure_ready()
        app.state.export_jobs = export_jobs
        providers = ProviderSettingsService(resolved_settings)
        analysis_tasks = AnalysisTaskService(
            resolved_settings,
            service,
            providers.bundle,
            SqliteAnalysisRepository(resolved_settings.database_path),
        )
        plan_repository = SqlitePhotographerPlanRepository(resolved_settings.database_path)
        photographer_service = PhotographerService(
            providers.bundle.planner,
            max_concurrency=resolved_settings.photographer_max_concurrency,
            analysis=analysis_tasks,
            sessions=session_service,
            images=service,
            plans=plan_repository,
            feedback=SqlitePhotographerFeedbackRepository(resolved_settings.database_path),
            styles=style_profiles,
            semantic_masks=semantic_mask_service,
        )
        style_library_service = StyleLibraryService(
            style_profiles,
            plans=plan_repository,
            images=service,
            analysis=analysis_tasks,
        )
        style_matching_service = StyleMatchingService(
            style_profiles,
            images=service,
            analysis=analysis_tasks,
        )
        personal_styles = SqlitePersonalStyleRepository(resolved_settings.database_path)
        personal_style_service = PersonalStyleService(
            personal_styles,
            images=service,
            analysis=analysis_tasks,
        )
        personal_style_analysis_service = PersonalStyleAnalysisService(
            personal_styles,
            analysis=analysis_tasks,
        )

        def on_providers_changed(bundle: ProviderBundle) -> None:
            analysis_tasks.update_providers(bundle)
            photographer_service.update_planner(bundle.planner)

        providers.set_on_change(on_providers_changed)
        app.state.provider_settings_service = providers
        analysis_tasks.recover()
        app.state.analysis_task_service = analysis_tasks
        app.state.deletion_service = DeletionService(
            resolved_settings,
            images=service,
            analysis=analysis_tasks,
            exports=export_service,
            previews=render_service.previews,
            proxy_cache=render_service.proxy_cache,
            export_jobs=export_jobs,
        )
        app.state.photographer_service = photographer_service
        app.state.style_library_service = style_library_service
        app.state.style_matching_service = style_matching_service
        app.state.personal_style_service = personal_style_service
        app.state.personal_style_analysis_service = personal_style_analysis_service
        cleanup_task = asyncio.create_task(
            _cleanup_previews(
                render_service.previews,
                resolved_settings.preview_cleanup_interval_seconds,
            )
        )
        try:
            yield
        finally:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
            export_jobs.shutdown()
            await asyncio.to_thread(analysis_tasks.shutdown)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.api_token_service = token_service
    app.state.semantic_registry = semantic_registry
    app.state.owner_scope = OwnerScope(owner_id=LOCAL_OWNER_ID)

    register_exception_handlers(app)

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_upload_bytes=resolved_settings.max_upload_bytes,
        max_json_body_bytes=resolved_settings.max_json_body_bytes,
        allowance_bytes=resolved_settings.content_length_allowance,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origin_list,
        allow_credentials=False,
        allow_methods=ALLOWED_CORS_METHODS,
        allow_headers=[
            "Content-Type",
            "X-Request-ID",
            "X-Render-Seq",
            "Idempotency-Key",
            "X-FRAME-Token",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-Export-Width",
            "X-Export-Height",
            "X-Export-Bit-Depth",
            "X-Export-Warning",
            "Content-Disposition",
        ],
        max_age=600,
    )
    app.add_middleware(
        CorsPreflightGuardMiddleware,
        allowed_origins=resolved_settings.allowed_origin_list,
        allowed_methods=ALLOWED_CORS_METHODS,
    )
    app.add_middleware(
        ApiAuthMiddleware,
        enabled=resolved_settings.api_auth_enabled,
        tokens=token_service,
        rate_limits=resolved_settings.api_rate_limits,
    )
    app.add_middleware(
        LocalOriginGuardMiddleware,
        allowed_origins=resolved_settings.allowed_origin_list,
        allowed_hosts=resolved_settings.allowed_host_list,
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(config.router, prefix=API_PREFIX)
    app.include_router(settings_routes.router, prefix=API_PREFIX)
    app.include_router(images.router, prefix=API_PREFIX)
    app.include_router(analysis.router, prefix=API_PREFIX)
    app.include_router(sessions.router, prefix=API_PREFIX)
    app.include_router(exports.router, prefix=API_PREFIX)
    app.include_router(previews.router, prefix=API_PREFIX)
    app.include_router(photographer_routes.router, prefix=API_PREFIX)
    app.include_router(style_routes.router, prefix=API_PREFIX)
    app.include_router(personal_style_routes.router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": resolved_settings.app_name,
            "version": resolved_settings.app_version,
            "health": f"{API_PREFIX}/health",
            "docs": "/docs",
        }

    return app


app = create_app()
