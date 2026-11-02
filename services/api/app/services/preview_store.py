from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

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
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return destination

    def cleanup(self, *, now: float | None = None) -> CleanupReport:
        """Delete expired regular files directly inside the preview directory."""
        if not self.directory.is_dir():
            return CleanupReport()
        cutoff = (time.time() if now is None else now) - self.ttl_seconds
        deleted: list[str] = []
        skipped = 0
        errors = 0
        try:
            entries = list(os.scandir(self.directory))
        except OSError:
            logger.warning("preview_cleanup_scan_failed directory=%s", self.directory)
            return CleanupReport(errors=1)

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
