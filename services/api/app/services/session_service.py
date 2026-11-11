from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.models.conversion import ConversionMode
from app.models.recipe import EditRecipe, default_recipe, recipe_hash, stored_recipe_json
from app.models.sessions import (
    CreateRevisionRequest,
    RevisionCreationSummary,
    RevisionListResponse,
    RevisionSource,
    RevisionSummary,
    RevisionView,
    SessionState,
)
from app.repositories.session_repo import (
    IdempotencyKeyReuseError,
    RevisionConflictError,
    RevisionCreation,
    RevisionNotFoundError,
    RevisionRecord,
    SessionNotFoundError,
    SessionRecord,
    SqliteSessionRepository,
)
from app.services.asset_resolver import ImageAssetResolver, ResolvedImage
from app.services.image_service import ImageService


@contextmanager
def _mapped() -> Iterator[None]:
    try:
        yield
    except SessionNotFoundError as exc:
        raise AppError(
            404,
            "session_not_found",
            "The requested session was not found.",
        ) from exc
    except RevisionNotFoundError as exc:
        raise AppError(
            404,
            "revision_not_found",
            "The requested revision was not found in this session.",
        ) from exc
    except RevisionConflictError as exc:
        raise AppError(
            409,
            "revision_conflict",
            "The edit state has changed; reload the session before committing.",
            {"activeRevisionId": exc.active_revision_id},
        ) from exc
    except IdempotencyKeyReuseError as exc:
        raise AppError(
            409,
            "idempotency_key_reuse",
            "The Idempotency-Key was already used with a different recipe or parent revision.",
            {"revisionId": exc.revision_id},
        ) from exc


class SessionService:
    def __init__(
        self,
        settings: Settings,
        images: ImageService,
        *,
        assets: ImageAssetResolver,
        repository: SqliteSessionRepository | None = None,
    ) -> None:
        self.settings = settings
        self.images = images
        self.assets = assets
        self.repository = repository or SqliteSessionRepository(settings.database_path)

    def create(self, image_id: str) -> SessionState:
        self.images.get_original(image_id)
        initial = default_recipe()
        with _mapped():
            session, _ = self.repository.create_session(
                image_id,
                recipe_json=stored_recipe_json(initial),
                recipe_hash=recipe_hash(initial),
            )
        return self._state(session)

    def get(self, session_id: str) -> SessionState:
        key = _session_key(session_id)
        with _mapped():
            session = self.repository.get(key)
        return self._state(session)

    def add_revision(
        self,
        session_id: str,
        request: CreateRevisionRequest,
        *,
        idempotency_key: str | None,
        creation: RevisionCreation | None = None,
    ) -> tuple[SessionState, bool]:
        key = _session_key(session_id)
        with _mapped():
            _, replayed = self.repository.add_revision(
                key,
                parent_id=str(request.parent_revision_id),
                recipe_json=stored_recipe_json(request.recipe),
                recipe_hash=recipe_hash(request.recipe),
                source=request.source,
                idempotency_key=idempotency_key,
                creation=creation,
            )
            session = self.repository.get(key)
        return self._state(session), replayed

    def idempotent_revision(
        self,
        session_id: str,
        idempotency_key: str | None,
    ) -> RevisionRecord | None:
        if idempotency_key is None:
            return None
        key = _session_key(session_id)
        with _mapped():
            return self.repository.get_by_idempotency(key, idempotency_key)

    def undo(self, session_id: str, expected_revision_id: UUID | None = None) -> SessionState:
        key = _session_key(session_id)
        with _mapped():
            new_active = self.repository.undo(
                key,
                None if expected_revision_id is None else str(expected_revision_id),
            )
            if new_active is None:
                raise AppError(
                    409,
                    "nothing_to_undo",
                    "There is no earlier revision to return to.",
                )
            session = self.repository.get(key)
        return self._state(session)

    def redo(self, session_id: str) -> SessionState:
        key = _session_key(session_id)
        with _mapped():
            new_active = self.repository.redo(key)
            if new_active is None:
                raise AppError(
                    409,
                    "nothing_to_redo",
                    "There is no later revision on the current history path.",
                )
            session = self.repository.get(key)
        return self._state(session)

    def activate(self, session_id: str, revision_id: UUID) -> SessionState:
        key = _session_key(session_id)
        with _mapped():
            self.repository.activate(key, str(revision_id))
            session = self.repository.get(key)
        return self._state(session)

    def get_revision(self, session_id: str, revision_id: UUID) -> RevisionView:
        key = _session_key(session_id)
        with _mapped():
            session = self.repository.get(key)
            record = self.repository.get_revision(key, str(revision_id))
        base = self.assets.resolve(session.image_id, record.base_generated_asset_id)
        return _view(record, base)

    def reset(self, session_id: str) -> SessionState:
        key = _session_key(session_id)
        default = default_recipe()
        with _mapped():
            self.repository.reset(
                key,
                default_recipe_json=stored_recipe_json(default),
                default_recipe_hash=recipe_hash(default),
            )
            session = self.repository.get(key)
        return self._state(session)

    def list_revisions(
        self,
        session_id: str,
        *,
        limit: int,
        cursor: int | None,
    ) -> RevisionListResponse:
        key = _session_key(session_id)
        with _mapped():
            records, next_cursor = self.repository.list_revisions(
                key,
                limit=limit,
                cursor=cursor,
            )
        return RevisionListResponse(
            items=[_summary(record) for record in records],
            next_cursor=None if next_cursor is None else str(next_cursor),
        )

    def _state(self, session: SessionRecord) -> SessionState:
        with _mapped():
            revision = self.repository.get_revision(session.id, session.active_revision_id)
            can_redo = self.repository.can_redo(
                session.id,
                active_revision_id=session.active_revision_id,
                head_revision_id=session.head_revision_id,
            )
        base = self.assets.resolve(
            session.image_id,
            revision.base_generated_asset_id,
        )
        return SessionState(
            session_id=UUID(session.id),
            image_id=UUID(session.image_id),
            active_revision_id=UUID(session.active_revision_id),
            head_revision_id=UUID(session.head_revision_id),
            can_undo=revision.parent_id is not None,
            can_redo=can_redo,
            revision=_view(revision, base),
        )


