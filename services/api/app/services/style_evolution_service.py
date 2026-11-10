from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.errors import AppError
from app.models.personal_style import (
    PersonalStyleChangeSource,
    PersonalStyleDetailResponse,
)
from app.models.style_evolution import (
    StyleEvolutionApplyRequest,
    StyleEvolutionListResponse,
    StyleEvolutionPreviewRequest,
    StyleEvolutionPreviewResponse,
    StyleEvolutionRecord,
    StyleEvolutionStatus,
    StyleFeedbackCreateRequest,
    StyleFeedbackListResponse,
    StyleFeedbackRecord,
    StyleFeedbackScope,
)
from app.repositories.style_evolution_repo import (
    EvolutionRow,
    FeedbackRow,
    SqliteStyleEvolutionRepository,
)
from app.services.personal_style_service import PersonalStyleService, _changed_fields
from app.styles.evolution import evolve_profile

logger = logging.getLogger("frame_ai.style_evolution")


def _next_version(version: str) -> str:
    major, _, minor = version.partition(".")
    return f"{major}.{int(minor) + 1}"


def _feedback_not_found() -> AppError:
    return AppError(
        404,
        "personal_style_feedback_not_found",
        "The feedback does not belong to this personal style.",
    )


def _evolution_not_found() -> AppError:
    return AppError(
        404,
        "personal_style_evolution_not_found",
        "The evolution proposal is not available.",
    )


def _confirmation_required() -> AppError:
    return AppError(
        409,
        "confirmation_required",
        "Applying an evolution proposal requires explicit confirmation.",
    )


def _feedback_required() -> AppError:
    return AppError(
        409,
        "personal_style_feedback_required",
        "Add at least one personal-style feedback before evolving the profile.",
    )


def _version_conflict() -> AppError:
    return AppError(
        409,
        "personal_style_version_conflict",
        "The style changed since this proposal was previewed; preview again before applying.",
    )


def _evolution_not_proposed() -> AppError:
    return AppError(
        409,
        "personal_style_evolution_not_proposed",
        "Only a proposed evolution can be applied or discarded.",
    )


def _feedback_already_applied() -> AppError:
    return AppError(
        409,
        "personal_style_feedback_already_applied",
        "This feedback has already been applied to a version.",
    )


def _invalid_feedback_scope() -> AppError:
    return AppError(
        422,
        "personal_style_feedback_scope",
        "Only personal-style (profile) feedback can evolve the profile; single-edit feedback "
        "affects just the current work.",
    )


def _feedback_record(row: FeedbackRow) -> StyleFeedbackRecord:
    return StyleFeedbackRecord(
        id=UUID(row.id),
        style_id=row.style_id,
        style_version=row.style_version,
        feedback_type=row.feedback_type,
        note=row.note,
        scope=row.scope,
        applied_version=row.applied_version,
        created_at=row.created_at,
    )


def _evolution_record(row: EvolutionRow) -> StyleEvolutionRecord:
    return StyleEvolutionRecord(
        id=UUID(row.id),
        style_id=row.style_id,
        base_version=row.base_version,
        new_version=row.new_version,
        feedback_ids=tuple(UUID(item) for item in row.feedback_ids),
        reason=row.reason,
        summary=row.summary,
        candidate=row.candidate,
        definition=row.definition,
        status=row.status,
        created_at=row.created_at,
        confirmed_at=row.confirmed_at,
    )


