from __future__ import annotations

import threading
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.loader import load_proxy
from app.imaging.output import JPEG_QUALITY, encode_image
from app.imaging.params_map import DRAFT_MAX_EDGE, ENGINE_VERSION
from app.imaging.pipeline import render as render_image
from app.models.recipe import render_key
from app.models.render import RenderRequest, RenderTier
from app.services.image_service import ImageService
from app.services.preview_store import PreviewStore
from app.services.session_service import SessionService

PREVIEW_URL_PREFIX = "/api/v1/previews"


@dataclass(frozen=True)
class RenderResult:
    preview_id: str
    width: int
    height: int
    quality: RenderTier
    cache_hit: bool

    @property
    def preview_url(self) -> str:
        return f"{PREVIEW_URL_PREFIX}/{self.preview_id}"


class RenderService:
    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        sessions: SessionService,
        *,
        previews: PreviewStore | None = None,
        max_concurrent_renders: int = 2,
    ) -> None:
        self.settings = settings
        self.images = images
        self.sessions = sessions
        self.previews = previews or PreviewStore(
            settings.preview_dir,
            ttl_seconds=settings.preview_ttl_seconds,
        )
        self._slots = threading.BoundedSemaphore(max_concurrent_renders)

    def render(self, session_id: str, request: RenderRequest) -> RenderResult:
        state = self.sessions.get(session_id)
        record, path = self.images.get_original(str(state.image_id))
        edge = self._resolve_edge(request.quality, request.max_edge)
        edge = max(1, min(edge, max(record.width, record.height)))
        preview_id = render_key(
            record.sha256,
            request.recipe.adjustments,
            edge=edge,
            quality=request.quality,
            engine_version=ENGINE_VERSION,
        )

        cached = self.previews.dimensions(preview_id)
        if cached is not None:
            return RenderResult(preview_id, cached[0], cached[1], request.quality, True)

        with self._slots:
            cached = self.previews.dimensions(preview_id)
            if cached is not None:
                return RenderResult(preview_id, cached[0], cached[1], request.quality, True)

            proxy = load_proxy(
                path,
                original_sha256=record.sha256,
                max_edge=edge,
                cache_dir=self.previews.directory,
                max_pixels=self.settings.max_image_pixels,
            )
            rendered = render_image(
                proxy,
                request.recipe.adjustments,
                image_sha256=record.sha256,
                quality=request.quality,
                max_edge=edge,
            )
            data = encode_image(rendered.rgb, image_format="jpeg", quality=JPEG_QUALITY)
            self.previews.write(preview_id, data)

        return RenderResult(
            preview_id,
            rendered.width,
            rendered.height,
            request.quality,
            False,
        )

    def _resolve_edge(self, quality: RenderTier, max_edge: int | None) -> int:
        if max_edge is not None:
            limit = self.settings.render_max_edge_limit
            if max_edge > limit:
                raise AppError(
                    422,
                    "validation_error",
                    "Request validation failed.",
                    {
                        "fields": [
                            {
                                "field": "maxEdge",
                                "rule": "less_than_equal",
                                "limit": {"le": limit},
                                "message": f"maxEdge must be at most {limit}.",
                            }
                        ]
                    },
                )
            return max_edge
        if quality == "draft":
            return min(DRAFT_MAX_EDGE, self.settings.render_max_edge_limit)
        return min(self.settings.render_max_edge_default, self.settings.render_max_edge_limit)
