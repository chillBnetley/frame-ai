from __future__ import annotations

import logging

from app.core.errors import AppError
from app.models.personal_style import (
    PersonalStyleChangeSource,
    PersonalStyleDetailResponse,
)
from app.models.style_mix import (
    StyleMixPreviewResponse,
    StyleMixRequest,
    StyleMixSaveRequest,
    StyleMixSourceRef,
)
from app.models.style_profile import StyleProfile
from app.repositories.personal_style_repo import SqlitePersonalStyleRepository
from app.repositories.style_repo import SqliteStyleProfileRepository
from app.services.personal_style_service import PersonalStyleService
from app.styles.mixing import mix_styles

logger = logging.getLogger("frame_ai.style_mix")


def _source_not_found() -> AppError:
    return AppError(404, "style_not_found", "One of the source styles is not available.")


class StyleMixService:
    def __init__(
        self,
        styles: SqliteStyleProfileRepository,
        personal_styles: SqlitePersonalStyleRepository,
        personal_style_service: PersonalStyleService,
    ) -> None:
        self._styles = styles
        self._personal_styles = personal_styles
        self._personal_style_service = personal_style_service

    def preview(self, request: StyleMixRequest, *, owner_id: str) -> StyleMixPreviewResponse:
        a = self._resolve(request.style_a, owner_id)
        b = self._resolve(request.style_b, owner_id)
        outcome = mix_styles(
            a,
            b,
            weight=request.weight,
            sources=request.sources,
            resolutions=request.resolutions,
        )
        return StyleMixPreviewResponse(
            profile=outcome.profile,
            definition=outcome.definition,
            weight=outcome.weight,
            sources=outcome.sources,
            dimensions=outcome.dimensions,
            conflicts=outcome.conflicts,
            protections=outcome.protections,
            summary=outcome.summary,
            limitations=outcome.limitations,
            provenance=outcome.provenance,
        )

    def save(self, request: StyleMixSaveRequest, *, owner_id: str) -> PersonalStyleDetailResponse:
        a = self._resolve(request.style_a, owner_id)
        b = self._resolve(request.style_b, owner_id)
        outcome = mix_styles(
            a,
            b,
            weight=request.weight,
            sources=request.sources,
            resolutions=request.resolutions,
            name=request.name,
            description=request.description,
            target_overrides=request.targets,
            avoid_overrides=request.avoid,
            note=request.note,
        )
        detail = self._personal_style_service.create_from_profile(
            outcome.profile,
            outcome.definition,
            owner_id=owner_id,
            change_source=PersonalStyleChangeSource.MIX,
            change_note=request.note or f"混合「{a.name}」与「{b.name}」。",
        )
        logger.info(
            "style_mix_saved style_id=%s source_a=%s source_b=%s weight=%s conflicts=%s",
            detail.style.id,
            a.id,
            b.id,
            request.weight,
            len(outcome.conflicts),
        )
        return detail

    def _resolve(self, ref: StyleMixSourceRef, owner_id: str) -> StyleProfile:
        if ref.style_id.startswith("personal_"):
            record = self._personal_styles.get(ref.style_id, owner_id=owner_id, version=ref.version)
            if record is None:
                raise _source_not_found()
            return record.profile
        profile = self._styles.get(ref.style_id, version=ref.version)
        if profile is None:
            raise _source_not_found()
        return profile


__all__ = ["StyleMixService"]
