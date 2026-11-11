from __future__ import annotations

import logging
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.loader import PROXY_EDGE_STEP, proxy_cache_directory, proxy_cache_path
from app.imaging.semantic_mattes import purge_mattes_for_image
from app.repositories.deletion_repo import ImageDeletionRecord, SqliteDeletionRepository
from app.repositories.generative_repo import SqliteGenerativeRepository
from app.services.analysis_task_service import AnalysisTaskService
from app.services.export_jobs import ExportJobManager
from app.services.export_service import ExportService
from app.services.generated_asset_store import GeneratedAssetStore
from app.services.image_service import ImageService
from app.services.preview_store import PreviewStore
from app.services.proxy_cache import DecodedProxyCache

logger = logging.getLogger("frame_ai.deletion")

IMAGE_NOT_FOUND = "The requested image was not found."
SESSION_NOT_FOUND = "The requested session was not found."
RESOURCE_BUSY = "The image is in use by a running analysis or export."


class DeletionService:
    """Hard-delete images and sessions, then their on-disk derivatives.

    Database rows are removed in one transaction; file removal happens after the
    commit and never changes the HTTP outcome. A file that is locked (Windows)
    or otherwise unremovable is logged and left for ``scripts/purge_orphans.py``.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        images: ImageService,
        analysis: AnalysisTaskService,
        exports: ExportService,
        previews: PreviewStore,
        proxy_cache: DecodedProxyCache | None = None,
        repository: SqliteDeletionRepository | None = None,
        export_jobs: ExportJobManager | None = None,
        generated: GeneratedAssetStore | None = None,
        generative_repository: SqliteGenerativeRepository | None = None,
    ) -> None:
        self.settings = settings
        self.images = images
        self.analysis = analysis
        self.exports = exports
        self.previews = previews
        self.proxy_cache = proxy_cache
        self.repository = repository or SqliteDeletionRepository(settings.database_path)
        self.export_jobs = export_jobs
        self.generated = generated or GeneratedAssetStore(settings)
        self.generative_repository = generative_repository or SqliteGenerativeRepository(
            settings.database_path
        )

    def _exporting_sessions(self) -> frozenset[str]:
        active = set(self.exports.active_sessions())
        if self.export_jobs is not None:
            active.update(self.export_jobs.active_sessions())
        return frozenset(active)

    def delete_image(self, image_id: str) -> None:
        normalized = _normalize_or_404(image_id, "image_not_found", IMAGE_NOT_FOUND)
        session_ids = self.repository.session_ids_for_image(normalized)
        reasons: list[str] = []
        if self.analysis.repository.has_active_for_image(normalized):
            reasons.append("analysis")
        if self.generative_repository.has_active_for_image(normalized):
            reasons.append("generative")
        if session_ids and self._exporting_sessions().intersection(session_ids):
            reasons.append("export")
        if reasons:
            raise AppError(409, "resource_busy", RESOURCE_BUSY, {"reasons": reasons})

        outcome = self.repository.delete_image(normalized)
        if outcome.status == "missing":
            raise AppError(404, "image_not_found", IMAGE_NOT_FOUND)
        if outcome.status == "tombstoned":
            # Already deleted by an earlier request. The session rows are gone,
            # so the affected jobs cannot be found by id; retry deferred
            # unlinks and sweep orphan result files instead.
            self._retry_export_cleanup()
            return
        self._purge_export_jobs(outcome.session_ids)
        self._remove_image_files(normalized, outcome)
        logger.info(
            "image_deleted image_id=%s sessions_deleted=%s",
            normalized,
            len(session_ids),
        )

    def delete_session(self, session_id: str) -> None:
        normalized = _normalize_or_404(session_id, "session_not_found", SESSION_NOT_FOUND)
        if normalized in self._exporting_sessions():
            raise AppError(
                409,
                "resource_busy",
                RESOURCE_BUSY,
                {"reasons": ["export"]},
            )
        if self.generative_repository.has_active_for_session(normalized):
            raise AppError(
                409,
                "resource_busy",
                RESOURCE_BUSY,
                {"reasons": ["generative"]},
            )
        outcome = self.repository.delete_session(normalized)
        if outcome.status == "missing":
            raise AppError(404, "session_not_found", SESSION_NOT_FOUND)
        if outcome.status == "tombstoned":
            self._retry_export_cleanup()
            return
        self._purge_export_jobs((normalized,))
        for storage_key in outcome.result_storage_keys:
            self.generated.discard(storage_key)
        for storage_key in outcome.generated_storage_keys:
            self.generated.discard(storage_key)
        for storage_key in outcome.mask_storage_keys:
            self.generated.discard(storage_key)
        # The original image stays; its content-addressed caches are still valid.
        logger.info(
            "session_deleted session_id=%s image_id=%s generated_removed=%s results_removed=%s",
            normalized,
            outcome.image_id,
            len(outcome.generated_storage_keys),
            len(outcome.result_storage_keys),
        )

    def _purge_export_jobs(self, session_ids: tuple[str, ...]) -> None:
        if self.export_jobs is None or not session_ids:
            return
        self.export_jobs.purge_sessions(session_ids)

    def _retry_export_cleanup(self) -> None:
        if self.export_jobs is not None:
            self.export_jobs.retry_cleanup()

    def _remove_image_files(self, image_id: str, outcome: ImageDeletionRecord) -> None:
        original_removed = False
        if outcome.storage_key:
            original_removed = self.images.store.discard(outcome.storage_key)

        generated_removed = sum(
            1
            for storage_key in outcome.generated_storage_keys
            if self.generated.discard(storage_key)
        )
        results_removed = sum(
            1 for storage_key in outcome.result_storage_keys if self.generated.discard(storage_key)
        )
        masks_removed = sum(
            1 for storage_key in outcome.mask_storage_keys if self.generated.discard(storage_key)
        )

        proxies_removed = 0
        proxies_skipped = 0
        cache_dropped = 0
        mattes_removed = 0
        if outcome.sha256 and not self.repository.sha_is_shared(outcome.sha256):
            mattes_removed = purge_mattes_for_image(self.settings.mattes_dir, outcome.sha256)
            cache_dir = proxy_cache_directory(self.previews.directory)
            edge_limit = self.settings.render_max_edge_limit + PROXY_EDGE_STEP
            for edge in range(PROXY_EDGE_STEP, edge_limit, PROXY_EDGE_STEP):
                path = proxy_cache_path(cache_dir, outcome.sha256, edge)
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
                except OSError:
                    proxies_skipped += 1
                    logger.warning("image_delete_proxy_failed image_id=%s path=%s", image_id, path)
                    continue
                proxies_removed += 1
            if self.proxy_cache is not None:
                cache_dropped = self.proxy_cache.drop_original(outcome.sha256)

        purged = self.previews.purge_previews()
        if not original_removed:
            logger.warning("image_delete_original_failed image_id=%s", image_id)
        logger.info(
            "image_files_deleted image_id=%s original_removed=%s proxies_removed=%s "
            "proxies_skipped=%s previews_removed=%s previews_skipped=%s "
            "proxy_cache_dropped=%s mattes_removed=%s generated_removed=%s "
            "results_removed=%s masks_removed=%s",
            image_id,
            original_removed,
            proxies_removed,
            proxies_skipped,
            purged.deleted,
            purged.skipped,
            cache_dropped,
            mattes_removed,
            generated_removed,
            results_removed,
            masks_removed,
        )


def _normalize_or_404(value: str, code: str, message: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AppError(404, code, message) from exc


__all__ = ["DeletionService", "IMAGE_NOT_FOUND", "SESSION_NOT_FOUND"]
