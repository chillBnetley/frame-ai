from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models.personal_style import PersonalStyleDefinition, PersonalStyleProfile
from app.models.style_evolution import (
    StyleEvolutionRecord,
    StyleEvolutionStatus,
    StyleFeedbackRecord,
    StyleFeedbackScope,
    StyleFeedbackType,
)
from app.repositories.db import connect
from app.repositories.personal_style_repo import PersonalStyleNotFoundError


@dataclass(frozen=True, slots=True)
class FeedbackRow:
    id: str
    style_id: str
    style_version: str
    feedback_type: StyleFeedbackType
    note: str | None
    scope: StyleFeedbackScope
    applied_version: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvolutionRow:
    id: str
    style_id: str
    base_version: str
    new_version: str | None
    feedback_ids: tuple[str, ...]
    reason: str
    summary: str
    candidate: PersonalStyleProfile
    definition: PersonalStyleDefinition
    status: StyleEvolutionStatus
    created_at: datetime
    confirmed_at: datetime | None


def _parse_time(value: object) -> datetime:
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _feedback_from_row(row: sqlite3.Row) -> FeedbackRow:
    return FeedbackRow(
        id=str(row["id"]),
        style_id=str(row["style_id"]),
        style_version=str(row["style_version"]),
        feedback_type=StyleFeedbackType(str(row["feedback_type"])),
        note=None if row["note"] is None else str(row["note"]),
        scope=StyleFeedbackScope(str(row["scope"])),
        applied_version=None if row["applied_version"] is None else str(row["applied_version"]),
        created_at=_parse_time(row["created_at"]),
    )


def _evolution_from_row(row: sqlite3.Row) -> EvolutionRow:
    return EvolutionRow(
        id=str(row["id"]),
        style_id=str(row["style_id"]),
        base_version=str(row["base_version"]),
        new_version=None if row["new_version"] is None else str(row["new_version"]),
        feedback_ids=tuple(str(item) for item in json.loads(str(row["feedback_ids_json"]))),
        reason=str(row["reason"]),
        summary=str(row["summary"]),
        candidate=PersonalStyleProfile.model_validate_json(str(row["candidate_json"])),
        definition=PersonalStyleDefinition.model_validate_json(str(row["definition_json"])),
        status=StyleEvolutionStatus(str(row["status"])),
        created_at=_parse_time(row["created_at"]),
        confirmed_at=None if row["confirmed_at"] is None else _parse_time(row["confirmed_at"]),
    )


class SqliteStyleEvolutionRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def add_feedback(
        self,
        feedback: StyleFeedbackRecord,
        *,
        owner_id: str,
    ) -> None:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_owned(connection, feedback.style_id, owner_id)
            connection.execute(
                "INSERT INTO personal_style_feedback "
                "(id, style_id, style_version, feedback_type, note, scope, "
                " applied_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(feedback.id),
                    feedback.style_id,
                    feedback.style_version,
                    feedback.feedback_type.value,
                    feedback.note,
                    feedback.scope.value,
                    feedback.applied_version,
                    _iso(feedback.created_at),
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_feedback(
        self,
        style_id: str,
        *,
        owner_id: str,
        scope: StyleFeedbackScope | None = None,
        unapplied_only: bool = False,
    ) -> list[FeedbackRow]:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return []
            clauses = ["style_id = ?"]
            params: list[object] = [style_id]
            if scope is not None:
                clauses.append("scope = ?")
                params.append(scope.value)
            if unapplied_only:
                clauses.append("applied_version IS NULL")
            rows = connection.execute(
                "SELECT * FROM personal_style_feedback "
                f"WHERE {' AND '.join(clauses)} ORDER BY created_at, id",
                params,
            ).fetchall()
        finally:
            connection.close()
        return [_feedback_from_row(row) for row in rows]

    def get_feedback(
        self,
        style_id: str,
        feedback_id: str,
        *,
        owner_id: str,
    ) -> FeedbackRow | None:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return None
            row = connection.execute(
                "SELECT * FROM personal_style_feedback WHERE id = ? AND style_id = ?",
                (feedback_id, style_id),
            ).fetchone()
        finally:
            connection.close()
        return _feedback_from_row(row) if row is not None else None

    def delete_feedback(
        self,
        style_id: str,
        feedback_id: str,
        *,
        owner_id: str,
    ) -> bool:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_owned(connection, style_id, owner_id)
            cursor = connection.execute(
                "DELETE FROM personal_style_feedback "
                "WHERE id = ? AND style_id = ? AND applied_version IS NULL",
                (feedback_id, style_id),
            )
            connection.commit()
            return cursor.rowcount > 0
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_feedbacks_applied(
        self,
        style_id: str,
        feedback_ids: tuple[str, ...],
        *,
        owner_id: str,
        applied_version: str,
    ) -> None:
        if not feedback_ids:
            return
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_owned(connection, style_id, owner_id)
            for feedback_id in feedback_ids:
                connection.execute(
                    "UPDATE personal_style_feedback SET applied_version = ? "
                    "WHERE id = ? AND style_id = ? AND applied_version IS NULL",
                    (applied_version, feedback_id, style_id),
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add_evolution(
        self,
        evolution: StyleEvolutionRecord,
        *,
        owner_id: str,
    ) -> None:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_owned(connection, evolution.style_id, owner_id)
            connection.execute(
                "INSERT INTO personal_style_evolution "
                "(id, style_id, base_version, new_version, feedback_ids_json, reason, "
                " summary, candidate_json, definition_json, status, created_at, confirmed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(evolution.id),
                    evolution.style_id,
                    evolution.base_version,
                    evolution.new_version,
                    json.dumps([str(item) for item in evolution.feedback_ids]),
                    evolution.reason,
                    evolution.summary,
                    evolution.candidate.model_dump_json(by_alias=True),
                    evolution.definition.model_dump_json(by_alias=True),
                    evolution.status.value,
                    _iso(evolution.created_at),
                    None if evolution.confirmed_at is None else _iso(evolution.confirmed_at),
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_evolution(
        self,
        style_id: str,
        evolution_id: str,
        *,
        owner_id: str,
    ) -> EvolutionRow | None:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return None
            row = connection.execute(
                "SELECT * FROM personal_style_evolution WHERE id = ? AND style_id = ?",
                (evolution_id, style_id),
            ).fetchone()
        finally:
            connection.close()
        return _evolution_from_row(row) if row is not None else None

    def list_evolutions(
        self,
        style_id: str,
        *,
        owner_id: str,
    ) -> list[EvolutionRow]:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return []
            rows = connection.execute(
                "SELECT * FROM personal_style_evolution WHERE style_id = ? "
                "ORDER BY created_at DESC, rowid DESC",
                (style_id,),
            ).fetchall()
        finally:
            connection.close()
        return [_evolution_from_row(row) for row in rows]

    def confirm_evolution(
        self,
        style_id: str,
        evolution_id: str,
        *,
        owner_id: str,
        new_version: str,
        confirmed_at: datetime,
    ) -> bool:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_owned(connection, style_id, owner_id)
            cursor = connection.execute(
                "UPDATE personal_style_evolution "
                "SET status = 'confirmed', new_version = ?, confirmed_at = ? "
                "WHERE id = ? AND style_id = ? AND status = 'proposed'",
                (new_version, _iso(confirmed_at), evolution_id, style_id),
            )
            connection.commit()
            return cursor.rowcount > 0
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def discard_evolution(
        self,
        style_id: str,
        evolution_id: str,
        *,
        owner_id: str,
    ) -> bool:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_owned(connection, style_id, owner_id)
            cursor = connection.execute(
                "UPDATE personal_style_evolution SET status = 'discarded' "
                "WHERE id = ? AND style_id = ? AND status = 'proposed'",
                (evolution_id, style_id),
            )
            connection.commit()
            return cursor.rowcount > 0
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _owns(connection: sqlite3.Connection, style_id: str, owner_id: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM personal_style WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
            (style_id, owner_id),
        ).fetchone()
        return row is not None

    @classmethod
    def _require_owned(
        cls,
        connection: sqlite3.Connection,
        style_id: str,
        owner_id: str,
    ) -> None:
        if not cls._owns(connection, style_id, owner_id):
            raise PersonalStyleNotFoundError(
                f"personal style '{style_id}' does not exist for this owner"
            )


__all__ = [
    "EvolutionRow",
    "FeedbackRow",
    "SqliteStyleEvolutionRepository",
]
