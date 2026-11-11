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
        revision_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(edit_revision)")
        }
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        connection.close()

    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
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
        "personal_style",
        "personal_style_version",
        "personal_style_reference",
        "personal_style_photo_feature",
        "personal_style_feedback",
        "personal_style_evolution",
        "personal_style_tombstone",
        "generated_asset",
        "generative_mask",
        "generative_task",
        "generative_result",
    } <= tables
    assert "conversion_mode" in plan_columns
    assert "base_revision_id" in plan_columns
    assert {
        "plan_id",
        "style_id",
        "conversion_mode",
        "style_strength",
        "render_key",
        "base_generated_asset_id",
        "generative_task_id",
    } <= revision_columns
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


def test_generative_migration_upgrades_an_existing_database(tmp_path: Path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    for source in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if source.name.startswith(("0012_", "0013_")):
            continue
        shutil.copyfile(source, directory / source.name)
    path = tmp_path / "frame.db"
    initialize_database(path, directory)

    digest = "a" * 64
    connection = connect(path)
    try:
        connection.execute(
            "INSERT INTO image_asset "
            "(id, original_name, storage_key, mime_type, width, height, exif_orientation, "
            " bytes, sha256, created_at) "
            "VALUES ('image', 'a.png', 'originals/image.png', 'image/png', 10, 10, 1, "
            "        1, ?, 'now')",
            (digest,),
        )
        connection.execute(
            "INSERT INTO edit_session "
            "(id, image_id, status, created_at, updated_at) "
            "VALUES ('session', 'image', 'active', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO edit_revision "
            "(id, session_id, parent_id, revision_no, recipe_json, recipe_hash, source, "
            " idempotency_key, created_at) "
            "VALUES ('revision', 'session', NULL, 1, '{}', 'hash', 'initial', NULL, 'now')"
        )
        connection.execute(
            "UPDATE edit_session SET active_revision_id = 'revision', "
            "head_revision_id = 'revision' WHERE id = 'session'"
        )
    finally:
        connection.close()

    shutil.copyfile(
        MIGRATIONS_DIR / "0012_generative_core.sql",
        directory / "0012_generative_core.sql",
    )
    initialize_database(path, directory)

    connection = connect(path)
    try:
        connection.execute(
            "INSERT INTO generative_task "
            "(id, owner_id, image_id, session_id, base_revision_id, task_type, plan_json, "
            " params_json, provider, model, prompt_version, is_mock, status, stage, "
            " dedupe_key, created_at, updated_at, expires_at) "
            "VALUES ('task', 'owner', 'image', 'session', 'revision', 'remove', '{}', '{}', "
            "        'mock', 'mock-model', 'v1', 1, 'queued', 'queued', 'dedupe', "
            "        'now', 'now', 'later')"
        )
    finally:
        connection.close()

    shutil.copyfile(
        MIGRATIONS_DIR / "0013_generative_base_mode.sql",
        directory / "0013_generative_base_mode.sql",
    )
    initialize_database(path, directory)
    initialize_database(path, directory)

    connection = connect(path)
    try:
        versions = [
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        revision = connection.execute(
            "SELECT base_generated_asset_id, generative_task_id FROM edit_revision "
            "WHERE id = 'revision'"
        ).fetchone()
        task = connection.execute(
            "SELECT base_mode, input_sha256, input_recipe_hash FROM generative_task "
            "WHERE id = 'task'"
        ).fetchone()
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()

    assert versions == list(range(1, 14))
    assert revision is not None
    assert revision["base_generated_asset_id"] is None
    assert revision["generative_task_id"] is None
    assert task is not None
    assert task["base_mode"] == "base"
    assert task["input_sha256"] is None
    assert task["input_recipe_hash"] is None
    assert {"generated_asset", "generative_mask", "generative_task", "generative_result"} <= tables
    assert foreign_key_issues == []


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
