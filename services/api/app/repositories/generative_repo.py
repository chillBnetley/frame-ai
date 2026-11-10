from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models.generative import (
    GeneratedAssetRecord,
    GenerativeMaskRecord,
    GenerativeResultRecord,
    GenerativeTaskRecord,
    GenerativeTaskStatus,
)
from app.repositories.db import connect, utc_now

_TASK_COLUMNS = (
    "id, owner_id, image_id, session_id, base_revision_id, base_generated_asset_id, "
    "task_type, instruction, plan_json, params_json, mask_id, provider, model, "
    "prompt_version, provider_job_id, is_mock, status, stage, attempts, max_attempts, "
    "cancel_requested, consent_at, provider_retention, error_code, error_message, "
    "dedupe_key, idempotency_key, created_at, updated_at, started_at, completed_at, "
    "expires_at"
)
_RESULT_COLUMNS = (
    "id, task_id, result_index, storage_key, sha256, width, height, bytes, mime_type, "
    "status, validation_json, revision_id, created_at, decided_at"
)
_QUALIFIED_RESULT_COLUMNS = (
    "generative_result.id AS id, generative_result.task_id AS task_id, "
    "generative_result.result_index AS result_index, "
    "generative_result.storage_key AS storage_key, generative_result.sha256 AS sha256, "
    "generative_result.width AS width, generative_result.height AS height, "
    "generative_result.bytes AS bytes, generative_result.mime_type AS mime_type, "
    "generative_result.status AS status, "
    "generative_result.validation_json AS validation_json, "
    "generative_result.revision_id AS revision_id, "
    "generative_result.created_at AS created_at, "
    "generative_result.decided_at AS decided_at"
)
_ASSET_COLUMNS = (
    "id, image_id, task_id, result_id, kind, storage_key, sha256, width, height, bytes, "
    "mime_type, created_at, deleted_at"
)
_MASK_COLUMNS = (
    "id, owner_id, image_id, base_generated_asset_id, kind, source, coordinate_space, "
    "width, height, storage_key, sha256, feather, inverted, strokes_json, created_at, "
    "deleted_at"
)
_ACTIVE_STATUSES = (
    GenerativeTaskStatus.CREATED.value,
    GenerativeTaskStatus.VALIDATING.value,
    GenerativeTaskStatus.QUEUED.value,
    GenerativeTaskStatus.PROCESSING.value,
)
_UNIQUE_ERROR_NAMES = frozenset({"SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_PRIMARYKEY"})


class DuplicateGenerativeTaskError(ValueError):
    pass


class DuplicateGeneratedAssetError(ValueError):
    pass


class RetryNotAllowedError(RuntimeError):
    pass


class MaskInUseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MaskDeletionOutcome:
    removed: bool
    referenced: bool


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _is_unique_violation(exc: sqlite3.IntegrityError) -> bool:
    errorname = str(getattr(exc, "sqlite_errorname", ""))
    if errorname:
        return errorname in _UNIQUE_ERROR_NAMES
    message = str(exc).lower()
    return "unique" in message or "primary key" in message


def _to_task(row: sqlite3.Row) -> GenerativeTaskRecord:
    data = dict(row)
    data["is_mock"] = bool(data["is_mock"])
    data["cancel_requested"] = bool(data["cancel_requested"])
    return GenerativeTaskRecord.model_validate(data)


def _to_result(row: sqlite3.Row) -> GenerativeResultRecord:
    return GenerativeResultRecord.model_validate(dict(row))


def _to_asset(row: sqlite3.Row) -> GeneratedAssetRecord:
    return GeneratedAssetRecord.model_validate(dict(row))


def _to_mask(row: sqlite3.Row) -> GenerativeMaskRecord:
    data = dict(row)
    data["inverted"] = bool(data["inverted"])
    return GenerativeMaskRecord.model_validate(data)


class SqliteGenerativeRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    # ------------------------------------------------------------------ tasks

    def create_task(self, task: GenerativeTaskRecord) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "INSERT INTO generative_task "
                f"({_TASK_COLUMNS}) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                " ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.owner_id,
                    task.image_id,
                    task.session_id,
                    task.base_revision_id,
                    task.base_generated_asset_id,
                    task.task_type.value,
                    task.instruction,
                    task.plan_json,
                    task.params_json,
                    task.mask_id,
                    task.provider,
                    task.model,
                    task.prompt_version,
                    task.provider_job_id,
                    int(task.is_mock),
                    task.status.value,
                    task.stage.value,
                    task.attempts,
                    task.max_attempts,
                    int(task.cancel_requested),
                    _iso(task.consent_at),
                    task.provider_retention,
                    task.error_code,
                    task.error_message,
                    task.dedupe_key,
                    task.idempotency_key,
                    _iso(task.created_at),
                    _iso(task.updated_at),
                    _iso(task.started_at),
                    _iso(task.completed_at),
                    _iso(task.expires_at),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateGenerativeTaskError("duplicate generative task") from exc
            raise
        finally:
            connection.close()

    def get_task(self, task_id: str) -> GenerativeTaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM generative_task WHERE id = ?",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        return _to_task(row) if row is not None else None

    def get_task_for_owner(self, task_id: str, owner_id: str) -> GenerativeTaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM generative_task WHERE id = ? AND owner_id = ?",
                (task_id, owner_id),
            ).fetchone()
        finally:
            connection.close()
        return _to_task(row) if row is not None else None

    def find_by_dedupe(self, dedupe_key: str) -> GenerativeTaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM generative_task WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
        finally:
            connection.close()
        return _to_task(row) if row is not None else None

    def find_by_idempotency(
        self,
        owner_id: str,
        idempotency_key: str,
    ) -> GenerativeTaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM generative_task "
                "WHERE owner_id = ? AND idempotency_key = ?",
                (owner_id, idempotency_key),
            ).fetchone()
        finally:
            connection.close()
        return _to_task(row) if row is not None else None

    def claim(self, task_id: str) -> GenerativeTaskRecord | None:
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE generative_task SET status = ?, stage = ?, attempts = attempts + 1, "
                "error_code = NULL, error_message = NULL, started_at = ?, updated_at = ?, "
                "completed_at = NULL WHERE id = ? AND status = ? AND attempts < max_attempts",
                (
                    GenerativeTaskStatus.PROCESSING.value,
                    "preparing_input",
                    now,
                    now,
                    task_id,
                    GenerativeTaskStatus.QUEUED.value,
                ),
            )
            claimed = cursor.rowcount == 1
        finally:
            connection.close()
        return self.get_task(task_id) if claimed else None

    def set_stage(self, task_id: str, stage: str) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "UPDATE generative_task SET stage = ?, updated_at = ? WHERE id = ? AND status = ?",
                (stage, utc_now(), task_id, GenerativeTaskStatus.PROCESSING.value),
            )
        finally:
            connection.close()

    def set_provider_job_id(self, task_id: str, provider_job_id: str | None) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "UPDATE generative_task SET provider_job_id = ?, updated_at = ? WHERE id = ?",
                (provider_job_id, utc_now(), task_id),
            )
        finally:
            connection.close()

    def is_cancel_requested(self, task_id: str) -> bool:
        connection = connect(self._path)
        try:
            row = connection.execute(
                "SELECT cancel_requested FROM generative_task WHERE id = ?",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        return bool(row["cancel_requested"]) if row is not None else False

    def complete_with_result(
        self,
        task_id: str,
        result: GenerativeResultRecord,
    ) -> bool:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE generative_task SET status = ?, stage = ?, error_code = NULL, "
                    "error_message = NULL, completed_at = ?, updated_at = ? "
                    "WHERE id = ? AND status = ?",
                    (
                        GenerativeTaskStatus.SUCCEEDED.value,
                        "completed",
                        now,
                        now,
                        task_id,
                        GenerativeTaskStatus.PROCESSING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return False
                connection.execute(
                    "INSERT INTO generative_result "
                    f"({_RESULT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.id,
                        task_id,
                        result.result_index,
                        result.storage_key,
                        result.sha256,
                        result.width,
                        result.height,
                        result.bytes,
                        result.mime_type,
                        result.status.value,
                        result.validation_json,
                        result.revision_id,
                        _iso(result.created_at),
                        _iso(result.decided_at),
                    ),
                )
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
            return True
        finally:
            connection.close()

    def fail(self, task_id: str, code: str, message: str) -> bool:
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE generative_task SET status = ?, stage = ?, error_code = ?, "
                "error_message = ?, updated_at = ?, completed_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    GenerativeTaskStatus.FAILED.value,
                    "failed",
                    code,
                    message,
                    now,
                    now,
                    task_id,
                    GenerativeTaskStatus.PROCESSING.value,
                ),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def cancel(self, task_id: str) -> GenerativeTaskRecord | None:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT status FROM generative_task WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return None
                status = str(row["status"])
                if status in (
                    GenerativeTaskStatus.CREATED.value,
                    GenerativeTaskStatus.VALIDATING.value,
                    GenerativeTaskStatus.QUEUED.value,
                ):
                    connection.execute(
                        "UPDATE generative_task SET status = ?, error_code = 'cancelled', "
                        "error_message = 'The task was cancelled.', updated_at = ?, "
                        "completed_at = ? WHERE id = ?",
                        (GenerativeTaskStatus.CANCELLED.value, now, now, task_id),
                    )
                elif status == GenerativeTaskStatus.PROCESSING.value:
                    connection.execute(
                        "UPDATE generative_task SET cancel_requested = 1, updated_at = ? "
                        "WHERE id = ?",
                        (now, task_id),
                    )
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        return self.get_task(task_id)

    def mark_cancelled(self, task_id: str) -> bool:
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE generative_task SET status = ?, error_code = 'cancelled', "
                "error_message = 'The task was cancelled.', updated_at = ?, completed_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    GenerativeTaskStatus.CANCELLED.value,
                    now,
                    now,
                    task_id,
                    GenerativeTaskStatus.PROCESSING.value,
                ),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def mark_expired(self, task_id: str) -> bool:
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE generative_task SET status = ?, error_code = 'expired', "
                "error_message = 'The task expired before it finished.', updated_at = ?, "
                "completed_at = ? WHERE id = ? AND status = ?",
                (
                    GenerativeTaskStatus.EXPIRED.value,
                    now,
                    now,
                    task_id,
                    GenerativeTaskStatus.PROCESSING.value,
                ),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def reset_for_retry(self, task_id: str) -> GenerativeTaskRecord:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT status, attempts, max_attempts FROM generative_task WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    raise KeyError(task_id)
                status = str(row["status"])
                if status not in (
                    GenerativeTaskStatus.FAILED.value,
                    GenerativeTaskStatus.CANCELLED.value,
                    GenerativeTaskStatus.EXPIRED.value,
                ):
                    connection.rollback()
                    raise RetryNotAllowedError("Only a finished task can be retried.")
                if int(row["attempts"]) >= int(row["max_attempts"]):
                    connection.rollback()
                    raise RetryNotAllowedError("The task reached its retry limit.")
                connection.execute(
                    "DELETE FROM generative_result WHERE task_id = ?",
                    (task_id,),
                )
                connection.execute(
                    "UPDATE generative_task SET status = ?, stage = ?, cancel_requested = 0, "
                    "error_code = NULL, error_message = NULL, started_at = NULL, "
                    "completed_at = NULL, updated_at = ? WHERE id = ?",
                    (
                        GenerativeTaskStatus.QUEUED.value,
                        "queued",
                        now,
                        task_id,
                    ),
                )
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def expire_if_needed(self, task_id: str, *, now: datetime) -> GenerativeTaskRecord | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status.value not in _ACTIVE_STATUSES or task.expires_at > now:
            return task
        connection = connect(self._path)
        try:
            if task.status is GenerativeTaskStatus.PROCESSING:
                connection.execute(
                    "UPDATE generative_task SET cancel_requested = 1, error_code = 'expired', "
                    "error_message = 'The task expired before it finished.', updated_at = ? "
                    "WHERE id = ? AND status = ?",
                    (utc_now(), task_id, GenerativeTaskStatus.PROCESSING.value),
                )
            else:
                connection.execute(
                    "UPDATE generative_task SET status = ?, error_code = 'expired', "
                    "error_message = 'The task expired before it finished.', updated_at = ?, "
                    "completed_at = ? WHERE id = ? AND status IN (?, ?, ?)",
                    (
                        GenerativeTaskStatus.EXPIRED.value,
                        utc_now(),
                        utc_now(),
                        task_id,
                        GenerativeTaskStatus.CREATED.value,
                        GenerativeTaskStatus.VALIDATING.value,
                        GenerativeTaskStatus.QUEUED.value,
                    ),
                )
        finally:
            connection.close()
        return self.get_task(task_id)

    def recover_startup(self) -> list[str]:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE generative_task SET status = ?, error_code = 'expired', "
                    "error_message = 'The task expired while the service was stopped.', "
                    "updated_at = ?, completed_at = ? "
                    "WHERE status IN (?, ?, ?, ?) AND expires_at <= ?",
                    (
                        GenerativeTaskStatus.EXPIRED.value,
                        now,
                        now,
                        *_ACTIVE_STATUSES,
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE generative_task SET status = ?, stage = 'failed', "
                    "error_code = 'service_restarted', "
                    "error_message = 'The task was interrupted by a service restart.', "
                    "updated_at = ?, completed_at = ? WHERE status IN (?, ?, ?)",
                    (
                        GenerativeTaskStatus.FAILED.value,
                        now,
                        now,
                        GenerativeTaskStatus.CREATED.value,
                        GenerativeTaskStatus.VALIDATING.value,
                        GenerativeTaskStatus.PROCESSING.value,
                    ),
                )
                connection.execute(
                    "UPDATE generative_task SET status = ?, stage = 'failed', "
                    "error_code = 'retry_limit_reached', "
                    "error_message = 'The task reached its retry limit.', "
                    "updated_at = ?, completed_at = ? "
                    "WHERE status = ? AND attempts >= max_attempts",
                    (
                        GenerativeTaskStatus.FAILED.value,
                        now,
                        now,
                        GenerativeTaskStatus.QUEUED.value,
                    ),
                )
                rows = connection.execute(
                    "SELECT id FROM generative_task WHERE status = ? ORDER BY created_at, id",
                    (GenerativeTaskStatus.QUEUED.value,),
                ).fetchall()
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        return [str(row["id"]) for row in rows]

    def list_tasks(
        self,
        owner_id: str,
        *,
        limit: int,
        offset: int,
        status: GenerativeTaskStatus | None = None,
    ) -> list[GenerativeTaskRecord]:
        connection = connect(self._path)
        try:
            params: list[object] = [owner_id]
            where = "owner_id = ?"
            if status is not None:
                where += " AND status = ?"
                params.append(status.value)
            params.extend((limit, offset))
            rows = connection.execute(
                f"SELECT {_TASK_COLUMNS} FROM generative_task WHERE {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        finally:
            connection.close()
        return [_to_task(row) for row in rows]

    def count_active(self, owner_id: str) -> int:
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM generative_task "
                f"WHERE owner_id = ? AND status IN ({placeholders})",
                (owner_id, *_ACTIVE_STATUSES),
            ).fetchone()
        finally:
            connection.close()
        return int(row["total"])

    def has_active_for_image(self, image_id: str) -> bool:
        return self._has_active("image_id", image_id)

    def has_active_for_session(self, session_id: str) -> bool:
        return self._has_active("session_id", session_id)

    def _has_active(self, column: str, value: str) -> bool:
        if column not in {"image_id", "session_id"}:
            raise ValueError("unsupported active-task lookup")
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT 1 FROM generative_task WHERE {column} = ? "
                f"AND status IN ({placeholders}) LIMIT 1",
                (value, *_ACTIVE_STATUSES),
            ).fetchone()
        finally:
            connection.close()
        return row is not None

    # ---------------------------------------------------------------- results

    def get_result(self, result_id: str) -> GenerativeResultRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_RESULT_COLUMNS} FROM generative_result WHERE id = ?",
                (result_id,),
            ).fetchone()
        finally:
            connection.close()
        return _to_result(row) if row is not None else None

    def get_result_for_owner(
        self,
        result_id: str,
        owner_id: str,
    ) -> GenerativeResultRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_QUALIFIED_RESULT_COLUMNS} FROM generative_result "
                "JOIN generative_task ON generative_task.id = generative_result.task_id "
                "WHERE generative_result.id = ? AND generative_task.owner_id = ?",
                (result_id, owner_id),
            ).fetchone()
        finally:
            connection.close()
        return _to_result(row) if row is not None else None

    def list_results(self, task_id: str) -> list[GenerativeResultRecord]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                f"SELECT {_RESULT_COLUMNS} FROM generative_result "
                "WHERE task_id = ? ORDER BY result_index, created_at, id",
                (task_id,),
            ).fetchall()
        finally:
            connection.close()
        return [_to_result(row) for row in rows]

    def mark_result_rejected(self, result_id: str) -> bool:
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE generative_result SET status = 'rejected', decided_at = ? "
                "WHERE id = ? AND status = 'candidate'",
                (now, result_id),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def mark_result_accepted(self, result_id: str, revision_id: str) -> bool:
        now = utc_now()
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE generative_result SET status = 'accepted', revision_id = ?, "
                "decided_at = ? WHERE id = ? AND status IN ('candidate', 'accepted')",
                (revision_id, now, result_id),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    def list_purgeable_results(self, cutoff: datetime) -> list[tuple[str, str]]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                "SELECT id, storage_key FROM generative_result "
                "WHERE status IN ('candidate', 'rejected', 'discarded') AND created_at < ? "
                "ORDER BY created_at",
                (_iso(cutoff),),
            ).fetchall()
        finally:
            connection.close()
        return [(str(row["id"]), str(row["storage_key"])) for row in rows]

    def delete_results(self, result_ids: list[str]) -> None:
        if not result_ids:
            return
        placeholders = ", ".join("?" for _ in result_ids)
        connection = connect(self._path)
        try:
            connection.execute(
                f"DELETE FROM generative_result WHERE id IN ({placeholders})",
                result_ids,
            )
        finally:
            connection.close()

    # ----------------------------------------------------------------- assets

    def create_generated_asset(self, asset: GeneratedAssetRecord) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "INSERT INTO generated_asset "
                f"({_ASSET_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset.id,
                    asset.image_id,
                    asset.task_id,
                    asset.result_id,
                    asset.kind,
                    asset.storage_key,
                    asset.sha256,
                    asset.width,
                    asset.height,
                    asset.bytes,
                    asset.mime_type,
                    _iso(asset.created_at),
                    _iso(asset.deleted_at),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateGeneratedAssetError("duplicate generated asset") from exc
            raise
        finally:
            connection.close()

    def get_generated_asset(self, asset_id: str) -> GeneratedAssetRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_ASSET_COLUMNS} FROM generated_asset WHERE id = ?",
                (asset_id,),
            ).fetchone()
        finally:
            connection.close()
        return _to_asset(row) if row is not None else None

    def get_generated_asset_by_result(self, result_id: str) -> GeneratedAssetRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_ASSET_COLUMNS} FROM generated_asset WHERE result_id = ?",
                (result_id,),
            ).fetchone()
        finally:
            connection.close()
        return _to_asset(row) if row is not None else None

    # ------------------------------------------------------------------ masks

    def create_mask(self, mask: GenerativeMaskRecord) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "INSERT INTO generative_mask "
                f"({_MASK_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mask.id,
                    mask.owner_id,
                    mask.image_id,
                    mask.base_generated_asset_id,
                    mask.kind.value,
                    mask.source.value,
                    mask.coordinate_space,
                    mask.width,
                    mask.height,
                    mask.storage_key,
                    mask.sha256,
                    mask.feather,
                    int(mask.inverted),
                    mask.strokes_json,
                    _iso(mask.created_at),
                    _iso(mask.deleted_at),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateGenerativeTaskError("duplicate mask") from exc
            raise
        finally:
            connection.close()

    def get_mask(self, mask_id: str) -> GenerativeMaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_MASK_COLUMNS} FROM generative_mask WHERE id = ? AND deleted_at IS NULL",
                (mask_id,),
            ).fetchone()
        finally:
            connection.close()
        return _to_mask(row) if row is not None else None

    def get_mask_for_owner(self, mask_id: str, owner_id: str) -> GenerativeMaskRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_MASK_COLUMNS} FROM generative_mask "
                "WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                (mask_id, owner_id),
            ).fetchone()
        finally:
            connection.close()
        return _to_mask(row) if row is not None else None

    def list_masks_for_owner(
        self,
        owner_id: str,
        *,
        image_id: str,
        base_generated_asset_id: str | None,
        limit: int,
        offset: int,
    ) -> list[GenerativeMaskRecord]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                f"SELECT {_MASK_COLUMNS} FROM generative_mask "
                "WHERE owner_id = ? AND image_id = ? AND base_generated_asset_id IS ? "
                "AND deleted_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (owner_id, image_id, base_generated_asset_id, limit, offset),
            ).fetchall()
        finally:
            connection.close()
        return [_to_mask(row) for row in rows]

    def has_active_for_mask(self, mask_id: str) -> bool:
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
        connection = connect(self._path)
        try:
            row = connection.execute(
                "SELECT 1 FROM generative_task WHERE mask_id = ? "
                f"AND status IN ({placeholders}) LIMIT 1",
                (mask_id, *_ACTIVE_STATUSES),
            ).fetchone()
        finally:
            connection.close()
        return row is not None

    def soft_delete_mask(self, mask_id: str, owner_id: str) -> MaskDeletionOutcome:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT id FROM generative_mask "
                    "WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                    (mask_id, owner_id),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return MaskDeletionOutcome(removed=False, referenced=False)
                placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
                active = connection.execute(
                    "SELECT 1 FROM generative_task WHERE mask_id = ? "
                    f"AND status IN ({placeholders}) LIMIT 1",
                    (mask_id, *_ACTIVE_STATUSES),
                ).fetchone()
                if active is not None:
                    connection.rollback()
                    raise MaskInUseError("the mask is used by an active task")
                referenced = (
                    connection.execute(
                        "SELECT 1 FROM generative_task WHERE mask_id = ? LIMIT 1",
                        (mask_id,),
                    ).fetchone()
                    is not None
                )
                connection.execute(
                    "UPDATE generative_mask SET deleted_at = ? "
                    "WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                    (utc_now(), mask_id, owner_id),
                )
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        return MaskDeletionOutcome(removed=True, referenced=referenced)


__all__ = [
    "DuplicateGeneratedAssetError",
    "DuplicateGenerativeTaskError",
    "MaskDeletionOutcome",
    "MaskInUseError",
    "RetryNotAllowedError",
    "SqliteGenerativeRepository",
]
