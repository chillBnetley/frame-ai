from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.geometry import export_target_size, resize_exact
from app.imaging.loader import LoadedImage, load_image
from app.imaging.output import FORMAT_INFO, encode_image
from app.imaging.params_map import (
    EXPORT_BASELINE_MB,
    EXPORT_BYTES_PER_PIXEL_FULL,
    EXPORT_BYTES_PER_PIXEL_LOCAL,
    EXPORT_BYTES_PER_PIXEL_NEUTRAL,
)
from app.imaging.pipeline import raise_if_cancelled
from app.imaging.pipeline import render as render_image
from app.models.export import ExportRequest
from app.models.recipe import EditRecipe
from app.models.sessions import SessionState
from app.services.export_admission import ExportAdmission
from app.services.image_service import ImageService
from app.services.session_service import SessionService

logger = logging.getLogger("frame_ai.export")

EXPORT_JPEG_QUALITY = 92


def _active_local_count(recipe: EditRecipe) -> int:
    return sum(
        1
        for item in recipe.local_adjustments
        if item.enabled and any(item.adjustments.model_dump().values())
    )


def estimate_export_peak_mb(
    pixels: int,
    recipe: EditRecipe,
    *,
    decode_pixels: int | None = None,
) -> float:
    """Conservative peak-RSS estimate for one export plan.

    ``decode_pixels`` is the size of the image that still gets decoded whole.
    A downscaled export renders ``pixels`` but reads the original at full size,
    so its plan can never be cheaper than a neutral pass over that decode.
    """
    neutral = recipe == EditRecipe()
    per_pixel = EXPORT_BYTES_PER_PIXEL_NEUTRAL if neutral else EXPORT_BYTES_PER_PIXEL_FULL
    per_pixel += _active_local_count(recipe) * EXPORT_BYTES_PER_PIXEL_LOCAL
    estimate = pixels * per_pixel / (1024 * 1024) + EXPORT_BASELINE_MB
    if decode_pixels is not None and decode_pixels > pixels:
        floor = decode_pixels * EXPORT_BYTES_PER_PIXEL_NEUTRAL / (1024 * 1024)
        estimate = max(estimate, floor + EXPORT_BASELINE_MB)
    return estimate


@dataclass(frozen=True)
class ExportResult:
    data: bytes
    width: int
    height: int
    filename: str
    media_type: str
    warnings: tuple[str, ...] = ()


