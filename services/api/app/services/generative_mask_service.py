from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.identity import OwnerScope
from app.imaging.generative_masks import (
    MaskArray,
    encode_mask,
    mask_quality,
    mask_sha256,
    rasterize_mask,
    read_mask,
)
from app.imaging.semantic_mattes import read_matte
from app.models.generative import (
    GenerativeMaskCreate,
    GenerativeMaskDefinition,
    GenerativeMaskKind,
    GenerativeMaskListResponse,
    GenerativeMaskQuality,
    GenerativeMaskRecord,
    GenerativeMaskSource,
    GenerativeMaskView,
)
from app.models.schemas import CamelModel
from app.repositories.generative_repo import (
    DuplicateGenerativeTaskError,
    MaskInUseError,
    SqliteGenerativeRepository,
)
from app.services.asset_resolver import ImageAssetResolver, ResolvedImage
from app.services.generated_asset_store import GeneratedAssetStore
from app.services.semantic_mask_service import SemanticMaskService
from app.services.session_service import SessionService

logger = logging.getLogger("frame_ai.generative_mask")

_MIN_COVERAGE = 0.0005
_MAX_COVERAGE = 0.95


class _StoredSemanticProvenance(CamelModel):
    matte_id: str
    model_version: str


class _StoredMaskPayload(CamelModel):
    schema_version: Literal[1] = 1
    definition: GenerativeMaskDefinition
    quality: GenerativeMaskQuality
    semantic: _StoredSemanticProvenance | None = None


