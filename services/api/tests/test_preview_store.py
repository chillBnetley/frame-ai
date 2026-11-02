from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.services.preview_store import PreviewStore

DIGEST = "a" * 64


def _store(tmp_path: Path, ttl: int = 60) -> PreviewStore:
    store = PreviewStore(tmp_path / "previews", ttl_seconds=ttl)
    store.ensure_ready()
    return store


def test_paths_reject_traversal_and_malformed_ids(tmp_path: Path):
    store = _store(tmp_path)
    for invalid in ("", "../secret", "a" * 63, "A" * 64, "g" * 64, f"{DIGEST}/x"):
        with pytest.raises(ValueError):
            store.path_for(invalid)
        assert store.resolve(invalid) is None

    path = store.path_for(DIGEST)
    assert path.parent == store.directory
    assert path.name == f"{DIGEST}.jpg"


def test_write_is_atomic_and_readable(tmp_path: Path):
    store = _store(tmp_path)

    path = store.write(DIGEST, b"preview-bytes")

    assert path.read_bytes() == b"preview-bytes"
    assert not list(store.directory.glob("*.tmp"))
    store.write(DIGEST, b"replacement")
    assert path.read_bytes() == b"replacement"


def test_write_keeps_existing_preview_when_replace_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path)
    path = store.write(DIGEST, b"stable-bytes")

    def blocked_replace(_source: str, _destination: str) -> None:
        raise PermissionError("file is open by another reader")

    monkeypatch.setattr("app.services.preview_store.os.replace", blocked_replace)

    assert store.write(DIGEST, b"duplicate-bytes") == path
    assert path.read_bytes() == b"stable-bytes"
    assert not list(store.directory.glob("*.tmp"))


def test_cleanup_deletes_only_expired_files_inside_the_directory(tmp_path: Path):
    store = _store(tmp_path, ttl=60)
    now = time.time()
    old = store.directory / "old.jpg"
    fresh = store.directory / "fresh.jpg"
    outside = tmp_path / "outside.txt"
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    outside.write_bytes(b"keep")
    os.utime(old, (now - 600, now - 600))
    os.utime(fresh, (now - 10, now - 10))
    os.utime(outside, (now - 600, now - 600))
    nested = store.directory / "nested"
    nested.mkdir()
    os.utime(nested, (now - 600, now - 600))

    report = store.cleanup(now=now)

    assert report.deleted_names == ("old.jpg",)
    assert report.deleted == 1
    assert not old.exists()
    assert fresh.is_file()
    assert outside.is_file()
    assert nested.is_dir()


def test_cleanup_skips_symlinks_that_point_outside(tmp_path: Path):
    store = _store(tmp_path, ttl=60)
    now = time.time()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    os.utime(outside, (now - 600, now - 600))
    link = store.directory / "link.jpg"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation requires platform privileges")

    report = store.cleanup(now=now)

    assert report.skipped_symlinks == 1
    assert report.deleted == 0
    assert outside.is_file()


def test_cleanup_never_unlinks_symlink_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = _store(tmp_path, ttl=60)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")

    class FakeEntry:
        path = str(outside)

        def is_symlink(self) -> bool:
            return True

        def is_file(self, *, follow_symlinks: bool) -> bool:
            return True

        def stat(self, *, follow_symlinks: bool) -> os.stat_result:
            return os.stat(outside)

    monkeypatch.setattr(
        "app.services.preview_store.os.scandir",
        lambda _: [FakeEntry()],
    )

    report = store.cleanup(now=time.time() + 3600)

    assert report.skipped_symlinks == 1
    assert report.deleted == 0
    assert outside.is_file()


def test_dimensions_reject_non_jpeg_and_corrupt_files(tmp_path: Path):
    store = _store(tmp_path)
    path = store.write(DIGEST, b"not an image")

    assert store.dimensions(DIGEST) is None
    assert not path.exists()
    assert store.dimensions(DIGEST) is None
