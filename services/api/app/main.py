from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import config, health, images, previews, sessions
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import CorsPreflightGuardMiddleware, RequestContextMiddleware
from app.core.upload_limit import UploadSizeLimitMiddleware
from app.services.analysis_service import AnalysisService
from app.services.image_service import ImageService
from app.services.preview_store import PreviewStore
from app.services.render_service import RenderService
from app.services.session_service import SessionService

API_PREFIX = "/api/v1"


async def _cleanup_previews(store: PreviewStore, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(store.cleanup)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

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
        app.state.analysis_service = AnalysisService(resolved_settings, service)
        app.state.session_service = session_service
        app.state.render_service = render_service
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

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

    register_exception_handlers(app)

    app.add_middleware(
        UploadSizeLimitMiddleware,
        max_upload_bytes=resolved_settings.max_upload_bytes,
        allowance_bytes=resolved_settings.content_length_allowance,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(
        CorsPreflightGuardMiddleware,
        allowed_origins=resolved_settings.allowed_origin_list,
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(config.router, prefix=API_PREFIX)
    app.include_router(images.router, prefix=API_PREFIX)
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
