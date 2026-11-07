from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.core.errors import AppError
from app.imaging.pipeline import RenderCancelled
from app.models.export import (
    ExportBitDepth,
    ExportJobError,
    ExportJobResponse,
    ExportJobStatus,
    ExportRequest,
)
from app.services.export_service import ExportResult, ExportService

logger = logging.getLogger("frame_ai.export_jobs")

# A retired session only needs to outlive render threads that already passed
# the delete-time busy check.  TTL covers them; the hard cap keeps a burst of
# deletions from growing the fence without bound.
RETIRED_SESSION_LIMIT = 4096


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class _ExportJob:
    id: str
    session_id: str
    request: ExportRequest
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    status: ExportJobStatus = "queued"
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    result_path: Path | None = None
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    bit_depth: ExportBitDepth = 8
    media_type: str | None = None
    warnings: tuple[str, ...] = ()
    error: AppError | None = None
    finished_at: float | None = None


class ExportJobManager:
    """In-process async export jobs.

    Jobs are memory-only: a restart loses every status and the result files are
    treated as orphans on the next start. Rendering itself runs on the existing
    ``ExportService`` pipeline, so admission, cancellation and output encoding
    stay in one place.
    """

    def __init__(
        self,
        exports: ExportService,
        *,
        directory: Path,
        ttl_seconds: int,
        queue_max: int,
        max_workers: int,
    ) -> None:
        self.exports = exports
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self.queue_max = queue_max
        self._jobs: dict[str, _ExportJob] = {}
        # Deleted sessions stay fenced for one TTL so a job that passed the
        # delete-time busy check can never publish a downloadable result.
        self._retired: dict[str, float] = {}
        # Result paths whose immediate unlink failed (usually a Windows open
        # handle). They are retried on later requests and tombstone deletes.
        self._pending_unlinks: set[Path] = set()
        self._lock = threading.Lock()
        # Serializes result writes with the orphan sweep so the sweep can never
        # delete a file a concurrently starting job is about to publish.
        self._result_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="export-job",
        )
        self._closed = False

    def ensure_ready(self) -> None:
        """Create the result directory and drop files left by a previous run."""
        self.directory.mkdir(parents=True, exist_ok=True)
        removed = 0
        try:
            entries = list(os.scandir(self.directory))
        except OSError:
            logger.warning("export_job_scan_failed directory=%s", self.directory)
            return
        for entry in entries:
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                os.unlink(entry.path)
                removed += 1
            except OSError:
                logger.warning("export_job_stale_unlink_failed path=%s", entry.path)
        if removed:
            logger.info("export_job_stale_removed count=%s", removed)

    def submit(self, session_id: str, request: ExportRequest) -> _ExportJob:
        # Validate synchronously so an unknown session/revision is still a 404,
        # not a 202 followed by a failed job.
        state = self.exports.sessions.get(session_id)
        self.exports.sessions.get_revision(str(state.session_id), request.revision_id)
        now = _utcnow()
        job = _ExportJob(
            id=uuid4().hex,
            session_id=str(state.session_id),
            request=request,
            bit_depth=request.bit_depth,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._sweep_locked(time.time())
            if self._closed:
                raise AppError(503, "service_unavailable", "The service is shutting down.")
            if self._is_retired_locked(job.session_id):
                # The session was deleted after the synchronous validation above
                # but before this job reached the registry.
                raise AppError(404, "session_not_found", "The requested session was not found.")
            queued = sum(1 for item in self._jobs.values() if item.status == "queued")
            if queued >= self.queue_max:
                raise AppError(
                    503,
                    "server_busy",
                    "Too many export jobs are waiting; retry shortly.",
                    headers={"Retry-After": "2"},
                )
            self._jobs[job.id] = job
        try:
            self._executor.submit(self._run, job)
        except RuntimeError as exc:
            with self._lock:
                self._jobs.pop(job.id, None)
            raise AppError(503, "service_unavailable", "The export worker is unavailable.") from exc
        self._drain_pending_unlinks()
        return job

    def get(self, job_id: str) -> _ExportJob:
        with self._lock:
            self._sweep_locked(time.time())
            job = self._jobs.get(job_id)
        self._drain_pending_unlinks()
        if job is None:
            raise AppError(404, "export_not_found", "Export job not found.")
        return job

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        with self._lock:
            if job.status in {"succeeded", "failed", "cancelled"}:
                return
            job.cancel.set()
            if job.status == "queued":
                job.status = "cancelled"
                job.updated_at = _utcnow()
                job.finished_at = time.time()
                job.done.set()
                logger.info("export_job_cancelled job_id=%s queued=true", job.id)

    def active_sessions(self) -> frozenset[str]:
        """Sessions with a queued or running job, for delete guards."""
        with self._lock:
            return frozenset(
                job.session_id.lower()
                for job in self._jobs.values()
                if job.status in {"queued", "running"}
            )

    def purge_sessions(self, session_ids: Iterable[str]) -> int:
        """Retire deleted sessions and drop every job that belongs to them.

        The deletion service checks ``active_sessions()`` before the database
        commit, but a job can pass its own session validation in the gap before
        that check. Such a job must not publish a result afterwards, so retired
        sessions are fenced: matching queued/running jobs are cancelled and
        removed from the registry, and ``_run`` re-checks the fence under the
        lock before a result becomes visible. Terminal jobs are removed and
        their result files detached here; unlinks happen outside the lock and
        failures are retried by ``retry_cleanup()``.
        """
        targets = {str(item).lower() for item in session_ids}
        now = time.time()
        removed = 0
        if targets:
            with self._lock:
                self._sweep_locked(now)
                for session_id in targets:
                    self._retire_locked(session_id, now)
                for job_id, job in list(self._jobs.items()):
                    if job.session_id.lower() not in targets:
                        continue
                    self._jobs.pop(job_id, None)
                    removed += 1
                    if job.status in {"queued", "running"}:
                        # Cooperative cancellation; the worker stops at its
                        # next checkpoint and the post-write fence drops any
                        # result that still made it to disk.
                        job.cancel.set()
                    path = job.result_path
                    job.result_path = None
                    if path is not None:
                        self._pending_unlinks.add(path)
        self._drain_pending_unlinks()
        if removed:
            logger.info(
                "export_jobs_purged sessions=%s jobs=%s",
                len(targets),
                removed,
            )
        return removed

    def retry_cleanup(self) -> int:
        """Finish cleanup left behind by a deferred unlink.

        Called on tombstone deletes (where the session/image rows are already
        gone, so the affected jobs can no longer be located by session id) and
        by callers that want to sweep crash leftovers. Result files are matched
        to live jobs by job id; anything else in the export directory is an
        orphan.
        """
        self._drain_pending_unlinks()
        return self.purge_orphan_results()

    def purge_orphan_results(self) -> int:
        """Remove result files that no job in the registry owns.

        Temporary files (leading dot), directories and symlinks are skipped.
        A running job writes its destination only after rendering completes and
        is protected by its job id even before ``result_path`` is assigned.
        """
        removed = 0
        # Take the write lock before the registry snapshot: a job added after
        # the snapshot is then blocked from writing until the sweep finishes,
        # and a job added before it is already protected by id.
        with self._result_lock:
            with self._lock:
                protected = {job.id for job in self._jobs.values()}
            try:
                entries = list(os.scandir(self.directory))
            except OSError:
                logger.warning("export_orphan_scan_failed directory=%s", self.directory)
                return 0
            for entry in entries:
                try:
                    if entry.name.startswith("."):
                        continue
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    if Path(entry.name).stem in protected:
                        continue
                    os.unlink(entry.path)
                    removed += 1
                except OSError:
                    with self._lock:
                        self._pending_unlinks.add(Path(entry.path))
                    logger.warning("export_orphan_result_unlink_deferred path=%s", entry.path)
        if removed:
            logger.info("export_orphan_results_removed count=%s", removed)
        return removed

    def result(self, job_id: str) -> tuple[_ExportJob, Path]:
        job = self.get(job_id)
        if job.status == "cancelled":
            raise AppError(409, "export_cancelled", "The export job was cancelled.")
        if job.status == "failed":
            raise AppError(409, "export_failed", "The export job failed.")
        if job.status != "succeeded" or job.result_path is None:
            raise AppError(409, "export_not_ready", "The export job has not finished yet.")
        if not job.result_path.is_file():
            raise AppError(
                404,
                "export_result_missing",
                "The export result is no longer available.",
            )
        return job, job.result_path

    def open_result(self, job_id: str) -> tuple[_ExportJob, BinaryIO, int]:
        """Open a succeeded job's result while holding the registry lock.

        Opening inside the lock closes the check-then-open window: a deletion
        purge either removes the job before we see it (404) or runs after the
        handle exists. On POSIX the later unlink keeps the open stream readable;
        on Windows the unlink is deferred to ``retry_cleanup()``.
        """
        with self._lock:
            self._sweep_locked(time.time())
            job = self._jobs.get(job_id)
            if job is None:
                raise AppError(404, "export_not_found", "Export job not found.")
            if job.status == "cancelled":
                raise AppError(409, "export_cancelled", "The export job was cancelled.")
            if job.status == "failed":
                raise AppError(409, "export_failed", "The export job failed.")
            if job.status != "succeeded" or job.result_path is None:
                raise AppError(
                    409,
                    "export_not_ready",
                    "The export job has not finished yet.",
                )
            try:
                stream = job.result_path.open("rb")
            except OSError:
                raise AppError(
                    404,
                    "export_result_missing",
                    "The export result is no longer available.",
                ) from None
            size = os.fstat(stream.fileno()).st_size
        self._drain_pending_unlinks()
        return job, stream, size

    def response(self, job: _ExportJob) -> ExportJobResponse:
        with self._lock:
            error = None
            if job.error is not None:
                error = ExportJobError(
                    code=job.error.code,
                    message=job.error.message,
                    details=dict(job.error.details),
                )
            return ExportJobResponse(
                job_id=job.id,
                status=job.status,
                filename=job.filename,
                width=job.width,
                height=job.height,
                bit_depth=job.bit_depth,
                warnings=list(job.warnings),
                error=error,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job: _ExportJob) -> None:
        try:
            with self._lock:
                if self._jobs.get(job.id) is not job or self._is_retired_locked(job.session_id):
                    # A delete raced past the busy check and retired this
                    # session before the worker started.
                    job.status = "cancelled"
                    job.updated_at = _utcnow()
                    job.finished_at = time.time()
                    logger.info("export_job_discarded_before_start job_id=%s", job.id)
                    return
                if job.status != "queued":
                    return
                job.status = "running"
                job.updated_at = _utcnow()
            logger.info("export_job_started job_id=%s session_id=%s", job.id, job.session_id)
            result = self.exports.export(job.session_id, job.request, cancel=job.cancel)
            if job.cancel.is_set():
                raise RenderCancelled
            with self._lock:
                discard = (
                    self._jobs.get(job.id) is not job
                    or self._is_retired_locked(job.session_id)
                    or job.cancel.is_set()
                )
            if discard:
                raise RenderCancelled
            path = self._write_result(job.id, result)
            finalized = False
            with self._lock:
                # Re-check after the bytes reached the destination: a purge can
                # run between the check above and this point, and the file must
                # not become downloadable behind its back.
                if (
                    self._jobs.get(job.id) is not job
                    or self._is_retired_locked(job.session_id)
                    or job.cancel.is_set()
                ):
                    logger.info("export_job_result_discarded job_id=%s", job.id)
                else:
                    job.status = "succeeded"
                    job.result_path = path
                    job.filename = result.filename
                    job.width = result.width
                    job.height = result.height
                    job.media_type = result.media_type
                    job.bit_depth = result.bit_depth
                    job.warnings = result.warnings
                    job.updated_at = _utcnow()
                    job.finished_at = time.time()
                    finalized = True
            if not finalized:
                self._discard_result(path)
                raise RenderCancelled
            logger.info(
                "export_job_succeeded job_id=%s bytes=%s",
                job.id,
                len(result.data),
            )
        except RenderCancelled:
            self._finish_cancelled(job)
        except AppError as exc:
            self._finish_failed(job, exc)
        except Exception:
            logger.exception("export_job_crashed job_id=%s", job.id)
            self._finish_failed(
                job,
                AppError(500, "export_failed", "The export job failed unexpectedly."),
            )
        finally:
            job.done.set()

    def _finish_cancelled(self, job: _ExportJob) -> None:
        with self._lock:
            job.status = "cancelled"
            job.updated_at = _utcnow()
            job.finished_at = time.time()
            path = job.result_path
            job.result_path = None
        self._discard_result(path)
        logger.info("export_job_cancelled job_id=%s", job.id)

    def _finish_failed(self, job: _ExportJob, error: AppError) -> None:
        with self._lock:
            job.status = "failed"
            job.error = error
            job.updated_at = _utcnow()
            job.finished_at = time.time()
            path = job.result_path
            job.result_path = None
        self._discard_result(path)
        logger.info("export_job_failed job_id=%s code=%s", job.id, error.code)

    def _write_result(self, job_id: str, result: ExportResult) -> Path:
        with self._result_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            suffix = Path(result.filename).suffix or ".bin"
            destination = self.directory / f"{job_id}{suffix}"
            temporary = self.directory / f".{job_id}.{uuid4().hex}.tmp"
            try:
                temporary.write_bytes(result.data)
                os.replace(temporary, destination)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise AppError(
                    500,
                    "export_storage_error",
                    "The export result could not be stored.",
                ) from exc
        return destination

    def _sweep_locked(self, now: float) -> None:
        expired = [
            job
            for job in self._jobs.values()
            if job.finished_at is not None and now - job.finished_at > self.ttl_seconds
        ]
        for job in expired:
            self._jobs.pop(job.id, None)
            path = job.result_path
            job.result_path = None
            if path is not None:
                self._pending_unlinks.add(path)
        expired_retired = [
            session_id for session_id, expiry in self._retired.items() if expiry <= now
        ]
        for session_id in expired_retired:
            self._retired.pop(session_id, None)

    def _retire_locked(self, session_id: str, now: float) -> None:
        self._retired[session_id.lower()] = now + self.ttl_seconds
        while len(self._retired) > RETIRED_SESSION_LIMIT:
            oldest = next(iter(self._retired))
            self._retired.pop(oldest, None)
            logger.warning("export_retired_session_evicted session_id=%s", oldest)

    def _is_retired_locked(self, session_id: str) -> bool:
        return session_id.lower() in self._retired

    def _discard_result(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            with self._lock:
                self._pending_unlinks.add(path)
            logger.warning("export_job_result_unlink_deferred path=%s", path)

    def _drain_pending_unlinks(self) -> int:
        with self._lock:
            pending = list(self._pending_unlinks)
        if not pending:
            return 0
        still: set[Path] = set()
        removed = 0
        for path in pending:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                still.add(path)
            else:
                removed += 1
        with self._lock:
            self._pending_unlinks.difference_update(pending)
            self._pending_unlinks.update(still)
        if removed or still:
            logger.info(
                "export_job_result_unlinks_retried removed=%s remaining=%s",
                removed,
                len(still),
            )
        return removed
