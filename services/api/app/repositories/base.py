from __future__ import annotations

from typing import Protocol

from app.repositories.image_registry import ImageAssetRecord


class ImageRepository(Protocol):
    def add(self, record: ImageAssetRecord) -> None: ...

    def get(self, image_id: str) -> ImageAssetRecord | None: ...

    def exists(self, image_id: str) -> bool: ...

    def list_ids(self) -> list[str]: ...

    def list_records(self, *, limit: int, offset: int) -> list[ImageAssetRecord]: ...
