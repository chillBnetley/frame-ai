from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

BACKUP_FORMAT = "frame-ai-backup/1"
MANIFEST_NAME = "manifest.json"
DATABASE_DEFAULT = "frame.db"
CONFIG_FILES = ("provider-settings.json", "provider-master-key", "onboarding.json")
CORE_DIRS = ("originals", "masks", "generated", "generative/results")
OPTIONAL_DIRS = {"previews": "tmp/previews", "models": "models"}
COUNT_TABLES = (
    "image_asset",
    "edit_session",
    "edit_revision",
    "analysis_task",
    "photographer_plan",
    "photographer_feedback",
    "generative_task",
    "generated_asset",
    "personal_style",
    "style_profile",
)


class BackupError(RuntimeError):
    """The backup or its verification could not be completed."""


@dataclass(frozen=True)
class BackupEntry:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class BackupReport:
    destination: Path
    entries: tuple[BackupEntry, ...]
    warnings: tuple[str, ...]
    db_version: int | None
    counts: dict[str, int]

    @property
    def total_bytes(self) -> int:
        return sum(entry.bytes for entry in self.entries)


@dataclass(frozen=True)
class VerifyReport:
    ok: bool
    entries: int
    problems: tuple[str, ...]


def create_backup(
    source: Path,
    destination: Path,
    *,
    database_filename: str = DATABASE_DEFAULT,
    include_previews: bool = False,
    include_models: bool = False,
) -> BackupReport:
    """Copy the durable parts of a FRAME AI data directory into ``destination``.

    The SQLite database is copied through the sqlite3 backup API so WAL content
    is included and no writer lock is required. Regenerable previews and
    temporary exports are excluded unless requested; the rotating API token is
    never copied.
    """

    source = source.resolve()
    destination = destination.resolve()
    database = source / database_filename
    if not database.is_file():
        raise BackupError(f"database_missing: {database}")
    if destination.exists():
        raise BackupError(f"destination_exists: {destination}")
    destination.mkdir(parents=True)

    warnings: list[str] = []
    _copy_database(database, destination / database_filename)
    for name in CORE_DIRS:
        _copy_tree(source / name, destination / name)
    if include_previews:
        _copy_tree(source / OPTIONAL_DIRS["previews"], destination / "previews")
    if include_models:
        _copy_tree(source / OPTIONAL_DIRS["models"], destination / "models")
    for name in CONFIG_FILES:
        origin = source / name
        if origin.is_file():
            shutil.copy2(origin, destination / name)

    has_settings = (source / "provider-settings.json").is_file()
    has_master_key = (source / "provider-master-key").is_file()
    if has_settings and not has_master_key:
        warnings.append(
            "provider-master-key is missing; encrypted API keys cannot be restored on this machine"
        )
    if has_master_key and not has_settings:
        warnings.append("provider-master-key exists without provider-settings.json")

    db_version = _db_version(destination / database_filename)
    counts = _table_counts(destination / database_filename)
    entries = _collect_entries(destination)
    manifest = {
        "format": BACKUP_FORMAT,
        "createdAt": datetime.now(UTC).isoformat(),
        "source": str(source),
        "database": database_filename,
        "dbVersion": db_version,
        "counts": counts,
        "warnings": warnings,
        "entries": [
            {"path": entry.path, "bytes": entry.bytes, "sha256": entry.sha256} for entry in entries
        ],
    }
    (destination / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return BackupReport(
        destination=destination,
        entries=entries,
        warnings=tuple(warnings),
        db_version=db_version,
        counts=counts,
    )


def verify_backup(destination: Path) -> VerifyReport:
    """Re-hash every manifest entry and check the copied database."""

    destination = destination.resolve()
    manifest_path = destination / MANIFEST_NAME
    if not manifest_path.is_file():
        return VerifyReport(ok=False, entries=0, problems=("manifest_missing",))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return VerifyReport(ok=False, entries=0, problems=("manifest_unreadable",))
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        return VerifyReport(ok=False, entries=0, problems=("manifest_entries_invalid",))

    problems: list[str] = []
    entries = 0
    for raw in raw_entries:
        if not isinstance(raw, dict):
            problems.append("manifest_entry_invalid")
            continue
        try:
            relative = str(raw["path"])
            expected_bytes = int(raw["bytes"])
            expected_sha = str(raw["sha256"])
        except (KeyError, TypeError, ValueError):
            problems.append("manifest_entry_invalid")
            continue
        entries += 1
        target = destination / relative
        try:
            target.resolve().relative_to(destination)
        except ValueError:
            problems.append(f"path_escapes_backup: {relative}")
            continue
        if not target.is_file():
            problems.append(f"missing: {relative}")
            continue
        if target.stat().st_size != expected_bytes:
            problems.append(f"size_mismatch: {relative}")
            continue
        if _sha256(target) != expected_sha:
            problems.append(f"sha256_mismatch: {relative}")

    database = destination / str(manifest.get("database") or DATABASE_DEFAULT)
    if database.is_file():
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error:
            problems.append("database_unreadable")
        else:
            if not result or result[0] != "ok":
                problems.append("database_integrity_failed")
    else:
        problems.append("database_missing")

    return VerifyReport(ok=not problems, entries=entries, problems=tuple(problems))


def _copy_database(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        return
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        if any(part in {"tmp", "__pycache__"} for part in relative.parts):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)


def _collect_entries(destination: Path) -> tuple[BackupEntry, ...]:
    entries: list[BackupEntry] = []
    for item in sorted(destination.rglob("*")):
        if not item.is_file() or item.name == MANIFEST_NAME:
            continue
        entries.append(
            BackupEntry(
                path=item.relative_to(destination).as_posix(),
                bytes=item.stat().st_size,
                sha256=_sha256(item),
            )
        )
    return tuple(entries)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_version(database: Path) -> int | None:
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row and row[0] is not None else None


def _table_counts(database: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            existing = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in COUNT_TABLES:
                if table in existing:
                    counts[table] = int(
                        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )
    except sqlite3.Error:
        return counts
    return counts


__all__ = [
    "BACKUP_FORMAT",
    "BackupEntry",
    "BackupError",
    "BackupReport",
    "VerifyReport",
    "create_backup",
    "verify_backup",
]
