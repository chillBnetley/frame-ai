from __future__ import annotations

from uuid import UUID

from app.core.errors import AppError
from app.models.personal_style import (
    PersonalStyleChangeSource,
    PersonalStyleDefinition,
    PersonalStyleProfile,
    PersonalStyleReference,
    PersonalStyleReferenceStatus,
)
from app.models.style_fusion import (
    PersonalStyleFusionRequest,
    PersonalStyleFusionResponse,
    PersonalStyleReferenceContribution,
)
from app.models.style_profile import StyleSource
from app.repositories.personal_style_repo import (
    PersonalStyleNotFoundError,
    PersonalStyleRecord,
    PersonalStyleVersionConflictError,
    SqlitePersonalStyleRepository,
)
from app.visual_dna.fusion import (
    FusionOutcome,
    FusionPhoto,
    fuse_photo_features,
    fusion_weight,
)


def _not_found() -> AppError:
    return AppError(404, "personal_style_not_found", "The personal style is not available.")


def _reference_not_found() -> AppError:
    return AppError(
        404,
        "personal_style_reference_not_found",
        "The reference photo does not belong to this personal style.",
    )


def _analysis_required() -> AppError:
    return AppError(
        409,
        "personal_style_analysis_required",
        "Run Visual DNA analysis for at least one reference photo before fusing.",
    )


def _next_version(version: str) -> str:
    major, _, minor = version.partition(".")
    return f"{major}.{int(minor) + 1}"


class StyleFusionService:
    def __init__(self, repository: SqlitePersonalStyleRepository) -> None:
        self._repository = repository

    def fuse(
        self,
        style_id: str,
        request: PersonalStyleFusionRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleFusionResponse:
        record = self._require(style_id, owner_id)
        references = self._repository.list_references(style_id, owner_id=owner_id)
        selected = self._select(references, request.reference_ids)
        features = self._repository.list_features(style_id, owner_id=owner_id)
        photos = [
            FusionPhoto(
                reference_id=str(reference.id),
                image_id=None if reference.image_id is None else str(reference.image_id),
                features=features[str(reference.id)],
            )
            for reference in selected
            if str(reference.id) in features
        ]
        if not photos:
            raise _analysis_required()
        outcome = fuse_photo_features(photos, avoid=record.profile.personal.avoid)
        missing = len(selected) - len(photos)
        limitations = list(outcome.limitations)
        if missing:
            limitations.append(f"{missing} 张参考照片尚未完成分析，未参与本次融合。")

        updated = self._merge(record.profile, record.definition, outcome, len(photos))
        definition = record.definition.model_copy(
            update={"note": request.note or record.definition.note}
        )
        try:
            self._repository.add_version(
                updated,
                definition,
                owner_id=owner_id,
                change_source=PersonalStyleChangeSource.ANALYSIS,
                change_note=request.note or f"融合 {len(photos)} 张参考照片",
            )
        except PersonalStyleNotFoundError as exc:
            raise _not_found() from exc
        except PersonalStyleVersionConflictError as exc:
            raise AppError(
                409,
                "personal_style_version_conflict",
                "The personal style version conflicts with the stored history.",
            ) from exc

        saved = self._require(style_id, owner_id)
        contributions = tuple(
            PersonalStyleReferenceContribution(
                reference_id=UUID(photo.reference_id),
                image_id=None if photo.image_id is None else UUID(photo.image_id),
                scene=photo.features.scene.primary,
                confidence=photo.features.overall_confidence,
                weight=round(fusion_weight(photo.features), 3),
                anomaly_count=len(photo.features.anomalies),
            )
            for photo in photos
        )
        return PersonalStyleFusionResponse(
            style=saved.profile,
            definition=saved.definition,
            version=saved.profile.version,
            status=saved.head.status,
            favorite=saved.head.favorite,
            summary=outcome.summary,
            sections=outcome.sections,
            conflicts=outcome.conflicts,
            scenes=outcome.scenes,
            contributions=contributions,
            occasional=outcome.occasional,
            stability=outcome.stability,
            confidence=outcome.confidence,
            sample_count=outcome.sample_count,
            anomaly_count=outcome.anomaly_count,
            default_strength=outcome.default_strength,
            limitations=tuple(limitations)[:12],
            created_at=saved.head.updated_at,
        )

    def _merge(
        self,
        current: PersonalStyleProfile,
        definition: PersonalStyleDefinition,
        outcome: FusionOutcome,
        sample_count: int,
    ) -> PersonalStyleProfile:
        overrides = definition.user_overrides
        scene_fit = (
            current.scene_fit
            if "sceneFit.suitable" in overrides
            else outcome.scene_fit
        )
        targets = (
            current.personal.targets
            if "personal.targets" in overrides
            else outcome.targets
        )
        constraints = tuple(
            dict.fromkeys((*current.constraints, *outcome.constraints))
        )[:11]
        personal = current.personal.model_copy(
            update={
                "confidence": outcome.confidence,
                "stability": outcome.stability,
                "targets": targets,
                "scene_targets": outcome.scene_targets,
                "protected": outcome.protected,
                "sample_count": sample_count,
                "anomaly_count": outcome.anomaly_count,
            }
        )
        sources = tuple(
            source
            for source in current.sources
            if not source.title.startswith("个人参考照片分析")
        )
        provenance = StyleSource(
            title=f"个人参考照片分析（{sample_count} 张）",
            license="用户主动授权，不用于模型训练",
        )
        return current.model_copy(
            update={
                "version": _next_version(current.version),
                "description": (
                    current.description
                    if "description" in overrides
                    else outcome.summary
                ),
                "color": outcome.color,
                "light": outcome.light,
                "composition": outcome.composition,
                "texture": outcome.texture,
                "scene_fit": scene_fit,
                "constraints": constraints,
                "envelope": outcome.envelope,
                "default_strength": outcome.default_strength,
                "sources": (*sources, provenance)[-8:],
                "personal": personal,
            }
        )

    def _select(
        self,
        references: list[PersonalStyleReference],
        requested: tuple[UUID, ...] | None,
    ) -> list[PersonalStyleReference]:
        if requested is None:
            return [
                reference
                for reference in references
                if reference.status is PersonalStyleReferenceStatus.ACTIVE
                and reference.image_id is not None
            ]
        by_id = {str(reference.id): reference for reference in references}
        missing = [
            str(reference_id)
            for reference_id in requested
            if str(reference_id) not in by_id
        ]
        if missing:
            raise _reference_not_found()
        return [by_id[str(reference_id)] for reference_id in requested]

    def _require(self, style_id: str, owner_id: str) -> PersonalStyleRecord:
        record = self._repository.get(style_id, owner_id=owner_id)
        if record is None:
            raise _not_found()
        return record


__all__ = ["StyleFusionService"]
