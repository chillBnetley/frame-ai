from __future__ import annotations

import hashlib
import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from unicodedata import category, normalize
from uuid import UUID, uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError
from app.imaging.decoder import DecodedImage, inspect_image, normalize_declared_mime
from app.repositories.base import ImageRepository
from app.repositories.db import initialize_database
from app.repositories.image_registry import ImageAssetRecord
from app.repositories.image_repo import SqliteImageRepository
from app.repositories.original_store import OriginalImageStore
from app.tools.import_json_registry import maybe_import_legacy_registry

logger = logging.getLogger("frame_ai.images")

_CHUNK_SIZE = 64 * 1024
_MIN_FREE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class StorageStatus:
    ok: bool
    writable: bool


@dataclass(frozen=True)
class ConsistencyReport:
    orphan_files: tuple[str, ...]
    dangling_records: tuple[str, ...]

    @property
    def is_consistent(self) -> bool:
        return not self.orphan_files and not self.dangling_records


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", "ignore").strip()


def sanitize_original_name(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = normalize("NFC", name)
    name = "".join(char for char in name if category(char)[0] != "C")
    name = name.strip()
    if name in {"", ".", ".."}:
        return "image"
    return _truncate_utf8(name, 255) or "image"


class ImageService:
    def __init__(
        self,
        settings: Settings,
        *,
        store: OriginalImageStore | None = None,
        repository: ImageRepository | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or OriginalImageStore(settings.data_dir, settings.originals_dirname)
        self.registry: ImageRepository = repository or SqliteImageRepository(settings.database_path)
        self._decode_slots = threading.BoundedSemaphore(2)

    def ensure_ready(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store.ensure_ready()
        free_bytes = shutil.disk_usage(self.settings.data_dir).free
        required_bytes = max(self.settings.max_upload_bytes * 2, _MIN_FREE_BYTES)
        if free_bytes < required_bytes:
            raise RuntimeError(
                f"Insufficient free disk space for image storage: {free_bytes} bytes "
                f"available, {required_bytes} bytes required."
            )
        initialize_database(self.settings.database_path)
        report = maybe_import_legacy_registry(self.settings)
        if report is not None:
            logger.info(
                "legacy_registry_imported imported=%s already_present=%s skipped=%s backup=%s",
                report.imported,
                report.already_present,
                len(report.skipped),
                report.backup_path,
            )
        logger.info(
            "storage_ready data_dir=%s originals_dir=%s free_bytes=%s",
            self.settings.data_dir,
            self.store.originals_dir,
            free_bytes,
        )

    def storage_status(self) -> StorageStatus:
        data_dir = self.settings.data_dir
        if not data_dir.is_dir():
            return StorageStatus(ok=False, writable=False)
        probe = data_dir / f".health-probe-{uuid4().hex}"
        try:
            probe.write_bytes(b"")
            return StorageStatus(ok=True, writable=True)
        except OSError:
            return StorageStatus(ok=False, writable=False)
        finally:
            try:
                probe.unlink()
            except OSError:
                pass

    def scan_consistency(self) -> ConsistencyReport:
        """Compare stored files with registry records; never deletes anything."""
        registered_files: set[str] = set()
        dangling_records: list[str] = []

        for image_id in self.registry.list_ids():
            record = self.registry.get(image_id)
            if record is None:
                dangling_records.append(image_id)
                continue
            registered_files.add(Path(record.storage_key).name)
            try:
                self.store.resolve(record.storage_key)
            except AppError:
                dangling_records.append(image_id)

        originals_dir = self.store.originals_dir
        present_files = {
            path.name
            for path in originals_dir.iterdir()
            if path.is_file() and not path.name.startswith(".")
        }
        orphan_files = sorted(present_files - registered_files)
        report = ConsistencyReport(
            orphan_files=tuple(orphan_files),
            dangling_records=tuple(sorted(dangling_records)),
        )
        if not report.is_consistent:
            logger.warning(
                "storage_consistency orphan_files=%s dangling_records=%s",
                list(report.orphan_files),
                list(report.dangling_records),
            )
        return report

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

    def list_images(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ImageAssetRecord], int | None]:
        records = self.registry.list_records(limit=limit + 1, offset=offset)
        has_more = len(records) > limit
        page = records[:limit]
        return page, (offset + limit if has_more else None)

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
