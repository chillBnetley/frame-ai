from __future__ import annotations

import os
from pathlib import Path

from app.core.errors import AppError


class OriginalImageStore:
    def __init__(self, data_dir: Path, originals_dirname: str) -> None:
        self._data_dir = data_dir.resolve()
        self._originals_dir = (data_dir / originals_dirname).resolve()

    @property
    def originals_dir(self) -> Path:
        return self._originals_dir

    def ensure_ready(self) -> None:
        self._originals_dir.mkdir(parents=True, exist_ok=True)
        probe = self._originals_dir / ".write-probe"
        try:
            probe.write_bytes(b"")
        except OSError as exc:
            raise RuntimeError(
                f"Image storage directory is not writable: {self._originals_dir}"
            ) from exc
        finally:
            try:
                probe.unlink()
            except FileNotFoundError:
                pass

    def save(self, image_id: str, extension: str, data: bytes) -> str:
        storage_key = f"{self._originals_dir.name}/{image_id}{extension}"
        path = self._resolve_key(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise AppError(500, "storage_conflict", "The image could not be stored.") from exc
        except OSError as exc:
            raise AppError(500, "storage_error", "The image could not be stored.") from exc
        return storage_key

    def resolve(self, storage_key: str) -> Path:
        path = self._resolve_key(storage_key)
        if not path.is_file():
            raise AppError(404, "image_file_missing", "The original image file is not available.")
        return path

    def discard(self, storage_key: str) -> None:
        try:
            self._resolve_key(storage_key).unlink()
        except (OSError, AppError):
            pass

    def _resolve_key(self, storage_key: str) -> Path:
        if not storage_key or Path(storage_key).is_absolute():
            raise AppError(500, "storage_error", "The stored image path is invalid.")
        candidate = (self._data_dir / storage_key).resolve()
        if candidate != self._originals_dir and self._originals_dir not in candidate.parents:
            raise AppError(500, "storage_error", "The stored image path is invalid.")
        return candidate
