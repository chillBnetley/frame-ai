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
        plan_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(photographer_plan)")
        }
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        connection.close()

    assert versions == [1, 2, 3, 4, 5, 6, 7, 8]
    assert {
        "image_asset",
        "edit_session",
        "edit_revision",
        "analysis_task",
        "analysis_result",
        "photographer_plan",
        "photographer_feedback",
        "deleted_resource",
        "style_profile",
        "style_profile_version",
        "style_favorite",
    } <= tables
    assert "conversion_mode" in plan_columns
    assert foreign_key_issues == []
    assert journal_mode == "wal"


def test_provider_usage_migration_upgrades_an_existing_database(tmp_path: Path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    for source in sorted(MIGRATIONS_DIR.glob("000[1-5]_*.sql")):
        shutil.copyfile(source, directory / source.name)
    path = tmp_path / "frame.db"
    initialize_database(path, directory)

    connection = connect(path)
    try:
        connection.execute(
            "INSERT INTO deleted_resource (kind, id, deleted_at) VALUES ('image', 'earlier', 'now')"
        )
    finally:
        connection.close()

    shutil.copyfile(
        MIGRATIONS_DIR / "0006_provider_usage.sql",
        directory / "0006_provider_usage.sql",
    )
    initialize_database(path, directory)
    initialize_database(path, directory)

    connection = connect(path)
    try:
        versions = [
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        kept = connection.execute(
            "SELECT COUNT(*) FROM deleted_resource WHERE id = 'earlier'"
        ).fetchone()[0]
        usage_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(provider_usage)")
        }
    finally:
        connection.close()

    assert versions == [1, 2, 3, 4, 5, 6]
    assert kept == 1
    assert usage_columns == {
        "date",
        "provider",
        "requests",
        "tokens_estimated",
        "tokens_reported",
        "updated_at",
    }


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
