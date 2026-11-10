from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.errors import AppError
from app.repositories.generative_repo import SqliteGenerativeRepository
from app.services.generated_asset_store import GeneratedAssetStore
from app.services.image_service import ImageService


@dataclass(frozen=True, slots=True)
class ResolvedImage:
    """The pixels a revision renders from: the original or a generated asset."""

    id: str
    image_id: str
    storage_key: str
    path: Path
    sha256: str
    width: int
    height: int
    mime_type: str
    exif_orientation: int = 1


class ImageAssetResolver:
    def __init__(
        self,
        images: ImageService,
        generated: SqliteGenerativeRepository,
        store: GeneratedAssetStore,
    ) -> None:
        self.images = images
        self.generated = generated
        self.store = store

    def resolve(
        self,
        image_id: str,
        generated_asset_id: str | None = None,
    ) -> ResolvedImage:
        if generated_asset_id is None:
            record, path = self.images.get_original(image_id)
            return ResolvedImage(
                id=record.id,
                image_id=record.id,
                storage_key=record.storage_key,
                path=path,
                sha256=record.sha256,
                width=record.width,
                height=record.height,
                mime_type=record.mime_type,
                exif_orientation=record.exif_orientation,
            )

        asset = self.generated.get_generated_asset(generated_asset_id)
        if asset is None or asset.image_id.lower() != image_id.lower():
            raise AppError(
                404,
                "generated_asset_not_found",
                "The generated image was not found.",
            )
        return ResolvedImage(
            id=asset.id,
            image_id=asset.image_id,
            storage_key=asset.storage_key,
            path=self.store.resolve(asset.storage_key),
            sha256=asset.sha256,
            width=asset.width,
            height=asset.height,
            mime_type=asset.mime_type,
            exif_orientation=1,
        )


__all__ = ["ImageAssetResolver", "ResolvedImage"]
