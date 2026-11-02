from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.config import Settings
from app.repositories.image_registry import ImageAssetRecord, ImageRegistry
from app.services.image_service import ConsistencyReport, ImageService
from tests.conftest import make_image


def _record(image_id: str, *, storage_key: str | None = None) -> ImageAssetRecord:
    return ImageAssetRecord(
        id=image_id,
        original_name="photo.png",
        storage_key=storage_key or f"originals/{image_id}.png",
        mime_type="image/png",
        width=10,
        height=10,
        exif_orientation=1,
        bytes=100,
        sha256="0" * 64,
        created_at=datetime.now(UTC),
    )


def test_registry_handles_concurrent_inserts(tmp_path: Path):
    path = tmp_path / "registry.json"
    registry = ImageRegistry(path)
    barrier = Barrier(50)

    def insert() -> None:
        barrier.wait()
        registry.add(_record(str(uuid4())))

    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(lambda _: insert(), range(50)))

    assert len(registry.list_ids()) == 50
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["images"]) == 50


class InMemoryImageRepository:
    def __init__(self) -> None:
        self.records: dict[str, ImageAssetRecord] = {}

    def add(self, record: ImageAssetRecord) -> None:
        if record.id in self.records:
            raise ValueError("duplicate")
        self.records[record.id] = record

    def get(self, image_id: str) -> ImageAssetRecord | None:
        return self.records.get(image_id.lower())

    def exists(self, image_id: str) -> bool:
        return image_id.lower() in self.records

    def list_ids(self) -> list[str]:
        return sorted(self.records)


def test_image_service_depends_on_repository_protocol(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )
    settings.data_dir.mkdir(parents=True)
    repository = InMemoryImageRepository()
    service = ImageService(settings, repository=repository)
    service.ensure_ready()

    payload = make_image("PNG")
    upload = UploadFile(
        io.BytesIO(payload),
        filename="photo.png",
        headers=Headers({"content-type": "image/png"}),
    )

    import asyncio

    record = asyncio.run(service.create_from_upload(upload))

    assert repository.records == {record.id: record}
    assert (settings.data_dir / "originals" / f"{record.id}.png").read_bytes() == payload
    assert service.scan_consistency() == ConsistencyReport((), ())


def test_consistency_scan_reports_orphans_and_dangling_records_without_deleting(
    tmp_path: Path,
):
    settings = Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )
    service = ImageService(settings)
    service.ensure_ready()

    dangling_id = str(uuid4())
    service.registry.add(_record(dangling_id))
    orphan = settings.data_dir / "originals" / "orphan.png"
    orphan.write_bytes(b"not registered")

    report = service.scan_consistency()

    assert report.dangling_records == (dangling_id,)
    assert report.orphan_files == ("orphan.png",)
    assert orphan.exists()
    assert service.registry.exists(dangling_id)