class ExportService:
    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        sessions: SessionService,
        *,
        admission: ExportAdmission | None = None,
    ) -> None:
        self.settings = settings
        self.images = images
        self.sessions = sessions
        self.admission = admission or ExportAdmission(
            max_concurrency=settings.export_max_concurrency,
            max_total_mb=settings.export_max_rss_mb,
            reserve_mb=settings.export_reserve_mb,
        )
        # Delete requests need to refuse a session that is currently being
        # rendered for export; the admission gate tracks memory, not identity.
        # Count callers, not just membership: two concurrent exports of the
        # same session must not have the first one cleared when the second
        # fails and runs its ``finally`` block.
        self._active_sessions: dict[str, int] = {}
        self._active_lock = threading.Lock()

    def active_sessions(self) -> frozenset[str]:
        with self._active_lock:
            return frozenset(self._active_sessions)

    def _mark_active(self, session_id: str) -> None:
        with self._active_lock:
            self._active_sessions[session_id] = self._active_sessions.get(session_id, 0) + 1

    def _mark_idle(self, session_id: str) -> None:
        with self._active_lock:
            count = self._active_sessions.get(session_id, 0)
            if count <= 1:
                self._active_sessions.pop(session_id, None)
            else:
                self._active_sessions[session_id] = count - 1

    def export(
        self,
        session_id: str,
        request: ExportRequest,
        *,
        cancel: threading.Event | None = None,
    ) -> ExportResult:
        state = self.sessions.get(session_id)
        key = str(state.session_id).lower()
        self._mark_active(key)
        try:
            return self._render_export(state, request, cancel=cancel)
        finally:
            self._mark_idle(key)

    def _render_export(
        self,
        state: SessionState,
        request: ExportRequest,
        *,
        cancel: threading.Event | None = None,
    ) -> ExportResult:
        raise_if_cancelled(cancel)
        session_id = str(state.session_id)
        revision = self.sessions.get_revision(session_id, request.revision_id)
        record, path = self.images.get_original(str(state.image_id))
        adjustments = revision.recipe.adjustments
        # Sizing happens before decoding so the memory estimate describes the
        # pixels this export will actually touch, not the original's.
        target_width, target_height, source_scale = export_target_size(
            record.width,
            record.height,
            adjustments.rotation_deg,
            adjustments.crop,
            request.max_edge,
        )
        source_pixels = max(1, round(record.width * source_scale)) * max(
            1, round(record.height * source_scale)
        )
        estimate_mb = estimate_export_peak_mb(
            source_pixels,
            revision.recipe,
            decode_pixels=record.width * record.height,
        )
        if estimate_mb > self.settings.export_max_rss_mb:
            raise AppError(
                413,
                "export_too_large",
                "This export would need more memory than allowed.",
                {
                    "estimatedPeakMb": round(estimate_mb),
                    "limitMb": self.settings.export_max_rss_mb,
                    "pixels": source_pixels,
                    "maxEdge": request.max_edge,
                },
            )
        if not self.admission.try_acquire(estimate_mb):
            raise AppError(
                503,
                "server_busy",
                "The server does not have enough free memory for another export; retry shortly.",
                headers={"Retry-After": "2"},
            )
        started = time.perf_counter()
        try:
            raise_if_cancelled(cancel)
            image = load_image(path, max_pixels=self.settings.max_image_pixels)
            raise_if_cancelled(cancel)
            image_width, image_height = image.width, image.height
            if (image_width, image_height) != (record.width, record.height):
                # Orientation-normalised decoding can differ from the stored
                # dimensions; re-derive the plan instead of trusting it.
                target_width, target_height, source_scale = export_target_size(
                    image_width,
                    image_height,
                    adjustments.rotation_deg,
                    adjustments.crop,
                    request.max_edge,
                )
            if source_scale < 1.0:
                # Scaling the source first keeps the composition identical to a
                # full-canvas export while cutting render time and peak memory.
                image = LoadedImage(
                    rgb=resize_exact(
                        image.rgb,
                        max(1, round(image_width * source_scale)),
                        max(1, round(image_height * source_scale)),
                    )
                )
            raise_if_cancelled(cancel)
            rendered = render_image(
                image,
                revision.recipe.adjustments,
                image_sha256=record.sha256,
                curve=revision.recipe.curve,
                hsl=revision.recipe.hsl,
                color_grading=revision.recipe.color_grading,
                masks=revision.recipe.masks,
                local_adjustments=revision.recipe.local_adjustments,
                quality="export",
                denoise_simplify_pixels=self.settings.export_denoise_simplify_pixels,
                cancel=cancel,
            )
            raise_if_cancelled(cancel)
            canvas = rendered.rgb
            if (canvas.shape[1], canvas.shape[0]) != (target_width, target_height):
                # Geometry rounding can leave the canvas 1-2 px away from the
                # requested long edge; converge instead of reporting a lie.
                canvas = resize_exact(canvas, target_width, target_height)
            raise_if_cancelled(cancel)
            quality = request.quality if request.quality is not None else EXPORT_JPEG_QUALITY
            try:
                data = encode_image(canvas, image_format=request.format, quality=quality)
            except (OSError, ValueError) as exc:
                raise AppError(
                    500,
                    "encode_failed",
                    "The rendered image could not be encoded.",
                ) from exc
            raise_if_cancelled(cancel)
        finally:
            self.admission.release(estimate_mb)

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
            width=target_width,
            height=target_height,
            filename=filename,
            media_type=media_type,
            warnings=rendered.warnings,
        )
