from __future__ import annotations

import hashlib
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.decoder import DecodedImage, inspect_image, normalize_declared_mime
from app.repositories.image_registry import ImageAssetRecord, ImageRegistry
from app.repositories.original_store import OriginalImageStore

logger = logging.getLogger("frame_ai.images")

_CHUNK_SIZE = 64 * 1024


def sanitize_original_name(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if char.isprintable() and char != "\x00").strip()
    if name in {"", ".", ".."}:
        return "image"
    return name[:200]


class ImageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = OriginalImageStore(settings.data_dir, settings.originals_dirname)
        self.registry = ImageRegistry(settings.registry_path)
        self._decode_slots = threading.BoundedSemaphore(2)

    def ensure_ready(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store.ensure_ready()

    def _inspect(self, data: bytes, declared_mime: str) -> DecodedImage:
        with self._decode_slots:
            return inspect_image(data, declared_mime, self.settings.max_image_pixels)

    async def create_from_upload(self, upload: UploadFile) -> ImageAssetRecord:
        declared_mime = normalize_declared_mime(upload.content_type)
        data = await self._read_limited(upload, self.settings.max_upload_bytes)
        decoded = await run_in_threadpool(self._inspect, data, declared_mime)

        image_id = str(uuid4())
        sha256 = hashlib.sha256(data).hexdigest()
        storage_key = await run_in_threadpool(
            self.store.save,
            image_id,
            decoded.extension,
            data,
        )

        record = ImageAssetRecord(
            id=image_id,
            original_name=sanitize_original_name(upload.filename),
            storage_key=storage_key,
            mime_type=decoded.mime_type,
            width=decoded.width,
            height=decoded.height,
            exif_orientation=decoded.exif_orientation,
            bytes=len(data),
            sha256=sha256,
            created_at=datetime.now(UTC),
        )
        try:
            self.registry.add(record)
        except Exception as exc:
            await run_in_threadpool(self.store.discard, storage_key)
            logger.exception("failed to register uploaded image")
            raise AppError(500, "storage_error", "The image could not be registered.") from exc

        logger.info(
            "image_stored image_id=%s bytes=%s width=%s height=%s mime=%s",
            image_id,
            record.bytes,
            record.width,
            record.height,
            record.mime_type,
        )
        return record

    def get_original(self, image_id: str) -> tuple[ImageAssetRecord, Path]:
        try:
            normalized_id = str(UUID(image_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise AppError(404, "image_not_found", "The requested image was not found.") from exc

        record = self.registry.get(normalized_id)
        if record is None:
            raise AppError(404, "image_not_found", "The requested image was not found.")
        return record, self.store.resolve(record.storage_key)

    async def _read_limited(self, upload: UploadFile, limit: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await upload.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise AppError(
                    413,
                    "file_too_large",
                    "The uploaded file exceeds the configured size limit.",
                    {"maxBytes": limit},
                )
            chunks.append(chunk)
        if total == 0:
            raise AppError(400, "empty_file", "The uploaded file is empty.")
        return b"".join(chunks)
