from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Response

from app.api.deps import (
    get_deletion_service,
    get_export_service,
    get_render_service,
    get_session_service,
)
from app.models.export import ExportRequest
from app.models.render import CompareResponse, RenderRequest, RenderResponse
from app.models.schemas import ErrorResponse
from app.models.sessions import (
    ActivateRevisionRequest,
    CreateRevisionRequest,
    CreateSessionRequest,
    RevisionListResponse,
    SessionState,
    UndoRequest,
)
from app.services.deletion_service import DeletionService
from app.services.export_service import ExportService, apply_provenance_headers
from app.services.render_service import RenderService
from app.services.session_service import SessionService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Session, image, or revision not found",
        409: "Revision conflict, no undo/redo step available, or resource busy",
        422: "Invalid request payload",
    }.items()
}
_RENDER_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorResponse, "description": "A newer render request superseded this one"},
    503: {"model": ErrorResponse, "description": "Rendering is busy"},
}
_EXPORT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorResponse, "description": "Export would exceed the memory budget"},
    503: {"model": ErrorResponse, "description": "Another export is in progress"},
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


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    service: Annotated[DeletionService, Depends(get_deletion_service)],
) -> Response:
    service.delete_session(session_id)
    return Response(status_code=204)


@router.get("/{session_id}/revisions", response_model=RevisionListResponse)
def list_revisions(
    session_id: str,
    service: Annotated[SessionService, Depends(get_session_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[int | None, Query(ge=1)] = None,
) -> RevisionListResponse:
    return service.list_revisions(session_id, limit=limit, cursor=cursor)


@router.post(
    "/{session_id}/render",
    response_model=RenderResponse,
    responses=_RENDER_ERROR_RESPONSES,
)
def render_preview(
    session_id: str,
    payload: RenderRequest,
    service: Annotated[RenderService, Depends(get_render_service)],
    render_seq: Annotated[int | None, Header(alias="X-Render-Seq", ge=0)] = None,
) -> RenderResponse:
    result = service.render(session_id, payload, render_seq=render_seq)
    return RenderResponse(
        preview_url=result.preview_url,
        width=result.width,
        height=result.height,
        quality=result.quality,
        cache_hit=result.cache_hit,
        warnings=list(result.warnings),
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


@router.get(
    "/{session_id}/compare",
    response_model=CompareResponse,
    responses={503: {"model": ErrorResponse, "description": "Rendering is busy"}},
)
def compare_revision(
    session_id: str,
    service: Annotated[RenderService, Depends(get_render_service)],
    revision_id: Annotated[UUID | None, Query(alias="revisionId")] = None,
    max_edge: Annotated[int, Query(alias="maxEdge", ge=1, le=2560)] = 1600,
) -> CompareResponse:
    return service.compare(session_id, revision_id=revision_id, max_edge=max_edge)


@router.post(
    "/{session_id}/export",
    responses=_EXPORT_ERROR_RESPONSES,
    deprecated=True,
)
def export_revision(
    session_id: str,
    payload: ExportRequest,
    service: Annotated[ExportService, Depends(get_export_service)],
) -> Response:
    result = service.export(session_id, payload)
    headers = {
        "Content-Disposition": f'attachment; filename="{result.filename}"',
        "X-Export-Width": str(result.width),
        "X-Export-Height": str(result.height),
        "X-Export-Bit-Depth": str(result.bit_depth),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if result.warnings:
        headers["X-Export-Warning"] = ",".join(result.warnings)
    apply_provenance_headers(
        headers,
        ai_generated=result.ai_generated,
        provenance=result.ai_provenance,
    )
    return Response(content=result.data, media_type=result.media_type, headers=headers)
