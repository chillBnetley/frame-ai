from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import analysis, config, health, images, previews, sessions
from app.api.routes import settings as settings_routes
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import (
    CorsPreflightGuardMiddleware,
    LocalOriginGuardMiddleware,
    RequestContextMiddleware,
)
from app.core.upload_limit import RequestBodyLimitMiddleware
from app.imaging.local_masks import configure_mask_cache
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.services.analysis_task_service import AnalysisTaskService
from app.services.export_service import ExportService
from app.services.image_service import ImageService
from app.services.preview_store import PreviewStore
from app.services.provider_settings_service import ProviderSettingsService
from app.services.render_service import RenderService
from app.services.session_service import SessionService

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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        service = ImageService(resolved_settings)
        service.ensure_ready()
        service.scan_consistency()
        session_service = SessionService(resolved_settings, service)
        render_service = RenderService(resolved_settings, service, session_service)
        render_service.previews.ensure_ready()
        await asyncio.to_thread(render_service.previews.cleanup)
        app.state.settings = resolved_settings
        app.state.image_service = service
        app.state.session_service = session_service
        app.state.render_service = render_service
        app.state.export_service = ExportService(
            resolved_settings,
            service,
            session_service,
        )
        providers = ProviderSettingsService(resolved_settings)
        analysis_tasks = AnalysisTaskService(
            resolved_settings,
            service,
            providers.bundle,
            SqliteAnalysisRepository(resolved_settings.database_path),
        )
        providers.set_on_change(analysis_tasks.update_providers)
        app.state.provider_settings_service = providers
        analysis_tasks.recover()
        app.state.analysis_task_service = analysis_tasks
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
            await asyncio.to_thread(analysis_tasks.shutdown)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

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
        allow_headers=["Content-Type", "X-Request-ID", "X-Render-Seq", "Idempotency-Key"],
        expose_headers=[
            "X-Request-ID",
            "X-Export-Width",
            "X-Export-Height",
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
    app.include_router(previews.router, prefix=API_PREFIX)

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
