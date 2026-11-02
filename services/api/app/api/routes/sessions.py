from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Response

from app.api.deps import get_render_service, get_session_service
from app.models.render import RenderRequest, RenderResponse
from app.models.schemas import ErrorResponse
from app.models.sessions import (
    ActivateRevisionRequest,
    CreateRevisionRequest,
    CreateSessionRequest,
    RevisionListResponse,
    SessionState,
    UndoRequest,
)
from app.services.render_service import RenderService
from app.services.session_service import SessionService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Session, image, or revision not found",
        409: "Revision conflict or no undo/redo step available",
        422: "Invalid request payload",
    }.items()
}

router = APIRouter(prefix="/sessions", tags=["sessions"], responses=_ERROR_RESPONSES)


@router.post("", response_model=SessionState, status_code=201)
def create_session(
    payload: CreateSessionRequest,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionState:
    return service.create(str(payload.image_id))


@router.get("/{session_id}", response_model=SessionState)
def get_session(
    session_id: str,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionState:
    return service.get(session_id)


@router.get("/{session_id}/revisions", response_model=RevisionListResponse)
def list_revisions(
    session_id: str,
    service: Annotated[SessionService, Depends(get_session_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[int | None, Query(ge=1)] = None,
) -> RevisionListResponse:
    return service.list_revisions(session_id, limit=limit, cursor=cursor)


@router.post("/{session_id}/render", response_model=RenderResponse)
def render_preview(
    session_id: str,
    payload: RenderRequest,
    service: Annotated[RenderService, Depends(get_render_service)],
) -> RenderResponse:
    result = service.render(session_id, payload)
    return RenderResponse(
        preview_url=result.preview_url,
        width=result.width,
        height=result.height,
        quality=result.quality,
        cache_hit=result.cache_hit,
    )


@router.post("/{session_id}/revisions", response_model=SessionState, status_code=201)
def create_revision(
    session_id: str,
    payload: CreateRevisionRequest,
    service: Annotated[SessionService, Depends(get_session_service)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> SessionState:
    key = idempotency_key.strip() if idempotency_key else None
    state, replayed = service.add_revision(
        session_id,
        payload,
        idempotency_key=key or None,
    )
    if replayed:
        response.status_code = 200
    return state


@router.post("/{session_id}/undo", response_model=SessionState)
def undo(
    session_id: str,
    service: Annotated[SessionService, Depends(get_session_service)],
    payload: Annotated[UndoRequest | None, Body()] = None,
) -> SessionState:
    expected = None if payload is None else payload.revision_id
    return service.undo(session_id, expected)


@router.post("/{session_id}/redo", response_model=SessionState)
def redo(
    session_id: str,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionState:
    return service.redo(session_id)


@router.post("/{session_id}/activate", response_model=SessionState)
def activate(
    session_id: str,
    payload: ActivateRevisionRequest,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionState:
    return service.activate(session_id, payload.revision_id)


@router.post("/{session_id}/reset", response_model=SessionState)
def reset(
    session_id: str,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionState:
    return service.reset(session_id)
