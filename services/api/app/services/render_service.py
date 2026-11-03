from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.loader import load_proxy
from app.imaging.output import JPEG_QUALITY, encode_image, to_uint8
from app.imaging.params_map import DRAFT_MAX_EDGE, ENGINE_VERSION
from app.imaging.pipeline import render as render_image
from app.models.recipe import render_key
from app.models.render import CompareResponse, CompareSide, RenderRequest, RenderTier
from app.services.image_service import ImageService
from app.services.preview_store import PreviewStore
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
            request.recipe.adjustments,
            edge=edge,
            quality=request.quality,
            engine_version=ENGINE_VERSION,
        )

        cached = self.previews.dimensions(preview_id)
        if cached is not None:
            return RenderResult(preview_id, cached[0], cached[1], request.quality, True)

        with self._render_slot():
            cached = self.previews.dimensions(preview_id)
            if cached is not None:
                return RenderResult(preview_id, cached[0], cached[1], request.quality, True)
            if self._superseded(session_id, render_seq):
                raise AppError(
                    409,
                    "render_superseded",
                    "A newer render request replaced this one.",
                )

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
        record, path = self.images.get_original(str(state.image_id))
        edge = max(1, min(max_edge, self.settings.render_max_edge_limit))
        edge = min(edge, max(record.width, record.height))

        original_id, original_width, original_height = self._original_preview(
            record.sha256,
            path,
            edge,
        )
        rendered = self.render(
            session_id,
            RenderRequest(recipe=revision.recipe, max_edge=edge, quality="final"),
        )
        return CompareResponse(
            original=CompareSide(
                preview_url=f"{PREVIEW_URL_PREFIX}/{original_id}",
                width=original_width,
                height=original_height,
            ),
            revision=CompareSide(
                preview_url=rendered.preview_url,
                width=rendered.width,
                height=rendered.height,
            ),
        )

    def _original_preview(
        self,
        image_sha256: str,
        path: Path,
        edge: int,
    ) -> tuple[str, int, int]:
        preview_id = hashlib.sha256(
            f"{image_sha256.lower()}|{ENGINE_VERSION}|original-preview|{edge}".encode()
        ).hexdigest()
        cached = self.previews.dimensions(preview_id)
        if cached is not None:
            return preview_id, cached[0], cached[1]

        with self._render_slot():
            cached = self.previews.dimensions(preview_id)
            if cached is not None:
                return preview_id, cached[0], cached[1]
            proxy = load_proxy(
                path,
                original_sha256=image_sha256,
                max_edge=edge,
                cache_dir=self.previews.directory,
                max_pixels=self.settings.max_image_pixels,
            )
            data = encode_image(to_uint8(proxy.rgb), image_format="jpeg", quality=JPEG_QUALITY)
            self.previews.write(preview_id, data)
        return preview_id, proxy.width, proxy.height

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
