from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.tools.backup_data import BackupError, create_backup, verify_backup


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "data"
    (source / "originals").mkdir(parents=True)
    (source / "masks").mkdir()
    (source / "generated").mkdir()
    (source / "generative" / "results").mkdir(parents=True)
    (source / "tmp" / "previews").mkdir(parents=True)
    (source / "tmp" / "exports").mkdir(parents=True)

    database = source / "frame.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO schema_migrations VALUES (13, 'generative_base_mode')")
        connection.execute("CREATE TABLE image_asset (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO image_asset VALUES ('image-1')")
        connection.execute("CREATE TABLE edit_session (id TEXT PRIMARY KEY)")

    (source / "originals" / "a.jpg").write_bytes(b"original-bytes")
    (source / "masks" / "m.png").write_bytes(b"mask-bytes")
    (source / "generated" / "g.png").write_bytes(b"generated-bytes")
    (source / "generative" / "results" / "r.png").write_bytes(b"result-bytes")
    (source / "tmp" / "previews" / "p.jpg").write_bytes(b"preview-bytes")
    (source / "tmp" / "exports" / "e.jpg").write_bytes(b"export-bytes")
    (source / "provider-settings.json").write_text("{}", encoding="utf-8")
    (source / "provider-master-key").write_bytes(b"key")
    (source / "onboarding.json").write_text("{}", encoding="utf-8")
    (source / "api-token").write_text("secret-token", encoding="utf-8")
    return source


def test_backup_copies_durable_state_and_excludes_secrets(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    destination = tmp_path / "backup"

    report = create_backup(source, destination)

    assert (destination / "frame.db").is_file()
    assert (destination / "originals" / "a.jpg").read_bytes() == b"original-bytes"
    assert (destination / "masks" / "m.png").is_file()
    assert (destination / "generative" / "results" / "r.png").is_file()
    assert (destination / "provider-settings.json").is_file()
    assert (destination / "provider-master-key").is_file()
    assert not (destination / "api-token").exists()
    assert not (destination / "previews").exists()
    assert not (destination / "tmp").exists()
    assert report.db_version == 13
    assert report.counts["image_asset"] == 1
    assert report.warnings == ()
    assert (destination / "manifest.json").is_file()

    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "frame-ai-backup/1"
    assert all("api-token" not in entry["path"] for entry in manifest["entries"])

    verification = verify_backup(destination)
    assert verification.ok
    assert verification.entries == len(report.entries)


def test_backup_can_include_previews(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    destination = tmp_path / "backup"

    create_backup(source, destination, include_previews=True)

    assert (destination / "previews" / "p.jpg").is_file()
    assert not (destination / "previews" / "e.jpg").exists()


def test_verify_detects_tampering(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    destination = tmp_path / "backup"
    create_backup(source, destination)

    (destination / "originals" / "a.jpg").write_bytes(b"tampered")

    verification = verify_backup(destination)
    assert not verification.ok
    assert any("a.jpg" in problem for problem in verification.problems)


def test_backup_refuses_existing_destination(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    destination = tmp_path / "backup"
    destination.mkdir()

    with pytest.raises(BackupError):
        create_backup(source, destination)


def test_backup_requires_database(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()

    with pytest.raises(BackupError):
        create_backup(source, tmp_path / "backup")


def test_backup_warns_when_master_key_is_missing(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    (source / "provider-master-key").unlink()

    report = create_backup(source, tmp_path / "backup")

    assert any("provider-master-key" in warning for warning in report.warnings)
