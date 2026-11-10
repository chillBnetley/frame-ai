from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.imaging.loader import proxy_cache_directory

logger = logging.getLogger("frame_ai.previews")

PREVIEW_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_JPEG_SUFFIX = ".jpg"


@dataclass(frozen=True)
class PreviewMetadata:
    """What a preview was rendered from, kept only in memory."""

    image_sha256: str
    recipe_hash: str
    edge: int
    quality: str


@dataclass(frozen=True)
class CleanupReport:
    deleted: int = 0
    skipped_symlinks: int = 0
    errors: int = 0
    deleted_names: tuple[str, ...] = field(default_factory=tuple)
    deleted_bytes: int = 0
    skipped: int = 0

    @property
    def removed_any(self) -> bool:
        return self.deleted > 0


class PreviewStore:
    """Content-addressed preview files confined to a single directory."""

    def __init__(
        self,
        directory: Path,
        *,
        ttl_seconds: int,
        max_bytes: int | None = None,
    ) -> None:
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self.max_bytes = max_bytes
        self._write_lock = threading.Lock()
        self._metadata: OrderedDict[str, PreviewMetadata] = OrderedDict()
        self._metadata_lock = threading.Lock()
        self._metadata_limit = 4096

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

    def remember(
        self,
        preview_id: str,
        *,
        image_sha256: str,
        recipe_hash: str,
        edge: int,
        quality: str,
    ) -> None:
        with self._metadata_lock:
            self._metadata[preview_id] = PreviewMetadata(
                image_sha256=image_sha256.lower(),
                recipe_hash=recipe_hash,
                edge=edge,
                quality=quality,
            )
            self._metadata.move_to_end(preview_id)
            while len(self._metadata) > self._metadata_limit:
                self._metadata.popitem(last=False)

    def metadata(self, preview_id: str) -> PreviewMetadata | None:
        with self._metadata_lock:
            metadata = self._metadata.get(preview_id)
            if metadata is not None:
                self._metadata.move_to_end(preview_id)
            return metadata

    def forget(self, preview_id: str) -> None:
        with self._metadata_lock:
            self._metadata.pop(preview_id, None)

    def touch(self, path: Path) -> None:
        """Renew the idle TTL of a served preview file.

        Read-only filesystems and permission errors must not break serving:
        the preview is still valid, it just keeps its previous mtime.
        """
        try:
            os.utime(path, None)
        except FileNotFoundError:
            return
        except OSError:
            logger.debug("preview_touch_failed path=%s", path)

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

    def purge_previews(self) -> CleanupReport:
        """Remove every rendered preview, leaving the proxy directory alone.

        Preview files are keyed by a render digest with no reverse index to the
        source image, so deleting one image cannot target only its previews.
        Dropping the whole preview cache is safe (it is disposable and
        regenerated on demand) and guarantees no rendered copy of the removed
        photo survives. Proxy files are deleted separately by the caller when
        their source digest is no longer referenced.
        """
        deleted: list[str] = []
        deleted_bytes = 0
        skipped_symlinks = 0
        skipped = 0
        errors = 0
        entries, scan_failed = self._scan(self.directory)
        if scan_failed:
            errors += 1
        for entry in entries:
            try:
                if entry.is_symlink():
                    skipped_symlinks += 1
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                errors += 1
                logger.warning("preview_purge_stat_failed path=%s", entry.path)
                continue
            try:
                os.unlink(entry.path)
            except FileNotFoundError:
                continue
            except OSError:
                skipped += 1
                logger.warning("preview_purge_unlink_failed path=%s", entry.path)
                continue
            deleted.append(entry.name)
            deleted_bytes += stat.st_size
            self.forget(Path(entry.name).stem)
        if deleted or skipped or errors:
            logger.info(
                "preview_purge deleted=%s deleted_bytes=%s skipped=%s "
                "skipped_symlinks=%s errors=%s",
                len(deleted),
                deleted_bytes,
                skipped,
                skipped_symlinks,
                errors,
            )
        return CleanupReport(
            deleted=len(deleted),
            skipped_symlinks=skipped_symlinks,
            errors=errors,
            deleted_names=tuple(sorted(deleted)),
            deleted_bytes=deleted_bytes,
            skipped=skipped,
        )

    def cleanup(self, *, now: float | None = None) -> CleanupReport:
        """Delete idle render files, then enforce the capacity budget.

        The TTL pass removes files whose mtime is older than the idle window;
        served previews and proxy hits refresh mtime, so actively viewed
        sessions survive. The capacity pass then evicts the oldest remaining
        files (previews and proxies together) until the byte budget is met.
        """
        current = time.time() if now is None else now
        cutoff = current - self.ttl_seconds
        deleted: list[str] = []
        deleted_bytes = 0
        skipped_symlinks = 0
        skipped = 0
        errors = 0
        files: list[tuple[Path, os.stat_result]] = []
        for directory in (self.directory, proxy_cache_directory(self.directory)):
            entries, scan_failed = self._scan(directory)
            if scan_failed:
                errors += 1
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        skipped_symlinks += 1
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError:
                    errors += 1
                    logger.warning("preview_cleanup_stat_failed path=%s", entry.path)
                    continue
                files.append((Path(entry.path), stat))

        remaining: list[tuple[Path, os.stat_result]] = []
        for path, stat in files:
            if stat.st_mtime >= cutoff:
                remaining.append((path, stat))
                continue
            try:
                os.unlink(path)
            except FileNotFoundError:
                continue
            except OSError:
                skipped += 1
                logger.warning("preview_cleanup_unlink_failed path=%s", path)
                remaining.append((path, stat))
                continue
            deleted.append(path.name)
            deleted_bytes += stat.st_size
            self.forget(Path(path.name).stem)

        if self.max_bytes is not None:
            total = sum(stat.st_size for _, stat in remaining)
            if total > self.max_bytes:
                for path, stat in sorted(
                    remaining,
                    key=lambda item: (item[1].st_mtime, item[0].name),
                ):
                    if total <= self.max_bytes:
                        break
                    try:
                        os.unlink(path)
                    except FileNotFoundError:
                        total -= stat.st_size
                        continue
                    except OSError:
                        skipped += 1
                        logger.warning("preview_cleanup_unlink_failed path=%s", path)
                        continue
                    total -= stat.st_size
                    deleted.append(path.name)
                    deleted_bytes += stat.st_size
                    self.forget(Path(path.name).stem)

        if deleted:
            logger.info(
                "preview_cleanup deleted=%s deleted_bytes=%s skipped=%s "
                "skipped_symlinks=%s errors=%s",
                len(deleted),
                deleted_bytes,
                skipped,
                skipped_symlinks,
                errors,
            )
        return CleanupReport(
            deleted=len(deleted),
            skipped_symlinks=skipped_symlinks,
            errors=errors,
            deleted_names=tuple(sorted(deleted)),
            deleted_bytes=deleted_bytes,
            skipped=skipped,
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
