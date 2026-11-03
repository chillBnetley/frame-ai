from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from PIL import Image

from app.core.config import Settings
from app.imaging.decoder import display_dimensions
from app.repositories.db import connect, initialize_database, utc_now
from app.repositories.image_registry import ImageAssetRecord, ImageRegistry

logger = logging.getLogger("frame_ai.import")

ORIENTATION_TAG = 0x0112


@dataclass(frozen=True)
class SkippedRecord:
    image_id: str
    reason: str


@dataclass(frozen=True)
class ImportReport:
    registry_found: bool
    imported: int
    already_present: int
    skipped: tuple[SkippedRecord, ...]
    backup_path: Path | None


def _read_orientation(path: Path) -> int:
    with Image.open(path) as image:
        value = image.getexif().get(ORIENTATION_TAG, 1)
    if isinstance(value, int) and 1 <= value <= 8:
        return value
    return 1


def _resolve_stored_file(settings: Settings, storage_key: str) -> Path | None:
    data_dir = settings.data_dir.resolve()
    candidate = (data_dir / storage_key).resolve()
    if not candidate.is_relative_to(data_dir):
        return None
    return candidate


def _backup_path(registry_path: Path) -> Path:
    candidate = registry_path.with_name(f"{registry_path.name}.imported.bak")
    if not candidate.exists():
        return candidate
    stamp = utc_now().replace(":", "").replace("-", "").replace(".", "")
    return registry_path.with_name(f"{registry_path.name}.{stamp}.imported.bak")


def import_registry(
    settings: Settings,
    *,
    registry_path: Path | None = None,
    backup: bool = True,
) -> ImportReport:
    path = registry_path or settings.registry_path
    if not path.exists():
        return ImportReport(False, 0, 0, (), None)

    registry = ImageRegistry(path)
    initialize_database(settings.database_path)
    skipped: list[SkippedRecord] = []
    imported = 0
    already_present = 0

    connection = connect(settings.database_path)
    try:
        for image_id in registry.list_ids():
            record = registry.get(image_id)
            if record is None:
                skipped.append(SkippedRecord(image_id, "record disappeared"))
                continue
            stored = _resolve_stored_file(settings, record.storage_key)
            if stored is None or not stored.is_file():
                skipped.append(SkippedRecord(image_id, "stored file missing"))
                continue
            data = stored.read_bytes()
            if hashlib.sha256(data).hexdigest() != record.sha256:
                skipped.append(SkippedRecord(image_id, "sha256 mismatch"))
                continue
            try:
                orientation = _read_orientation(stored)
            except (OSError, ValueError, SyntaxError):
                skipped.append(SkippedRecord(image_id, "image header unreadable"))
                continue

            width, height = display_dimensions(record.width, record.height, orientation)
            migrated = ImageAssetRecord(
                id=record.id,
                original_name=record.original_name,
                storage_key=record.storage_key,
                mime_type=record.mime_type,
                width=width,
                height=height,
                exif_orientation=orientation,
                bytes=len(data),
                sha256=record.sha256,
                created_at=record.created_at.astimezone(UTC),
            )
            try:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO image_asset "
                    "(id, original_name, storage_key, mime_type, width, height, "
                    " exif_orientation, bytes, sha256, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        migrated.id,
                        migrated.original_name,
                        migrated.storage_key,
                        migrated.mime_type,
                        migrated.width,
                        migrated.height,
                        migrated.exif_orientation,
                        migrated.bytes,
                        migrated.sha256,
                        migrated.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                skipped.append(SkippedRecord(image_id, f"insert failed: {exc}"))
                continue
            if cursor.rowcount == 1:
                imported += 1
            else:
                already_present += 1
    finally:
        connection.close()

    destination: Path | None = None
    if backup:
        destination = _backup_path(path)
        os.replace(path, destination)

    report = ImportReport(True, imported, already_present, tuple(skipped), destination)
    logger.info(
        "registry_import imported=%s already_present=%s skipped=%s backup=%s",
        report.imported,
        report.already_present,
        len(report.skipped),
        report.backup_path,
    )
    return report


def maybe_import_legacy_registry(settings: Settings) -> ImportReport | None:
    if not settings.registry_path.exists():
        return None
    try:
        return import_registry(settings)
    except Exception:
        logger.exception("legacy_registry_import_failed path=%s", settings.registry_path)
        return None
