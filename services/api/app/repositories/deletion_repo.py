from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.repositories.db import connect, utc_now

DeletionStatus = Literal["deleted", "tombstoned", "missing"]


@dataclass(frozen=True)
class ImageDeletionRecord:
    status: DeletionStatus
    storage_key: str | None = None
    sha256: str | None = None
    session_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionDeletionRecord:
    status: DeletionStatus
    image_id: str | None = None


@dataclass(frozen=True)
class StoredImageRecord:
    id: str
    storage_key: str
    sha256: str


class SqliteDeletionRepository:
    """Hard-delete an image or a session together with its dependent rows.

    ``edit_session.image_id`` is ``ON DELETE RESTRICT``, so the sessions must
    go before the image; every other child table cascades from either the
    session or the image. The whole cascade runs in one ``BEGIN IMMEDIATE``
    transaction so a failure never leaves a partly deleted aggregate.

    A small ``deleted_resource`` tombstone keeps repeated DELETEs idempotent
    (204) without keeping any of the removed content.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def delete_image(self, image_id: str) -> ImageDeletionRecord:
        normalized = _normalize_id(image_id)
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT storage_key, sha256 FROM image_asset WHERE id = ?",
                    (normalized,),
                ).fetchone()
                if row is None:
                    tombstoned = self._tombstoned(connection, "image", normalized)
                    connection.rollback()
                    return ImageDeletionRecord(status="tombstoned" if tombstoned else "missing")
                session_ids = tuple(
                    str(item["id"])
                    for item in connection.execute(
                        "SELECT id FROM edit_session WHERE image_id = ? ORDER BY id",
                        (normalized,),
                    ).fetchall()
                )
                connection.execute(
                    "DELETE FROM edit_session WHERE image_id = ?",
                    (normalized,),
                )
                self._detach_personal_references(connection, normalized)
                connection.execute("DELETE FROM image_asset WHERE id = ?", (normalized,))
                self._remember(connection, "image", normalized)
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        return ImageDeletionRecord(
            status="deleted",
            storage_key=str(row["storage_key"]),
            sha256=str(row["sha256"]),
            session_ids=session_ids,
        )

    def delete_session(self, session_id: str) -> SessionDeletionRecord:
        normalized = _normalize_id(session_id)
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT image_id FROM edit_session WHERE id = ?",
                    (normalized,),
                ).fetchone()
                if row is None:
                    tombstoned = self._tombstoned(connection, "session", normalized)
                    connection.rollback()
                    return SessionDeletionRecord(status="tombstoned" if tombstoned else "missing")
                connection.execute("DELETE FROM edit_session WHERE id = ?", (normalized,))
                self._remember(connection, "session", normalized)
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()
        return SessionDeletionRecord(status="deleted", image_id=str(row["image_id"]))

    def sha_is_shared(self, sha256: str) -> bool:
        """True when another image still references the same content digest."""
        connection = connect(self._path)
        try:
            row = connection.execute(
                "SELECT 1 FROM image_asset WHERE sha256 = ? LIMIT 1",
                (sha256,),
            ).fetchone()
        finally:
            connection.close()
        return row is not None

    def session_ids_for_image(self, image_id: str) -> tuple[str, ...]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                "SELECT id FROM edit_session WHERE image_id = ? ORDER BY id",
                (image_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(str(row["id"]) for row in rows)

    def list_images(self) -> list[StoredImageRecord]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                "SELECT id, storage_key, sha256 FROM image_asset ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        return [
            StoredImageRecord(
                id=str(row["id"]),
                storage_key=str(row["storage_key"]),
                sha256=str(row["sha256"]),
            )
            for row in rows
        ]

    @staticmethod
    def _detach_personal_references(connection: sqlite3.Connection, image_id: str) -> None:
        """Keep the personal style but drop per-photo evidence of a deleted image."""

        connection.execute(
            "DELETE FROM personal_style_photo_feature "
            "WHERE reference_id IN ("
            "  SELECT id FROM personal_style_reference WHERE image_id = ?"
            ")",
            (image_id,),
        )
        connection.execute(
            "UPDATE personal_style_reference SET status = 'missing' WHERE image_id = ?",
            (image_id,),
        )

    @staticmethod
    def _tombstoned(connection: sqlite3.Connection, kind: str, resource_id: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM deleted_resource WHERE kind = ? AND id = ?",
            (kind, resource_id),
        ).fetchone()
        return row is not None

    @staticmethod
    def _remember(connection: sqlite3.Connection, kind: str, resource_id: str) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO deleted_resource (kind, id, deleted_at) VALUES (?, ?, ?)",
            (kind, resource_id, utc_now()),
        )


def _normalize_id(value: str) -> str:
    return str(UUID(value))


__all__ = [
    "ImageDeletionRecord",
    "SessionDeletionRecord",
    "SqliteDeletionRepository",
    "StoredImageRecord",
]
