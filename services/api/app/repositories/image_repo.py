from __future__ import annotations

import sqlite3
from pathlib import Path

from app.repositories.db import connect
from app.repositories.image_registry import ImageAssetRecord

_RECORD_COLUMNS = (
    "id, original_name, storage_key, mime_type, width, height, "
    "exif_orientation, bytes, sha256, created_at"
)


def _to_record(row: sqlite3.Row) -> ImageAssetRecord:
    return ImageAssetRecord.model_validate(dict(row))


class SqliteImageRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def add(self, record: ImageAssetRecord) -> None:
        connection = connect(self._path)
        try:
            connection.execute(
                "INSERT INTO image_asset "
                "(id, original_name, storage_key, mime_type, width, height, "
                " exif_orientation, bytes, sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.original_name,
                    record.storage_key,
                    record.mime_type,
                    record.width,
                    record.height,
                    record.exif_orientation,
                    record.bytes,
                    record.sha256,
                    record.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate or invalid image record") from exc
        finally:
            connection.close()

    def get(self, image_id: str) -> ImageAssetRecord | None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                f"SELECT {_RECORD_COLUMNS} FROM image_asset WHERE id = ?",
                (image_id.lower(),),
            ).fetchone()
        finally:
            connection.close()
        return _to_record(row) if row is not None else None

    def exists(self, image_id: str) -> bool:
        return self.get(image_id) is not None

    def list_ids(self) -> list[str]:
        connection = connect(self._path)
        try:
            rows = connection.execute("SELECT id FROM image_asset ORDER BY id").fetchall()
        finally:
            connection.close()
        return [str(row["id"]) for row in rows]
