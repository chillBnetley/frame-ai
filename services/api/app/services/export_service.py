from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.loader import load_image
from app.imaging.output import FORMAT_INFO, encode_image
from app.imaging.pipeline import render as render_image
from app.models.export import ExportRequest
from app.services.image_service import ImageService
from app.services.session_service import SessionService

logger = logging.getLogger("frame_ai.export")

EXPORT_JPEG_QUALITY = 92


@dataclass(frozen=True)
class ExportResult:
    data: bytes
    width: int
    height: int
    filename: str
    media_type: str


class ExportService:
    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        sessions: SessionService,
        *,
        max_concurrent_exports: int = 1,
    ) -> None:
        self.settings = settings
        self.images = images
        self.sessions = sessions
        self._slots = threading.BoundedSemaphore(max_concurrent_exports)

    def export(self, session_id: str, request: ExportRequest) -> ExportResult:
        state = self.sessions.get(session_id)
        revision = self.sessions.get_revision(session_id, request.revision_id)

        if not self._slots.acquire(blocking=False):
            raise AppError(
                503,
                "server_busy",
                "Another high-resolution export is in progress; retry shortly.",
                headers={"Retry-After": "2"},
            )
        started = time.perf_counter()
        try:
            record, path = self.images.get_original(str(state.image_id))
            image = load_image(path, max_pixels=self.settings.max_image_pixels)
            rendered = render_image(
                image,
                revision.recipe.adjustments,
                image_sha256=record.sha256,
                quality="export",
            )
            quality = request.quality if request.quality is not None else EXPORT_JPEG_QUALITY
            data = encode_image(rendered.rgb, image_format=request.format, quality=quality)
        finally:
            self._slots.release()

        _, suffix, media_type = FORMAT_INFO[request.format]
        filename = f"frame-{revision.id.hex[:8]}{suffix}"
        logger.info(
            "export_completed session_id=%s revision_id=%s format=%s bytes=%s duration_ms=%.2f",
            state.session_id,
            revision.id,
            request.format,
            len(data),
            (time.perf_counter() - started) * 1000,
        )
        return ExportResult(
            data=data,
            width=rendered.width,
            height=rendered.height,
            filename=filename,
            media_type=media_type,
        )