class StyleEvolutionService:
    def __init__(
        self,
        repository: SqliteStyleEvolutionRepository,
        styles: PersonalStyleService,
    ) -> None:
        self._repository = repository
        self._styles = styles

    def add_feedback(
        self,
        style_id: str,
        request: StyleFeedbackCreateRequest,
        *,
        owner_id: str,
    ) -> StyleFeedbackRecord:
        detail = self._styles.detail(style_id, owner_id=owner_id)
        feedback = StyleFeedbackRecord(
            id=uuid4(),
            style_id=style_id,
            style_version=request.style_version or detail.style.version,
            feedback_type=request.feedback_type,
            note=request.note,
            scope=request.scope,
            created_at=datetime.now(UTC),
        )
        self._repository.add_feedback(feedback, owner_id=owner_id)
        logger.info(
            "style_feedback_added style_id=%s type=%s scope=%s",
            style_id,
            feedback.feedback_type.value,
            feedback.scope.value,
        )
        return feedback

    def list_feedback(
        self,
        style_id: str,
        *,
        owner_id: str,
        scope: StyleFeedbackScope | None = None,
    ) -> StyleFeedbackListResponse:
        self._styles.detail(style_id, owner_id=owner_id)
        rows = self._repository.list_feedback(style_id, owner_id=owner_id, scope=scope)
        return StyleFeedbackListResponse(
            style_id=style_id,
            feedbacks=tuple(_feedback_record(row) for row in rows),
        )

    def delete_feedback(self, style_id: str, feedback_id: str, *, owner_id: str) -> None:
        self._styles.detail(style_id, owner_id=owner_id)
        row = self._repository.get_feedback(style_id, feedback_id, owner_id=owner_id)
        if row is None:
            raise _feedback_not_found()
        if row.applied_version is not None:
            raise _feedback_already_applied()
        self._repository.delete_feedback(style_id, feedback_id, owner_id=owner_id)

    def preview(
        self,
        style_id: str,
        request: StyleEvolutionPreviewRequest,
        *,
        owner_id: str,
    ) -> StyleEvolutionPreviewResponse:
        detail = self._styles.detail(style_id, owner_id=owner_id)
        rows = self._select_feedback(style_id, request, owner_id=owner_id)
        if not rows:
            raise _feedback_required()
        outcome = evolve_profile(
            detail.style,
            detail.definition,
            [row.feedback_type for row in rows],
            notes=[row.note for row in rows if row.note],
            note=request.note,
            version=_next_version(detail.style.version),
        )
        changes = _changed_fields(
            {
                "profile": detail.style.model_dump(mode="json", by_alias=True),
                "definition": detail.definition.model_dump(mode="json", by_alias=True),
            },
            {
                "profile": outcome.profile.model_dump(mode="json", by_alias=True),
                "definition": outcome.definition.model_dump(mode="json", by_alias=True),
            },
        )
        evolution = StyleEvolutionRecord(
            id=uuid4(),
            style_id=style_id,
            base_version=detail.style.version,
            feedback_ids=tuple(UUID(row.id) for row in rows),
            reason=outcome.reason,
            summary=outcome.summary,
            candidate=outcome.profile,
            definition=outcome.definition,
            status=StyleEvolutionStatus.PROPOSED,
            created_at=datetime.now(UTC),
        )
        self._repository.add_evolution(evolution, owner_id=owner_id)
        logger.info(
            "style_evolution_previewed style_id=%s evolution_id=%s feedback_count=%s",
            style_id,
            evolution.id,
            outcome.feedback_count,
        )
        return StyleEvolutionPreviewResponse(
            evolution=evolution,
            changes=changes,
            adjustments=outcome.adjustments,
            limitations=outcome.limitations,
            feedback_count=outcome.feedback_count,
        )

    def apply(
        self,
        style_id: str,
        evolution_id: str,
        request: StyleEvolutionApplyRequest,
        *,
        owner_id: str,
    ) -> PersonalStyleDetailResponse:
        if not request.confirm:
            raise _confirmation_required()
        detail = self._styles.detail(style_id, owner_id=owner_id)
        row = self._repository.get_evolution(style_id, evolution_id, owner_id=owner_id)
        if row is None:
            raise _evolution_not_found()
        if row.status is not StyleEvolutionStatus.PROPOSED:
            raise _evolution_not_proposed()
        if row.base_version != detail.style.version:
            raise _version_conflict()
        definition = row.definition.model_copy(update={"note": request.note or row.definition.note})
        result = self._styles.apply_profile_version(
            style_id,
            row.candidate,
            definition,
            owner_id=owner_id,
            change_source=PersonalStyleChangeSource.EVOLUTION,
            change_note=row.reason,
        )
        new_version = result.style.version
        self._repository.mark_feedbacks_applied(
            style_id,
            row.feedback_ids,
            owner_id=owner_id,
            applied_version=new_version,
        )
        if not self._repository.confirm_evolution(
            style_id,
            evolution_id,
            owner_id=owner_id,
            new_version=new_version,
            confirmed_at=datetime.now(UTC),
        ):
            raise _evolution_not_proposed()
        logger.info(
            "style_evolution_confirmed style_id=%s evolution_id=%s base=%s new=%s",
            style_id,
            evolution_id,
            row.base_version,
            new_version,
        )
        return result

    def discard(self, style_id: str, evolution_id: str, *, owner_id: str) -> None:
        self._styles.detail(style_id, owner_id=owner_id)
        row = self._repository.get_evolution(style_id, evolution_id, owner_id=owner_id)
        if row is None:
            raise _evolution_not_found()
        if row.status is not StyleEvolutionStatus.PROPOSED:
            raise _evolution_not_proposed()
        self._repository.discard_evolution(style_id, evolution_id, owner_id=owner_id)

    def list_evolutions(self, style_id: str, *, owner_id: str) -> StyleEvolutionListResponse:
        self._styles.detail(style_id, owner_id=owner_id)
        rows = self._repository.list_evolutions(style_id, owner_id=owner_id)
        return StyleEvolutionListResponse(
            style_id=style_id,
            evolutions=tuple(_evolution_record(row) for row in rows),
        )

    def _select_feedback(
        self,
        style_id: str,
        request: StyleEvolutionPreviewRequest,
        *,
        owner_id: str,
    ) -> list[FeedbackRow]:
        if request.feedback_ids is None:
            return self._repository.list_feedback(
                style_id,
                owner_id=owner_id,
                scope=StyleFeedbackScope.PROFILE,
                unapplied_only=True,
            )
        rows: list[FeedbackRow] = []
        for feedback_id in request.feedback_ids:
            row = self._repository.get_feedback(style_id, str(feedback_id), owner_id=owner_id)
            if row is None:
                raise _feedback_not_found()
            if row.scope is not StyleFeedbackScope.PROFILE:
                raise _invalid_feedback_scope()
            if row.applied_version is not None:
                raise _feedback_already_applied()
            rows.append(row)
        return rows


__all__ = ["StyleEvolutionService"]
