from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.repositories.image_registry import ImageAssetRecord, ImageRegistry
from app.services.image_service import ImageService
from app.tools.import_json_registry import import_registry
from tests.conftest import image_row, make_image


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )


def _store(settings: Settings, payload: bytes, extension: str = "png") -> str:
    path = settings.originals_dir / f"{uuid4()}.{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return f"originals/{path.name}"


def _record(
    *,
    storage_key: str,
    payload: bytes | None,
    sha256: str | None = None,
    mime_type: str = "image/png",
    exif_orientation: int = 1,
) -> ImageAssetRecord:
    return ImageAssetRecord(
        id=str(uuid4()),
        original_name="photo.png",
        storage_key=storage_key,
        mime_type=mime_type,
        width=64,
        height=48,
        exif_orientation=exif_orientation,
        bytes=len(payload) if payload is not None else 100,
        sha256=sha256 or (hashlib.sha256(payload).hexdigest() if payload is not None else "0" * 64),
        created_at=datetime.now(UTC),
    )


def test_importer_skips_bad_records_and_backs_up_registry(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    payload = make_image("PNG")

    valid = _record(storage_key=_store(settings, payload), payload=payload)
    missing = _record(storage_key="originals/missing.png", payload=None)
    mismatched = _record(
        storage_key=_store(settings, b"not the registered bytes"),
        payload=payload,
    )
    escaped = _record(storage_key="../outside.png", payload=None)

    registry = ImageRegistry(settings.registry_path)
    for record in (valid, missing, mismatched, escaped):
        registry.add(record)

    report = import_registry(settings)

    skipped = {item.image_id: item.reason for item in report.skipped}
    assert report.registry_found is True
    assert report.imported == 1
    assert report.already_present == 0
    assert skipped == {
        missing.id: "stored file missing",
        mismatched.id: "sha256 mismatch",
        escaped.id: "stored file missing",
    }
    assert image_row(settings, valid.id)["sha256"] == hashlib.sha256(payload).hexdigest()

    backup = report.backup_path
    assert backup is not None and backup.is_file()
    assert not settings.registry_path.exists()
    assert (settings.data_dir / "originals" / "missing.png").exists() is False
    assert (settings.data_dir / mismatched.storage_key).read_bytes() == b"not the registered bytes"
    assert not (settings.data_dir.parent / "outside.png").exists()


def test_importer_is_idempotent_when_registry_is_kept(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    payload = make_image("PNG")
    record = _record(storage_key=_store(settings, payload), payload=payload)
    ImageRegistry(settings.registry_path).add(record)

    first = import_registry(settings, backup=False)
    second = import_registry(settings, backup=False)

    assert (first.imported, first.already_present) == (1, 0)
    assert (second.imported, second.already_present) == (0, 1)
    assert second.backup_path is None
    assert settings.registry_path.is_file()
    assert len(ImageRegistry(settings.registry_path).list_ids()) == 1


def test_importer_recomputes_exif_orientation_from_original(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    payload = make_image("JPEG", exif_orientation=6)
    storage_key = _store(settings, payload, extension="jpg")
    record = _record(
        storage_key=storage_key,
        payload=payload,
        mime_type="image/jpeg",
        exif_orientation=1,
    )
    ImageRegistry(settings.registry_path).add(record)

    import_registry(settings)

    assert image_row(settings, record.id)["exif_orientation"] == 6


def test_image_service_imports_legacy_registry_at_startup(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    payload = make_image("PNG")
    record = _record(storage_key=_store(settings, payload), payload=payload)
    ImageRegistry(settings.registry_path).add(record)

    service = ImageService(settings)
    service.ensure_ready()

    imported = service.registry.get(record.id)
    assert imported is not None
    assert imported.sha256 == record.sha256
    assert settings.registry_path.with_name("image_registry.json.imported.bak").is_file()
    assert service.scan_consistency().is_consistent
