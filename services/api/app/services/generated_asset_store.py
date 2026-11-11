from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.core.errors import AppError

logger = logging.getLogger("frame_ai.generative_store")

_CANDIDATE_EXTENSION = ".png"
_GENERATED_EXTENSION = ".png"
_MASKS_PREFIX = "masks"
_MASK_EXTENSION = ".png"


class GeneratedAssetStore:
    """Atomic storage for generated pixels and unaccepted candidates.

    Paths are relative keys such as ``generated/{id}.png`` or
    ``generative/results/{id}.png``. Writes go through a temporary file and
    ``os.replace``; reads and deletes are confined to the two configured roots.
    """

    def __init__(self, settings: Settings) -> None:
        self._data_dir = settings.data_dir.resolve()
        self.generated_dir = settings.generated_dir.resolve()
        self.results_dir = settings.generative_results_dir.resolve()
        self.tmp_dir = settings.generative_tmp_dir.resolve()
        self.masks_dir = (settings.data_dir / "masks").resolve()
        self._generated_prefix = settings.generated_dirname
        self._results_prefix = settings.generative_results_dirname
        self.max_bytes = settings.generative_max_output_bytes

    def ensure_ready(self) -> None:
        for directory in (self.generated_dir, self.results_dir, self.tmp_dir, self.masks_dir):
            self._guard_root(directory)
            directory.mkdir(parents=True, exist_ok=True)
        probe = self.tmp_dir / ".write-probe"
        try:
            probe.write_bytes(b"")
        except OSError as exc:
            raise RuntimeError(f"Generative storage is not writable: {self.tmp_dir}") from exc
        finally:
            with contextlib.suppress(FileNotFoundError):
                probe.unlink()

    def cleanup_temp(self) -> None:
        """Drop leftovers from a previous process; no task survives a restart."""
        self._guard_root(self.tmp_dir)
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        finally:
            self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def slug_for_candidate(self, result_id: str) -> str:
        return f"{self._results_prefix}/{result_id}{_CANDIDATE_EXTENSION}"

    def slug_for_generated(self, asset_id: str) -> str:
        return f"{self._generated_prefix}/{asset_id}{_GENERATED_EXTENSION}"

    def save_candidate(self, result_id: str, data: bytes) -> str:
        return self._write(self.slug_for_candidate(result_id), data)

    def save_generated(self, asset_id: str, data: bytes) -> str:
        return self._write(self.slug_for_generated(asset_id), data)

    def slug_for_mask(self, mask_id: str) -> str:
        return f"{_MASKS_PREFIX}/{mask_id}{_MASK_EXTENSION}"

    def mask_sidecar_key(self, storage_key: str) -> str:
        if not storage_key.endswith(_MASK_EXTENSION):
            raise AppError(
                500,
                "generative_mask_storage_error",
                "The mask storage key is invalid.",
            )
        return storage_key[: -len(_MASK_EXTENSION)] + ".json"

    def save_mask(self, mask_id: str, data: bytes, metadata: dict[str, Any]) -> str:
        """Publish the grayscale PNG and its sidecar; the pair is all-or-nothing."""

        key = self.slug_for_mask(mask_id)
        self._write_mask(key, data)
        payload = json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            self._write_mask(self.mask_sidecar_key(key), payload)
        except AppError:
            self.discard(key)
            raise
        return key

    def read(self, storage_key: str) -> bytes:
        return self.resolve(storage_key).read_bytes()

    def resolve(self, storage_key: str) -> Path:
        path = self._resolve_key(storage_key)
        if not path.is_file():
            raise AppError(
                404,
                "generated_asset_file_missing",
                "The generated image file is not available.",
            )
        return path

    def discard(self, storage_key: str) -> bool:
        try:
            path = self._resolve_key(storage_key)
        except AppError:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            logger.warning("generated_file_delete_failed path=%s", path)
            return False
        return True

    def measure_masks_bytes(self) -> int:
        if not self.masks_dir.exists():
            return 0
        total = 0
        try:
            for entry in self.masks_dir.iterdir():
                if entry.is_file():
                    with contextlib.suppress(OSError):
                        total += entry.stat().st_size
        except OSError:
            pass
        return total

    def _write(self, storage_key: str, data: bytes) -> str:
        return self._write_payload(
            storage_key,
            data,
            empty_code="generative_empty_output",
            empty_message="The generated file is empty.",
            too_large_message="The generated file exceeds the configured size limit.",
            error_code="generative_storage_error",
            error_message="The generated image could not be stored.",
        )

    def _write_mask(self, storage_key: str, data: bytes) -> str:
        return self._write_payload(
            storage_key,
            data,
            empty_code="generative_mask_empty",
            empty_message="The mask file is empty.",
            too_large_message="The mask file exceeds the configured size limit.",
            error_code="generative_mask_storage_error",
            error_message="The mask could not be stored.",
        )

    def _write_payload(
        self,
        storage_key: str,
        data: bytes,
        *,
        empty_code: str,
        empty_message: str,
        too_large_message: str,
        error_code: str,
        error_message: str,
    ) -> str:
        if not data:
            raise AppError(500, empty_code, empty_message)
        if len(data) > self.max_bytes:
            raise AppError(
                413,
                "generative_output_too_large",
                too_large_message,
                {"bytes": len(data), "maxBytes": self.max_bytes},
            )
        path = self._resolve_key(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with open(temporary, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise AppError(500, error_code, error_message) from exc
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()
        return storage_key

    def _resolve_key(self, storage_key: str) -> Path:
        if not storage_key or Path(storage_key).is_absolute():
            raise AppError(500, "generative_storage_error", "The stored path is invalid.")
        candidate = (self._data_dir / storage_key).resolve()
        allowed = (self.generated_dir, self.results_dir, self.tmp_dir, self.masks_dir)
        if not any(candidate == root or root in candidate.parents for root in allowed):
            raise AppError(500, "generative_storage_error", "The stored path is invalid.")
        return candidate

    def _guard_root(self, directory: Path) -> None:
        if self._data_dir not in directory.parents:
            raise RuntimeError(
                f"Generative storage must live inside the data directory: {directory}"
            )


__all__ = ["GeneratedAssetStore"]
