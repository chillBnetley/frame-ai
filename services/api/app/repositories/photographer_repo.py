from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.repositories.db import connect

_PLAN_COLUMNS = (
    "id, image_id, session_id, analysis_id, mode, style_id, style_version, "
    "style_strength, provider, model, prompt_version, is_mock, degraded, "
    "confidence, plan_json, recipe_json, recipe_hash, created_at"
)

_FEEDBACK_COLUMNS = (
    "id, image_id, session_id, plan_id, revision_id, source, action, "
    "changed_paths_json, rubric_json, is_mock, degraded, created_at"
)

# The newest rows a summary scan reads. Feedback is a local, low-volume signal, so
# aggregation happens in Python over this window instead of SQL JSON functions.
MAX_FEEDBACK_SCAN = 500


@dataclass(frozen=True, slots=True)
class PhotographerPlanRecord:
    id: str
    image_id: str
    session_id: str
    analysis_id: str
    mode: str
    style_id: str | None
    style_version: str | None
    style_strength: float | None
    provider: str
    model: str
    prompt_version: str
    is_mock: bool
    degraded: bool
    confidence: float | None
    plan_json: str
    recipe_json: str
    recipe_hash: str
    created_at: datetime


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _normalize_id(value: str) -> str:
    return str(UUID(value)).lower()


@dataclass(frozen=True, slots=True)
class PhotographerFeedbackRecord:
    id: str
    image_id: str
    session_id: str
    plan_id: str | None
    revision_id: str | None
    source: str | None
    action: str
    changed_paths: tuple[str, ...]
    rubric: dict[str, int] | None
    is_mock: bool
    degraded: bool
    created_at: datetime


def _to_record(row: sqlite3.Row) -> PhotographerPlanRecord:
    data = dict(row)
    data["is_mock"] = bool(data["is_mock"])
    data["degraded"] = bool(data["degraded"])
    data["created_at"] = _parse_time(str(data["created_at"]))
    return PhotographerPlanRecord(**data)


class SqlitePhotographerPlanRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def create(self, record: PhotographerPlanRecord) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "INSERT INTO photographer_plan "
                f"({_PLAN_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _normalize_id(record.id),
                    _normalize_id(record.image_id),
                    _normalize_id(record.session_id),
                    _normalize_id(record.analysis_id),
                    record.mode,
                    record.style_id,
                    record.style_version,
                    record.style_strength,
                    record.provider,
                    record.model,
                    record.prompt_version,
                    int(record.is_mock),
                    int(record.degraded),
                    record.confidence,
                    record.plan_json,
                    record.recipe_json,
                    record.recipe_hash,
                    _iso(record.created_at),
                ),
            )
        finally:
            connection.close()

    def get(self, plan_id: str) -> PhotographerPlanRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_PLAN_COLUMNS} FROM photographer_plan WHERE id = ?",
                (_normalize_id(plan_id),),
            ).fetchone()
        finally:
            connection.close()
        return _to_record(row) if row is not None else None

    def latest_for_session(self, session_id: str) -> PhotographerPlanRecord | None:
        return self._latest("session_id", session_id)

    def latest_for_image(self, image_id: str) -> PhotographerPlanRecord | None:
        return self._latest("image_id", image_id)

    def list_for_session(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[PhotographerPlanRecord]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                f"SELECT {_PLAN_COLUMNS} FROM photographer_plan "
                "WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (_normalize_id(session_id), limit),
            ).fetchall()
        finally:
            connection.close()
        return [_to_record(row) for row in rows]

    def _latest(self, column: str, value: str) -> PhotographerPlanRecord | None:
        if column not in {"session_id", "image_id"}:
            raise ValueError("unsupported plan lookup column")
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_PLAN_COLUMNS} FROM photographer_plan "
                f"WHERE {column} = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (_normalize_id(value),),
            ).fetchone()
        finally:
            connection.close()
        return _to_record(row) if row is not None else None


def _to_feedback_record(row: sqlite3.Row) -> PhotographerFeedbackRecord:
    data = dict(row)
    data["changed_paths"] = tuple(json.loads(str(data.pop("changed_paths_json"))))
    stored_rubric = data.pop("rubric_json")
    data["rubric"] = None if stored_rubric is None else dict(json.loads(str(stored_rubric)))
    data["is_mock"] = bool(data["is_mock"])
    data["degraded"] = bool(data["degraded"])
    data["created_at"] = _parse_time(str(data["created_at"]))
    return PhotographerFeedbackRecord(**data)


class SqlitePhotographerFeedbackRepository:
    """What the user did with a proposal. Holds no image data and no instruction text."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, record: PhotographerFeedbackRecord) -> PhotographerFeedbackRecord:
        """Upsert one decision and hand back the row that ends up stored.

        A rating re-annotates the accept it belongs to, so the id the caller
        receives can be the id of the row that was already there.
        """
        connection = connect(self._path)
        try:
            row = connection.execute(
                "INSERT INTO photographer_feedback "
                f"({_FEEDBACK_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (plan_id, action) DO UPDATE SET "
                "revision_id = excluded.revision_id, "
                "source = excluded.source, "
                "changed_paths_json = excluded.changed_paths_json, "
                "rubric_json = excluded.rubric_json, "
                "is_mock = excluded.is_mock, "
                "degraded = excluded.degraded "
                f"RETURNING {_FEEDBACK_COLUMNS}",
                (
                    _normalize_id(record.id),
                    _normalize_id(record.image_id),
                    _normalize_id(record.session_id),
                    None if record.plan_id is None else _normalize_id(record.plan_id),
                    None if record.revision_id is None else _normalize_id(record.revision_id),
                    record.source,
                    record.action,
                    json.dumps(list(record.changed_paths)),
                    None if record.rubric is None else json.dumps(record.rubric),
                    int(record.is_mock),
                    int(record.degraded),
                    _iso(record.created_at),
                ),
            ).fetchone()
            if row is None:
                raise sqlite3.Error("the feedback row could not be read back")
            return _to_feedback_record(row)
        finally:
            connection.close()

    def get(self, feedback_id: str) -> PhotographerFeedbackRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_FEEDBACK_COLUMNS} FROM photographer_feedback WHERE id = ?",
                (_normalize_id(feedback_id),),
            ).fetchone()
        finally:
            connection.close()
        return _to_feedback_record(row) if row is not None else None

    def list_recent(
        self,
        *,
        session_id: str | None = None,
        image_id: str | None = None,
        plan_id: str | None = None,
        limit: int = MAX_FEEDBACK_SCAN,
    ) -> list[PhotographerFeedbackRecord]:
        filters = {"session_id": session_id, "image_id": image_id, "plan_id": plan_id}
        selected = {column: value for column, value in filters.items() if value is not None}
        conditions = [f"{column} = ?" for column in selected]
        clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        parameters = (*(_normalize_id(str(value)) for value in selected.values()), limit)
        connection = connect(self._path)
        try:
            rows = connection.execute(
                f"SELECT {_FEEDBACK_COLUMNS} FROM photographer_feedback{clause} "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                parameters,
            ).fetchall()
        finally:
            connection.close()
        return [_to_feedback_record(row) for row in rows]

    def delete(self, feedback_id: str) -> bool:
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "DELETE FROM photographer_feedback WHERE id = ?",
                (_normalize_id(feedback_id),),
            )
            return cursor.rowcount > 0
        finally:
            connection.close()


__all__ = [
    "MAX_FEEDBACK_SCAN",
    "PhotographerFeedbackRecord",
    "PhotographerPlanRecord",
    "SqlitePhotographerFeedbackRepository",
    "SqlitePhotographerPlanRepository",
]
