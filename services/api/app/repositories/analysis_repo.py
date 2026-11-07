from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.ai.contracts import AnalysisOptions
from app.models.analysis_task import (
    AnalysisResultRecord,
    AnalysisTaskRecord,
    TaskStage,
    TaskStatus,
)
from app.repositories.db import connect, utc_now

_TASK_COLUMNS = (
    "id, image_id, image_sha256, options_json, config_key, dedupe_key, status, stage, "
    "attempts, error_code, error_message, created_at, updated_at, started_at, completed_at"
)
_RESULT_COLUMNS = "id, task_id, schema_version, is_mock, report_json, created_at"
_QUALIFIED_RESULT_COLUMNS = (
    "analysis_result.id AS id, analysis_result.task_id AS task_id, "
    "analysis_result.schema_version AS schema_version, analysis_result.is_mock AS is_mock, "
    "analysis_result.report_json AS report_json, analysis_result.created_at AS created_at"
)
_INTERRUPTED_MESSAGE = "The analysis was interrupted before it completed."
_UNIQUE_ERROR_NAMES = frozenset(
    {
        "SQLITE_CONSTRAINT_UNIQUE",
        "SQLITE_CONSTRAINT_PRIMARYKEY",
    }
)


class DuplicateAnalysisTaskError(ValueError):
    """An analysis task already exists for the same dedupe key."""


def _is_unique_violation(exc: sqlite3.IntegrityError) -> bool:
    errorname = str(getattr(exc, "sqlite_errorname", ""))
    if errorname:
        return errorname in _UNIQUE_ERROR_NAMES
    message = str(exc).lower()
    return "unique" in message or "primary key" in message


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_task(row: sqlite3.Row) -> AnalysisTaskRecord:
    data = dict(row)
    options = AnalysisOptions.model_validate_json(str(data.pop("options_json")))
    return AnalysisTaskRecord.model_validate({**data, "options": options})


def _to_result(row: sqlite3.Row) -> AnalysisResultRecord:
    data = dict(row)
    data["is_mock"] = bool(data["is_mock"])
    return AnalysisResultRecord.model_validate(data)


class SqliteAnalysisRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def create(self, task: AnalysisTaskRecord) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "INSERT INTO analysis_task "
                f"({_TASK_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.image_id,
                    task.image_sha256,
                    task.options.model_dump_json(by_alias=True),
                    task.config_key,
                    task.dedupe_key,
                    task.status.value,
                    task.stage.value,
                    task.attempts,
                    task.error_code,
                    task.error_message,
                    _iso(task.created_at),
                    _iso(task.updated_at),
                    _iso(task.started_at),
                    _iso(task.completed_at),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateAnalysisTaskError("duplicate analysis task") from exc
            raise
        finally:
            connection.close()

    def get(self, task_id: str) -> AnalysisTaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM analysis_task WHERE id = ?",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        return _to_task(row) if row is not None else None

    def find_by_dedupe(self, dedupe_key: str) -> AnalysisTaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM analysis_task WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
        finally:
            connection.close()
        return _to_task(row) if row is not None else None

    def mark_started(self, task_id: str) -> AnalysisTaskRecord | None:
        """Claim a queued task.  Only a ``pending`` row flips, so a worker that
        loses the race receives ``None`` and must not write any state."""
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE analysis_task SET status = ?, stage = ?, attempts = attempts + 1, "
                "error_code = NULL, error_message = NULL, started_at = ?, updated_at = ?, "
                "completed_at = NULL WHERE id = ? AND status = ?",
                (
                    TaskStatus.PROCESSING.value,
                    TaskStage.PREPROCESSING.value,
                    now,
                    now,
                    task_id,
                    TaskStatus.PENDING.value,
                ),
            )
            claimed = cursor.rowcount == 1
        finally:
            connection.close()
        return self.get(task_id) if claimed else None

    def set_stage(self, task_id: str, stage: TaskStage) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "UPDATE analysis_task SET stage = ?, updated_at = ? WHERE id = ? AND status = ?",
                (stage.value, utc_now(), task_id, TaskStatus.PROCESSING.value),
            )
        finally:
            connection.close()

    def mark_failed(self, task_id: str, code: str, message: str) -> bool:
        """Fail a task this worker still holds; ``False`` when the claim is gone."""
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE analysis_task SET status = ?, stage = ?, error_code = ?, "
                "error_message = ?, updated_at = ?, completed_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    TaskStatus.FAILED.value,
                    TaskStage.FAILED.value,
                    code,
                    message,
                    now,
                    now,
                    task_id,
                    TaskStatus.PROCESSING.value,
                ),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def complete_with_result(
        self,
        task_id: str,
        *,
        schema_version: str,
        is_mock: bool,
        report_json: str,
    ) -> bool:
        """Persist the report and complete the task, or drop it when the claim is gone.

        The status guard runs before the insert so a worker that lost the race
        cannot leave an orphan result row behind a ``failed`` task.
        """
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE analysis_task SET status = ?, stage = ?, error_code = NULL, "
                    "error_message = NULL, completed_at = ?, updated_at = ? "
                    "WHERE id = ? AND status = ?",
                    (
                        TaskStatus.COMPLETED.value,
                        TaskStage.COMPLETED.value,
                        now,
                        now,
                        task_id,
                        TaskStatus.PROCESSING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return False
                connection.execute(
                    "INSERT INTO analysis_result "
                    "(id, task_id, schema_version, is_mock, report_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), task_id, schema_version, int(is_mock), report_json, now),
                )
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
            return True
        finally:
            connection.close()

    def get_result(self, task_id: str) -> AnalysisResultRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_RESULT_COLUMNS} FROM analysis_result WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        return _to_result(row) if row is not None else None

    def latest_completed_for_image(self, image_id: str) -> AnalysisResultRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_QUALIFIED_RESULT_COLUMNS} FROM analysis_result "
                "JOIN analysis_task ON analysis_task.id = analysis_result.task_id "
                "WHERE analysis_task.image_id = ? AND analysis_task.status = ? "
                "ORDER BY analysis_task.completed_at DESC, analysis_task.created_at DESC "
                "LIMIT 1",
                (image_id.lower(), TaskStatus.COMPLETED.value),
            ).fetchone()
        finally:
            connection.close()
        return _to_result(row) if row is not None else None

    def reset_for_retry(self, task_id: str) -> AnalysisTaskRecord | None:
        """Re-arm a failed task.  Only a ``failed`` row flips, so two simultaneous
        retries cannot both hand the same task to the executor."""
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE analysis_task SET status = ?, stage = ?, attempts = 0, "
                    "error_code = NULL, error_message = NULL, started_at = NULL, "
                    "completed_at = NULL, updated_at = ? WHERE id = ? AND status = ?",
                    (
                        TaskStatus.PENDING.value,
                        TaskStage.QUEUED.value,
                        now,
                        task_id,
                        TaskStatus.FAILED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return None
                connection.execute(
                    "DELETE FROM analysis_result WHERE task_id = ?",
                    (task_id,),
                )
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        return self.get(task_id)

    def has_active_for_image(self, image_id: str) -> bool:
        """True while an analysis for this image is queued or running.

        Deleting the image would cascade the task away mid-run, so callers must
        treat this as a busy resource instead.
        """
        connection = connect(self._path)
        try:
            row = connection.execute(
                "SELECT 1 FROM analysis_task WHERE image_id = ? AND status IN (?, ?) LIMIT 1",
                (
                    image_id.lower(),
                    TaskStatus.PENDING.value,
                    TaskStatus.PROCESSING.value,
                ),
            ).fetchone()
        finally:
            connection.close()
        return row is not None

    def count_queued(self) -> int:
        connection = connect(self._path)
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM analysis_task WHERE status = ?",
                (TaskStatus.PENDING.value,),
            ).fetchone()
        finally:
            connection.close()
        return int(row["total"])

    def delete_if_not_processing(self, task_id: str) -> str:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT status FROM analysis_task WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return "missing"
                if row["status"] == TaskStatus.PROCESSING.value:
                    connection.rollback()
                    return "processing"
                connection.execute("DELETE FROM analysis_task WHERE id = ?", (task_id,))
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
            return "deleted"
        finally:
            connection.close()

    def recover_startup(self, max_attempts: int) -> list[str]:
        now = utc_now()
        rows: list[sqlite3.Row] = []
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE analysis_task SET status = ?, stage = ?, error_code = ?, "
                    "error_message = ?, updated_at = ?, completed_at = ? "
                    "WHERE status = ? AND attempts >= ?",
                    (
                        TaskStatus.FAILED.value,
                        TaskStage.FAILED.value,
                        "analysis_interrupted",
                        _INTERRUPTED_MESSAGE,
                        now,
                        now,
                        TaskStatus.PROCESSING.value,
                        max_attempts,
                    ),
                )
                connection.execute(
                    "UPDATE analysis_task SET status = ?, stage = ?, updated_at = ? "
                    "WHERE status = ?",
                    (
                        TaskStatus.PENDING.value,
                        TaskStage.QUEUED.value,
                        now,
                        TaskStatus.PROCESSING.value,
                    ),
                )
                rows = connection.execute(
                    "SELECT id FROM analysis_task WHERE status = ? ORDER BY created_at, id",
                    (TaskStatus.PENDING.value,),
                ).fetchall()
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        return [str(row["id"]) for row in rows]


__all__ = [
    "DuplicateAnalysisTaskError",
    "SqliteAnalysisRepository",
]
