from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.repositories.db import connect, utc_now


class SessionNotFoundError(LookupError):
    pass


class RevisionNotFoundError(LookupError):
    pass


class RevisionConflictError(RuntimeError):
    def __init__(self, active_revision_id: str) -> None:
        super().__init__(f"parent revision does not match active revision {active_revision_id}")
        self.active_revision_id = active_revision_id


class IdempotencyKeyReuseError(RuntimeError):
    def __init__(self, revision_id: str) -> None:
        super().__init__(f"idempotency key already used by revision {revision_id}")
        self.revision_id = revision_id


@dataclass(frozen=True)
class SessionRecord:
    id: str
    image_id: str
    status: str
    active_revision_id: str
    head_revision_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RevisionRecord:
    id: str
    session_id: str
    parent_id: str | None
    revision_no: int
    recipe_json: str
    recipe_hash: str
    source: str
    idempotency_key: str | None
    created_at: datetime


_SESSION_COLUMNS = (
    "id, image_id, status, active_revision_id, head_revision_id, created_at, updated_at"
)
_REVISION_COLUMNS = (
    "id, session_id, parent_id, revision_no, recipe_json, recipe_hash, "
    "source, idempotency_key, created_at"
)
_REDO_QUERY = """
WITH RECURSIVE ancestors(id, parent_id) AS (
    SELECT id, parent_id FROM edit_revision WHERE id = ?
    UNION
    SELECT revision.id, revision.parent_id
    FROM edit_revision AS revision
    JOIN ancestors ON revision.id = ancestors.parent_id
)
SELECT id FROM ancestors WHERE parent_id = ? LIMIT 1
"""


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _to_session(row: sqlite3.Row) -> SessionRecord:
    active = row["active_revision_id"]
    head = row["head_revision_id"]
    if active is None or head is None:
        raise RuntimeError(f"session {row['id']} is missing its active or head revision")
    return SessionRecord(
        id=str(row["id"]),
        image_id=str(row["image_id"]),
        status=str(row["status"]),
        active_revision_id=str(active),
        head_revision_id=str(head),
        created_at=_parse_time(str(row["created_at"])),
        updated_at=_parse_time(str(row["updated_at"])),
    )


def _to_revision(row: sqlite3.Row) -> RevisionRecord:
    parent_id = row["parent_id"]
    idempotency_key = row["idempotency_key"]
    return RevisionRecord(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        parent_id=str(parent_id) if parent_id is not None else None,
        revision_no=int(row["revision_no"]),
        recipe_json=str(row["recipe_json"]),
        recipe_hash=str(row["recipe_hash"]),
        source=str(row["source"]),
        idempotency_key=str(idempotency_key) if idempotency_key is not None else None,
        created_at=_parse_time(str(row["created_at"])),
    )


class SqliteSessionRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def create_session(
        self,
        image_id: str,
        *,
        recipe_json: str,
        recipe_hash: str,
    ) -> tuple[SessionRecord, RevisionRecord]:
        session_id = str(uuid4())
        revision_id = str(uuid4())
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO edit_session "
                    "(id, image_id, status, active_revision_id, head_revision_id, "
                    " created_at, updated_at) "
                    "VALUES (?, ?, 'active', NULL, NULL, ?, ?)",
                    (session_id, image_id.lower(), now, now),
                )
                connection.execute(
                    "INSERT INTO edit_revision "
                    "(id, session_id, parent_id, revision_no, recipe_json, recipe_hash, "
                    " source, idempotency_key, created_at) "
                    "VALUES (?, ?, NULL, 1, ?, ?, 'initial', NULL, ?)",
                    (revision_id, session_id, recipe_json, recipe_hash, now),
                )
                connection.execute(
                    "UPDATE edit_session SET active_revision_id = ?, head_revision_id = ? "
                    "WHERE id = ?",
                    (revision_id, revision_id, session_id),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()
        return self.get(session_id), self.get_revision(session_id, revision_id)

    def get(self, session_id: str) -> SessionRecord:
        normalized = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_SESSION_COLUMNS} FROM edit_session WHERE id = ?",
                (normalized,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise SessionNotFoundError(normalized)
        return _to_session(row)

    def get_revision(self, session_id: str, revision_id: str) -> RevisionRecord:
        normalized_session = _normalize_id(session_id)
        normalized_revision = _normalize_id(revision_id)
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_REVISION_COLUMNS} FROM edit_revision WHERE id = ? AND session_id = ?",
                (normalized_revision, normalized_session),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise RevisionNotFoundError(normalized_revision)
        return _to_revision(row)

    def add_revision(
        self,
        session_id: str,
        *,
        parent_id: str,
        recipe_json: str,
        recipe_hash: str,
        source: str,
        idempotency_key: str | None,
    ) -> tuple[RevisionRecord, bool]:
        normalized_session = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                session = self._require_session(connection, normalized_session)
                if idempotency_key is not None:
                    existing = connection.execute(
                        f"SELECT {_REVISION_COLUMNS} FROM edit_revision "
                        "WHERE session_id = ? AND idempotency_key = ?",
                        (normalized_session, idempotency_key),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["recipe_hash"]) != recipe_hash
                            or str(existing["parent_id"] or "").lower() != parent_id.lower()
                        ):
                            raise IdempotencyKeyReuseError(str(existing["id"]))
                        connection.rollback()
                        return _to_revision(existing), True

                if parent_id.lower() != session.active_revision_id:
                    raise RevisionConflictError(session.active_revision_id)

                revision_id = str(uuid4())
                now = utc_now()
                next_number = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(revision_no), 0) + 1 AS next_no "
                        "FROM edit_revision WHERE session_id = ?",
                        (normalized_session,),
                    ).fetchone()["next_no"]
                )
                connection.execute(
                    "INSERT INTO edit_revision "
                    "(id, session_id, parent_id, revision_no, recipe_json, recipe_hash, "
                    " source, idempotency_key, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        revision_id,
                        normalized_session,
                        parent_id.lower(),
                        next_number,
                        recipe_json,
                        recipe_hash,
                        source,
                        idempotency_key,
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE edit_session SET active_revision_id = ?, head_revision_id = ?, "
                    "updated_at = ? WHERE id = ?",
                    (revision_id, revision_id, now, normalized_session),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()
        return self.get_revision(normalized_session, revision_id), False

    def undo(self, session_id: str, expected_revision_id: str | None = None) -> str | None:
        """Move active to the parent; return the new active id or None if at the root."""
        normalized_session = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                session = self._require_session(connection, normalized_session)
                if (
                    expected_revision_id is not None
                    and expected_revision_id.lower() != session.active_revision_id
                ):
                    raise RevisionConflictError(session.active_revision_id)
                active = self._revision_row(connection, session.active_revision_id)
                parent_id = active["parent_id"]
                if parent_id is None:
                    connection.rollback()
                    return None
                connection.execute(
                    "UPDATE edit_session SET active_revision_id = ?, updated_at = ? WHERE id = ?",
                    (str(parent_id), utc_now(), normalized_session),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()
        return str(parent_id)

    def redo(self, session_id: str) -> str | None:
        """Move active one step toward head; return the new active id or None."""
        normalized_session = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                session = self._require_session(connection, normalized_session)
                row = connection.execute(
                    _REDO_QUERY,
                    (session.head_revision_id, session.active_revision_id),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return None
                target = str(row["id"])
                connection.execute(
                    "UPDATE edit_session SET active_revision_id = ?, updated_at = ? WHERE id = ?",
                    (target, utc_now(), normalized_session),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()
        return target

    def activate(self, session_id: str, revision_id: str) -> None:
        normalized_session = _normalize_id(session_id)
        normalized_revision = _normalize_id(revision_id)
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_session(connection, normalized_session)
                row = connection.execute(
                    "SELECT id FROM edit_revision WHERE id = ? AND session_id = ?",
                    (normalized_revision, normalized_session),
                ).fetchone()
                if row is None:
                    raise RevisionNotFoundError(normalized_revision)
                connection.execute(
                    "UPDATE edit_session SET active_revision_id = ?, updated_at = ? WHERE id = ?",
                    (normalized_revision, utc_now(), normalized_session),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()

    def reset(
        self,
        session_id: str,
        *,
        default_recipe_json: str,
        default_recipe_hash: str,
    ) -> bool:
        """Create a reset revision unless the active recipe already is the default."""
        normalized_session = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                session = self._require_session(connection, normalized_session)
                active = self._revision_row(connection, session.active_revision_id)
                if str(active["recipe_hash"]) == default_recipe_hash:
                    connection.rollback()
                    return False
                now = utc_now()
                next_number = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(revision_no), 0) + 1 AS next_no "
                        "FROM edit_revision WHERE session_id = ?",
                        (normalized_session,),
                    ).fetchone()["next_no"]
                )
                revision_id = str(uuid4())
                connection.execute(
                    "INSERT INTO edit_revision "
                    "(id, session_id, parent_id, revision_no, recipe_json, recipe_hash, "
                    " source, idempotency_key, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'reset', NULL, ?)",
                    (
                        revision_id,
                        normalized_session,
                        session.active_revision_id,
                        next_number,
                        default_recipe_json,
                        default_recipe_hash,
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE edit_session SET active_revision_id = ?, head_revision_id = ?, "
                    "updated_at = ? WHERE id = ?",
                    (revision_id, revision_id, now, normalized_session),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()
        return True

    def can_redo(self, session_id: str, *, active_revision_id: str, head_revision_id: str) -> bool:
        normalized_session = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            row = connection.execute(
                _REDO_QUERY,
                (head_revision_id, active_revision_id),
            ).fetchone()
            if row is None:
                return False
            owner = connection.execute(
                "SELECT session_id FROM edit_revision WHERE id = ?",
                (str(row["id"]),),
            ).fetchone()
        finally:
            connection.close()
        return owner is not None and str(owner["session_id"]) == normalized_session

    def list_revisions(
        self,
        session_id: str,
        *,
        limit: int,
        cursor: int | None = None,
    ) -> tuple[list[RevisionRecord], int | None]:
        normalized_session = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            row = connection.execute(
                "SELECT id FROM edit_session WHERE id = ?",
                (normalized_session,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(normalized_session)
            params: list[object] = [normalized_session]
            where = "session_id = ?"
            if cursor is not None:
                where += " AND revision_no < ?"
                params.append(cursor)
            params.append(limit + 1)
            rows = connection.execute(
                f"SELECT {_REVISION_COLUMNS} FROM edit_revision WHERE {where} "
                "ORDER BY revision_no DESC LIMIT ?",
                params,
            ).fetchall()
        finally:
            connection.close()
        records = [_to_revision(item) for item in rows[:limit]]
        next_cursor = records[-1].revision_no if len(rows) > limit else None
        return records, next_cursor

    @staticmethod
    def _require_session(connection: sqlite3.Connection, session_id: str) -> SessionRecord:
        row = connection.execute(
            f"SELECT {_SESSION_COLUMNS} FROM edit_session WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)
        return _to_session(row)

    @staticmethod
    def _revision_row(connection: sqlite3.Connection, revision_id: str) -> sqlite3.Row:
        row = connection.execute(
            f"SELECT {_REVISION_COLUMNS} FROM edit_revision WHERE id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise RevisionNotFoundError(revision_id)
        return row  # type: ignore[no-any-return]


def _normalize_id(value: str) -> str:
    return str(UUID(value))