class GenerativeMaskService:
    """Creates and manages immutable raster masks for generative tasks.

    Every edit is stored as a new mask id so a queued or historical task keeps
    the exact pixels it was validated against; the previous version is only
    retired once no active task can still select it.
    """

    def __init__(
        self,
        settings: Settings,
        sessions: SessionService,
        assets: ImageAssetResolver,
        repository: SqliteGenerativeRepository,
        store: GeneratedAssetStore,
        semantic_masks: SemanticMaskService | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.assets = assets
        self.repository = repository
        self.store = store
        self.semantic_masks = semantic_masks

    def create(self, request: GenerativeMaskCreate, *, owner: OwnerScope) -> GenerativeMaskView:
        session = self.sessions.get(str(request.session_id))
        image_id = str(session.image_id)
        base_asset_id = _asset_id(session.revision.base_generated_asset_id)
        kind = GenerativeMaskKind(request.kind)
        self._validate_definition(kind, request.definition)
        base = self.assets.resolve(image_id, base_asset_id)
        self._validate_base_size(base)

        semantic: MaskArray | None = None
        provenance: _StoredSemanticProvenance | None = None
        if kind is GenerativeMaskKind.SEMANTIC:
            semantic, provenance = self._semantic_mask(
                image_id,
                base,
                base_asset_id,
                semantic_class=_require_semantic_class(request.definition),
            )

        pixels = rasterize_mask(
            request.definition,
            kind,
            width=base.width,
            height=base.height,
            feather=request.feather,
            inverted=request.inverted,
            semantic=semantic,
        )
        quality = mask_quality(pixels)
        self._validate_coverage(quality)

        mask_id = str(uuid4())
        created_at = datetime.now(UTC)
        data = encode_mask(pixels)
        sha256 = mask_sha256(pixels)
        payload = _StoredMaskPayload(
            definition=request.definition,
            quality=quality,
            semantic=provenance,
        )
        record = GenerativeMaskRecord(
            id=mask_id,
            owner_id=owner.owner_id,
            image_id=image_id,
            base_generated_asset_id=base_asset_id,
            kind=kind,
            source=(
                GenerativeMaskSource.SEMANTIC
                if kind is GenerativeMaskKind.SEMANTIC
                else GenerativeMaskSource.USER
            ),
            width=base.width,
            height=base.height,
            storage_key="",
            sha256=sha256,
            feather=request.feather,
            inverted=request.inverted,
            strokes_json=payload.model_dump_json(),
            created_at=created_at,
        )
        storage_key = self.store.save_mask(
            mask_id,
            data,
            _sidecar(record, payload),
        )
        record = record.model_copy(update={"storage_key": storage_key})
        try:
            self.repository.create_mask(record)
        except DuplicateGenerativeTaskError as exc:
            self._discard_pair(storage_key)
            raise AppError(
                409,
                "generative_mask_conflict",
                "A mask with this identifier already exists.",
            ) from exc
        except Exception:
            self._discard_pair(storage_key)
            raise
        logger.info(
            "generative_mask_created mask_id=%s image_id=%s kind=%s source=%s "
            "width=%s height=%s coverage=%.6f components=%s",
            mask_id,
            image_id,
            kind.value,
            record.source.value,
            base.width,
            base.height,
            quality.coverage,
            quality.component_count,
        )
        return self._view(record)

    def list_for_session(
        self,
        session_id: UUID,
        *,
        owner: OwnerScope,
        limit: int,
        offset: int,
    ) -> GenerativeMaskListResponse:
        session = self.sessions.get(str(session_id))
        records = self.repository.list_masks_for_owner(
            owner.owner_id,
            image_id=str(session.image_id),
            base_generated_asset_id=_asset_id(session.revision.base_generated_asset_id),
            limit=limit,
            offset=offset,
        )
        return GenerativeMaskListResponse(items=[self._view(record) for record in records])

    def get(self, mask_id: str, *, owner: OwnerScope) -> GenerativeMaskView:
        return self._view(self._require(mask_id, owner))

    def mask_image(self, mask_id: str, *, owner: OwnerScope) -> tuple[Path, str]:
        record = self._require(mask_id, owner)
        self.verify_pixels(record)
        return self.store.resolve(record.storage_key), "image/png"

    def delete(self, mask_id: str, *, owner: OwnerScope) -> None:
        record = self._require(mask_id, owner)
        try:
            outcome = self.repository.soft_delete_mask(record.id, owner.owner_id)
        except MaskInUseError as exc:
            raise AppError(
                409,
                "resource_busy",
                "The mask is used by a generative task that has not finished.",
                {"reasons": ["generative"]},
            ) from exc
        if not outcome.removed:
            raise AppError(404, "generative_mask_not_found", "The mask was not found.")
        if not outcome.referenced:
            self._discard_pair(record.storage_key)
        logger.info(
            "generative_mask_deleted mask_id=%s pixels_kept=%s",
            record.id,
            outcome.referenced,
        )

    def verify_pixels(self, record: GenerativeMaskRecord) -> MaskArray:
        """Re-read the stored grayscale pixels and check the recorded digest."""
        try:
            path = self.store.resolve(record.storage_key)
            return read_mask(
                path,
                width=record.width,
                height=record.height,
                expected_sha256=record.sha256,
                max_bytes=self.settings.generative_max_output_bytes,
            )
        except ValueError as exc:
            raise AppError(
                409,
                "generative_mask_invalid",
                "The stored mask is damaged or does not match its record.",
            ) from exc

    def _semantic_mask(
        self,
        image_id: str,
        base: ResolvedImage,
        base_asset_id: str | None,
        *,
        semantic_class: Literal["person", "sky"],
    ) -> tuple[MaskArray, _StoredSemanticProvenance]:
        if base_asset_id is not None:
            raise AppError(
                409,
                "generative_mask_semantic_base_unsupported",
                "AI-assisted masks currently bind to the original image, "
                "not to a generated base.",
            )
        if self.semantic_masks is None:
            raise AppError(503, "semantic_mask_unavailable", "Semantic masks are not available.")
        result = self.semantic_masks.create(image_id, semantic_class)
        matte = read_matte(self.settings.mattes_dir, result.matte_id, result.sha256)
        if matte is None or (matte.shape[1], matte.shape[0]) != (result.width, result.height):
            raise AppError(503, "semantic_mask_unavailable", "Semantic masks are not available.")
        return matte, _StoredSemanticProvenance(
            matte_id=result.matte_id,
            model_version=result.model_version,
        )

    def _validate_definition(
        self,
        kind: GenerativeMaskKind,
        definition: GenerativeMaskDefinition,
    ) -> None:
        reasons: list[str] = []
        if kind not in {
            GenerativeMaskKind.BRUSH,
            GenerativeMaskKind.RECT,
            GenerativeMaskKind.ELLIPSE,
            GenerativeMaskKind.SEMANTIC,
        }:
            raise AppError(
                422,
                "generative_mask_kind_unsupported",
                "This mask source is not available yet.",
                {"kind": kind.value},
            )
        if kind is GenerativeMaskKind.BRUSH:
            if not definition.strokes:
                reasons.append("a brush mask needs at least one stroke")
            if definition.region is not None:
                reasons.append("a brush mask cannot carry a region")
        elif kind in (GenerativeMaskKind.RECT, GenerativeMaskKind.ELLIPSE):
            if definition.region is None:
                reasons.append("a geometric mask needs a region")
        if kind is GenerativeMaskKind.SEMANTIC:
            if definition.semantic_class is None:
                reasons.append("a semantic mask needs a semantic class")
        elif definition.semantic_class is not None:
            reasons.append("semantic classes belong to semantic masks only")
        if reasons:
            raise AppError(
                422,
                "generative_mask_definition_invalid",
                "The mask definition is incomplete or inconsistent.",
                {"reasons": reasons},
            )

    def _validate_base_size(self, base: ResolvedImage) -> None:
        limit = min(
            self.settings.generative_max_input_pixels,
            self.settings.generative_max_output_pixels,
        )
        if base.width * base.height > limit:
            raise AppError(
                413,
                "generative_input_too_large",
                "The base image is larger than the mask pipeline accepts.",
                {"maxPixels": limit, "actual": base.width * base.height},
            )

    def _validate_coverage(self, quality: GenerativeMaskQuality) -> None:
        if _MIN_COVERAGE <= quality.coverage <= _MAX_COVERAGE:
            return
        raise AppError(
            422,
            "generative_mask_coverage",
            "The selected region is too small or nearly the whole image.",
            {
                "coverage": quality.coverage,
                "minCoverage": _MIN_COVERAGE,
                "maxCoverage": _MAX_COVERAGE,
            },
        )

    def _require(self, mask_id: str, owner: OwnerScope) -> GenerativeMaskRecord:
        try:
            identifier = str(UUID(mask_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise AppError(404, "generative_mask_not_found", "The mask was not found.") from exc
        record = self.repository.get_mask_for_owner(identifier, owner.owner_id)
        if record is None:
            raise AppError(404, "generative_mask_not_found", "The mask was not found.")
        return record

    def _view(self, record: GenerativeMaskRecord) -> GenerativeMaskView:
        payload = self._payload(record)
        return GenerativeMaskView(
            mask_id=UUID(record.id),
            image_id=UUID(record.image_id),
            base_generated_asset_id=_uuid(record.base_generated_asset_id),
            kind=record.kind,
            source=record.source,
            coordinate_space=record.coordinate_space,
            width=record.width,
            height=record.height,
            image_url=f"/api/v1/generative/masks/{record.id}/image",
            sha256=record.sha256,
            feather=record.feather,
            inverted=record.inverted,
            definition=payload.definition,
            quality=payload.quality,
            model_version=payload.semantic.model_version if payload.semantic else None,
            created_at=record.created_at,
        )

    def _payload(self, record: GenerativeMaskRecord) -> _StoredMaskPayload:
        try:
            return _StoredMaskPayload.model_validate_json(record.strokes_json)
        except ValidationError:
            return _StoredMaskPayload(
                definition=GenerativeMaskDefinition(),
                quality=mask_quality(self.verify_pixels(record)),
            )

    def _discard_pair(self, storage_key: str) -> None:
        try:
            sidecar = self.store.mask_sidecar_key(storage_key)
        except AppError:
            sidecar = None
        if sidecar is not None:
            self.store.discard(sidecar)
        self.store.discard(storage_key)


def load_task_mask(
    record: GenerativeMaskRecord,
    store: GeneratedAssetStore,
    *,
    max_bytes: int,
) -> MaskArray:
    try:
        path = store.resolve(record.storage_key)
        return read_mask(
            path,
            width=record.width,
            height=record.height,
            expected_sha256=record.sha256,
            max_bytes=max_bytes,
        )
    except ValueError as exc:
        raise AppError(
            409,
            "generative_mask_invalid",
            "The stored mask is damaged or does not match its record.",
        ) from exc


def mask_error_detail(view: GenerativeMaskView) -> dict[str, Any]:
    return {
        "maskId": str(view.mask_id),
        "width": view.width,
        "height": view.height,
        "coverage": view.quality.coverage,
        "warnings": view.quality.warnings,
    }


def _sidecar(record: GenerativeMaskRecord, payload: _StoredMaskPayload) -> dict[str, Any]:
    return {
        "schemaVersion": payload.schema_version,
        "maskId": record.id,
        "ownerId": record.owner_id,
        "imageId": record.image_id,
        "baseGeneratedAssetId": record.base_generated_asset_id,
        "kind": record.kind.value,
        "source": record.source.value,
        "coordinateSpace": record.coordinate_space,
        "width": record.width,
        "height": record.height,
        "sha256": record.sha256,
        "feather": record.feather,
        "inverted": record.inverted,
        "createdAt": record.created_at.astimezone(UTC).isoformat(timespec="milliseconds"),
        "definition": payload.definition.model_dump(mode="json"),
        "quality": payload.quality.model_dump(mode="json"),
        "semantic": None if payload.semantic is None else payload.semantic.model_dump(mode="json"),
    }


def _require_semantic_class(
    definition: GenerativeMaskDefinition,
) -> Literal["person", "sky"]:
    value = definition.semantic_class
    if value is None:
        raise AppError(
            422,
            "generative_mask_definition_invalid",
            "The mask definition is incomplete or inconsistent.",
            {"reasons": ["a semantic mask needs a supported semantic class"]},
        )
    return value


def _asset_id(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _uuid(value: str | None) -> UUID | None:
    return None if value is None else UUID(value)


__all__ = [
    "GenerativeMaskService",
    "load_task_mask",
    "mask_error_detail",
]