def _session_key(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AppError(
            404,
            "session_not_found",
            "The requested session was not found.",
        ) from exc


def _view(record: RevisionRecord, base: ResolvedImage) -> RevisionView:
    return RevisionView(
        id=UUID(record.id),
        revision_no=record.revision_no,
        parent_id=None if record.parent_id is None else UUID(record.parent_id),
        source=cast(RevisionSource, record.source),
        recipe=EditRecipe.model_validate_json(record.recipe_json),
        creation=_creation(record),
        base_generated_asset_id=(
            None
            if record.base_generated_asset_id is None
            else UUID(record.base_generated_asset_id)
        ),
        base_width=base.width,
        base_height=base.height,
        generative_task_id=(
            None if record.generative_task_id is None else UUID(record.generative_task_id)
        ),
        created_at=record.created_at,
    )


def _summary(record: RevisionRecord) -> RevisionSummary:
    return RevisionSummary(
        id=UUID(record.id),
        revision_no=record.revision_no,
        parent_id=None if record.parent_id is None else UUID(record.parent_id),
        source=cast(RevisionSource, record.source),
        recipe_hash=record.recipe_hash,
        creation=_creation(record),
        base_generated_asset_id=(
            None
            if record.base_generated_asset_id is None
            else UUID(record.base_generated_asset_id)
        ),
        generative_task_id=(
            None if record.generative_task_id is None else UUID(record.generative_task_id)
        ),
        created_at=record.created_at,
    )


def _creation(record: RevisionRecord) -> RevisionCreationSummary | None:
    if record.plan_id is None:
        return None
    return RevisionCreationSummary(
        plan_id=UUID(record.plan_id),
        style_id=record.style_id,
        style_version=record.style_version,
        conversion_mode=(
            None if record.conversion_mode is None else ConversionMode(record.conversion_mode)
        ),
        style_strength=record.style_strength,
        render_key=record.render_key,
    )
