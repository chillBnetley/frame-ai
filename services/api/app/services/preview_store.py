from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.imaging.loader import proxy_cache_directory

logger = logging.getLogger("frame_ai.previews")

PREVIEW_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_JPEG_SUFFIX = ".jpg"


@dataclass(frozen=True)
class CleanupReport:
    deleted: int = 0
    skipped_symlinks: int = 0
    errors: int = 0
    deleted_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def removed_any(self) -> bool:
        return self.deleted > 0


class PreviewStore:
    """Content-addressed preview files confined to a single directory."""

    def __init__(self, directory: Path, *, ttl_seconds: int) -> None:
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self._write_lock = threading.Lock()

    def ensure_ready(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, preview_id: str) -> Path:
        if not PREVIEW_ID_PATTERN.fullmatch(preview_id):
            raise ValueError("preview_id must be a 64-character lowercase hex digest")
        return self.directory / f"{preview_id}{_JPEG_SUFFIX}"

    def resolve(self, preview_id: str) -> Path | None:
        try:
            path = self.path_for(preview_id)
        except ValueError:
            return None
        if path.is_symlink() or not path.is_file():
            return None
        return path

    def dimensions(self, preview_id: str) -> tuple[int, int] | None:
        path = self.resolve(preview_id)
        if path is None:
            return None
        try:
            with Image.open(path) as image:
                width, height = image.size
                if image.format != "JPEG":
                    return None
                return int(width), int(height)
        except (OSError, UnidentifiedImageError, ValueError):
            path.unlink(missing_ok=True)
            return None

    def write(self, preview_id: str, data: bytes) -> Path:
        destination = self.path_for(preview_id)
        self.ensure_ready()
        # Serialize writers: concurrent renders of the same content-addressed
        # preview otherwise race on Windows' non-atomic replace semantics.
        with self._write_lock:
            temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_bytes(data)
                for attempt in range(5):
                    try:
                        os.replace(temporary, destination)
                        return destination
                    except PermissionError:
                        if attempt == 4:
                            # A concurrent reader still holds the old file open.
                            # Content-addressed previews are identical, so the
                            # already-published bytes are a valid result.
                            if destination.is_file():
                                logger.debug(
                                    "preview_write_kept_existing preview_id=%s", preview_id
                                )
                                return destination
                            raise
                        time.sleep(0.02)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        return destination

    def cleanup(self, *, now: float | None = None) -> CleanupReport:
        """Delete expired render files in the preview directory and proxy cache."""
        cutoff = (time.time() if now is None else now) - self.ttl_seconds
        deleted: list[str] = []
        skipped = 0
        errors = 0
        directories = [self.directory, proxy_cache_directory(self.directory)]
        for directory in directories:
            entries, scan_failed = self._scan(directory)
            if scan_failed:
                errors += 1
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        skipped += 1
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                        continue
                    os.unlink(entry.path)
                    deleted.append(entry.name)
                except FileNotFoundError:
                    continue
                except OSError:
                    errors += 1
                    logger.warning("preview_cleanup_unlink_failed path=%s", entry.path)

        if deleted:
            logger.info(
                "preview_cleanup deleted=%s skipped_symlinks=%s errors=%s",
                len(deleted),
                skipped,
                errors,
            )
        return CleanupReport(
            deleted=len(deleted),
            skipped_symlinks=skipped,
            errors=errors,
            deleted_names=tuple(sorted(deleted)),
        )

    @staticmethod
    def _scan(directory: Path) -> tuple[list[os.DirEntry[str]], bool]:
        if not directory.is_dir():
            return [], False
        try:
            return list(os.scandir(directory)), False
        except OSError:
            logger.warning("preview_cleanup_scan_failed directory=%s", directory)
            return [], True
