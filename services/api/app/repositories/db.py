from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  checksum   TEXT NOT NULL,
  applied_at TEXT NOT NULL
)
"""


class MigrationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def _statements(sql: str) -> Iterator[str]:
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    remainder = buffer.strip()
    if remainder:
        yield remainder


def _migration_files(directory: Path) -> list[tuple[int, str, Path]]:
    migrations: list[tuple[int, str, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        prefix, _, name = path.stem.partition("_")
        if not prefix.isdigit() or not name:
            raise MigrationError(f"Invalid migration filename: {path.name}")
        migrations.append((int(prefix), name, path))
    versions = [version for version, _, _ in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError("Duplicate migration versions found")
    return migrations


def apply_migrations(
    connection: sqlite3.Connection,
    directory: Path = MIGRATIONS_DIR,
) -> list[int]:
    """Apply pending SQL migrations and verify applied checksums."""
    connection.execute(_SCHEMA_MIGRATIONS)
    applied = {
        int(row["version"]): (str(row["checksum"]),)
        for row in connection.execute("SELECT version, checksum FROM schema_migrations")
    }
    newly_applied: list[int] = []
    for version, name, path in _migration_files(directory):
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        if version in applied:
            if applied[version][0] != checksum:
                raise MigrationError(f"Migration {path.name} was modified after it was applied.")
            continue

        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in _statements(raw.decode("utf-8")):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (version, name, checksum, utc_now()),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        newly_applied.append(version)
    return newly_applied


def initialize_database(path: Path, directory: Path = MIGRATIONS_DIR) -> None:
    connection = connect(path)
    try:
        apply_migrations(connection, directory)
    finally:
        connection.close()
