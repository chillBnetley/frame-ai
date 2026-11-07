from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.repositories.db import (
    MIGRATIONS_DIR,
    MigrationError,
    connect,
    initialize_database,
)


def _migration_source() -> Path:
    return MIGRATIONS_DIR / "0001_init.sql"


def test_migrations_are_idempotent_and_schema_is_consistent(tmp_path: Path):
    path = tmp_path / "frame.db"

    initialize_database(path)
    initialize_database(path)

    connection = connect(path)
    try:
        versions = [
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        connection.close()

    assert versions == [1, 2, 3, 4, 5]
    assert {
        "image_asset",
        "edit_session",
        "edit_revision",
        "analysis_task",
        "analysis_result",
        "photographer_plan",
        "photographer_feedback",
        "deleted_resource",
    } <= tables
    assert foreign_key_issues == []
    assert journal_mode == "wal"


def test_modified_migration_is_rejected(tmp_path: Path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    target = directory / "0001_init.sql"
    shutil.copyfile(_migration_source(), target)
    path = tmp_path / "frame.db"
    initialize_database(path, directory)

    target.write_text(target.read_text(encoding="utf-8") + "\n-- changed after apply\n")

    with pytest.raises(MigrationError, match="modified"):
        initialize_database(path, directory)


def test_foreign_keys_are_enforced(tmp_path: Path):
    path = tmp_path / "frame.db"
    initialize_database(path)
    connection = connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO edit_session "
                "(id, image_id, status, created_at, updated_at) "
                "VALUES ('session', 'missing-image', 'active', 'now', 'now')"
            )
    finally:
        connection.close()
