from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.loader import load_proxy, proxy_cache_directory
from app.imaging.local_masks import local_adjustment_warnings
from app.imaging.output import JPEG_QUALITY, encode_image
from app.imaging.params_map import DRAFT_MAX_EDGE, ENGINE_VERSION
from app.imaging.pipeline import render as render_image
from app.models.recipe import Adjustments, EditRecipe, render_key
from app.models.render import CompareResponse, CompareSide, RenderRequest, RenderTier
from app.services.image_service import ImageService
from app.services.preview_store import PreviewStore
from app.services.proxy_cache import DecodedProxyCache
from app.services.session_service import SessionService

PREVIEW_URL_PREFIX = "/api/v1/previews"
RENDER_SLOT_TIMEOUT_SECONDS = 10.0
MAX_TRACKED_RENDER_SEQUENCES = 256


@dataclass(frozen=True)
class RenderResult:
    preview_id: str
    width: int
    height: int
    quality: RenderTier
    cache_hit: bool
    warnings: tuple[str, ...] = ()

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
        proxy_cache: DecodedProxyCache | None = None,
        max_concurrent_renders: int = 2,
    ) -> None:
        self.settings = settings
        self.images = images
        self.sessions = sessions
        self.previews = previews or PreviewStore(
            settings.preview_dir,
            ttl_seconds=settings.preview_ttl_seconds,
        )
        self.proxy_cache = proxy_cache or DecodedProxyCache(
            settings.proxy_cache_mb * 1024 * 1024,
        )
        self._slots = threading.BoundedSemaphore(max_concurrent_renders)
        self._latest_seq: OrderedDict[str, int] = OrderedDict()
        self._seq_lock = threading.Lock()

    @contextmanager
    def _render_slot(self) -> Iterator[None]:
        if not self._slots.acquire(timeout=RENDER_SLOT_TIMEOUT_SECONDS):
            raise AppError(
                503,
                "server_busy",
                "Rendering is busy; retry shortly.",
                headers={"Retry-After": "1"},
            )
        try:
            yield
        finally:
            self._slots.release()

    def _note_seq(self, session_id: str, seq: int | None) -> None:
        if seq is None:
            return
        with self._seq_lock:
            self._latest_seq[session_id] = max(seq, self._latest_seq.get(session_id, 0))
            self._latest_seq.move_to_end(session_id)
            while len(self._latest_seq) > MAX_TRACKED_RENDER_SEQUENCES:
                self._latest_seq.popitem(last=False)

    def _superseded(self, session_id: str, seq: int | None) -> bool:
        if seq is None:
            return False
        with self._seq_lock:
            return seq < self._latest_seq.get(session_id, 0)

    def render(
        self,
        session_id: str,
        request: RenderRequest,
        *,
        render_seq: int | None = None,
    ) -> RenderResult:
        self._note_seq(session_id, render_seq)
        state = self.sessions.get(session_id)
        record, path = self.images.get_original(str(state.image_id))
        edge = self._resolve_edge(request.quality, request.max_edge)
        edge = max(1, min(edge, max(record.width, record.height)))
        preview_id = render_key(
            record.sha256,
            request.recipe,
            edge=edge,
            quality=request.quality,
            engine_version=ENGINE_VERSION,
        )

        cached = self.previews.dimensions(preview_id)
        if cached is not None:
            return RenderResult(
                preview_id,
                cached[0],
                cached[1],
                request.quality,
                True,
                self._cached_warnings(request.recipe),
            )

        with self._render_slot():
            cached = self.previews.dimensions(preview_id)
            if cached is not None:
                return RenderResult(
                    preview_id,
                    cached[0],
                    cached[1],
                    request.quality,
                    True,
                    self._cached_warnings(request.recipe),
                )
            if self._superseded(session_id, render_seq):
                raise AppError(
                    409,
                    "render_superseded",
                    "A newer render request replaced this one.",
                )

            proxy_key = self.proxy_cache.key_for(record.sha256, edge)
            proxy = self.proxy_cache.get(proxy_key)
            if proxy is None:
                proxy = load_proxy(
                    path,
                    original_sha256=record.sha256,
                    max_edge=edge,
                    cache_dir=proxy_cache_directory(self.previews.directory),
                    max_pixels=self.settings.max_image_pixels,
                )
                self.proxy_cache.put(proxy_key, proxy)
            # Decoding the proxy can outlive the request it was made for, so the
            # newest sequence number is re-checked before the expensive render.
            if self._superseded(session_id, render_seq):
                raise AppError(
                    409,
                    "render_superseded",
                    "A newer render request replaced this one.",
                )

            rendered = render_image(
                proxy,
                request.recipe.adjustments,
                image_sha256=record.sha256,
                curve=request.recipe.curve,
                hsl=request.recipe.hsl,
                color_grading=request.recipe.color_grading,
                masks=request.recipe.masks,
                local_adjustments=request.recipe.local_adjustments,
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
            rendered.warnings,
        )

    @staticmethod
    def _cached_warnings(recipe: EditRecipe) -> tuple[str, ...]:
        # A content-addressed hit stores no render metadata. Warnings for the
        # preview tiers (draft/final) depend only on the recipe, so they can be
        # derived again without decoding pixels; denoise_simplified is export-only.
        return local_adjustment_warnings(recipe.local_adjustments, recipe.masks)

    def compare(
        self,
        session_id: str,
        *,
        revision_id: UUID | None,
        max_edge: int,
    ) -> CompareResponse:
        state = self.sessions.get(session_id)
        revision = (
            state.revision
            if revision_id is None
            else self.sessions.get_revision(session_id, revision_id)
        )
        record, _ = self.images.get_original(str(state.image_id))
        edge = max(1, min(max_edge, self.settings.render_max_edge_limit))
        edge = min(edge, max(record.width, record.height))

        adjustments = revision.recipe.adjustments
        geometry_only = Adjustments(rotation_deg=adjustments.rotation_deg, crop=adjustments.crop)
        original = self.render(
            session_id,
            RenderRequest(
                recipe=EditRecipe(adjustments=geometry_only),
                max_edge=edge,
                quality="final",
            ),
        )
        rendered = self.render(
            session_id,
            RenderRequest(recipe=revision.recipe, max_edge=edge, quality="final"),
        )
        return CompareResponse(
            original=CompareSide(
                preview_url=original.preview_url,
                width=original.width,
                height=original.height,
            ),
            revision=CompareSide(
                preview_url=rendered.preview_url,
                width=rendered.width,
                height=rendered.height,
            ),
            warnings=list(dict.fromkeys((*original.warnings, *rendered.warnings))),
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
