from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class ImageAssetRecord(BaseModel):
    id: str
    original_name: str
    storage_key: str
    mime_type: str
    width: int
    height: int
    exif_orientation: int = Field(default=1, ge=1, le=8)
    bytes: int
    sha256: str
    created_at: datetime


class ImageRegistry:
    """Small, atomic JSON registry for uploaded image metadata.

    Sessions and revisions move to versioned SQLite migrations in phase 3.
    """

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._records: dict[str, ImageAssetRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Image registry is unreadable: {self._path}") from exc

        if payload.get("version") != self.VERSION or not isinstance(payload.get("images"), dict):
            raise RuntimeError(f"Image registry has an unsupported format: {self._path}")

        records: dict[str, ImageAssetRecord] = {}
        try:
            for image_id, raw in payload["images"].items():
                record = ImageAssetRecord.model_validate(raw)
                if record.id != image_id:
                    raise ValueError("registry key does not match record id")
                records[image_id] = record
        except ValidationError as exc:
            raise RuntimeError(f"Image registry contains invalid records: {self._path}") from exc
        except ValueError as exc:
            raise RuntimeError(f"Image registry contains invalid records: {self._path}") from exc

        self._records = records

    def get(self, image_id: str) -> ImageAssetRecord | None:
        with self._lock:
            return self._records.get(image_id.lower())

    def exists(self, image_id: str) -> bool:
        with self._lock:
            return image_id.lower() in self._records

    def list_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._records)

    def add(self, record: ImageAssetRecord) -> None:
        with self._lock:
            if record.id in self._records:
                raise ValueError("duplicate image id")
            next_records = {**self._records, record.id: record}
            self._write(next_records)
            self._records = next_records

    def _write(self, records: dict[str, ImageAssetRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.VERSION,
            "images": {
                image_id: record.model_dump(mode="json") for image_id, record in records.items()
            },
        }
        fd, temp_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
