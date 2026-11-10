from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import FileResponse

from app.api.deps import get_generative_service, get_owner_scope
from app.core.identity import OwnerScope
from app.models.generative import (
    GenerativeCapabilitiesResponse,
    GenerativeResultView,
    GenerativeTaskCreated,
    GenerativeTaskListResponse,
    GenerativeTaskRequest,
    GenerativeTaskStatus,
    GenerativeTaskStatusResponse,
)
from app.models.schemas import ErrorResponse
from app.models.sessions import SessionState
from app.services.generative_service import GenerativeTaskService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Generative task, result, or asset not found",
        409: "Task state, mask, or base revision conflict",
        413: "Generative input or output exceeds the configured limit",
        422: "Invalid request, unsupported capability, or missing consent",
        502: "Provider returned an invalid or blank image",
        503: "Generation queue is full or the pipeline is unavailable",
        504: "Generation timed out",
    }.items()
}

router = APIRouter(
    prefix="/generative",
    tags=["generative"],
    responses=_ERROR_RESPONSES,
)


@router.get("/capabilities", response_model=GenerativeCapabilitiesResponse)
def get_capabilities(
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
) -> GenerativeCapabilitiesResponse:
    return service.capabilities()


@router.post("/tasks", response_model=GenerativeTaskCreated, status_code=201)
def create_task(
    payload: GenerativeTaskRequest,
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=200),
    ] = None,
) -> GenerativeTaskCreated:
    key = idempotency_key.strip() if idempotency_key else None
    created, deduplicated = service.create(
        payload,
        owner=owner,
        idempotency_key=key or None,
    )
    if deduplicated:
        response.status_code = 200
    return created


@router.get("/tasks", response_model=GenerativeTaskListResponse)
def list_tasks(
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[GenerativeTaskStatus | None, Query()] = None,
) -> GenerativeTaskListResponse:
    return service.list_tasks(
        owner=owner,
        limit=limit,
        offset=offset,
        status=status,
    )


@router.get("/tasks/{task_id}", response_model=GenerativeTaskStatusResponse)
def get_task(
    task_id: str,
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> GenerativeTaskStatusResponse:
    return service.status(task_id, owner=owner)


@router.post("/tasks/{task_id}/cancel", response_model=GenerativeTaskStatusResponse)
def cancel_task(
    task_id: str,
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> GenerativeTaskStatusResponse:
    return service.cancel(task_id, owner=owner)


@router.post("/tasks/{task_id}/retry", response_model=GenerativeTaskStatusResponse)
def retry_task(
    task_id: str,
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> GenerativeTaskStatusResponse:
    return service.retry(task_id, owner=owner)


@router.get(
    "/results/{result_id}/image",
    response_class=FileResponse,
    responses={
        200: {
            "description": "Candidate result bytes",
            "content": {"image/png": {}},
        },
        404: {"model": ErrorResponse, "description": "Result or file not found"},
    },
)
def get_result_image(
    result_id: str,
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> FileResponse:
    path, media_type = service.result_image(result_id, owner=owner)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="generative-{result_id[:8]}.png"',
        },
    )


@router.post("/results/{result_id}/accept", response_model=SessionState)
def accept_result(
    result_id: str,
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> SessionState:
    return service.accept_result(result_id, owner=owner)


@router.post("/results/{result_id}/reject", response_model=GenerativeResultView)
def reject_result(
    result_id: str,
    service: Annotated[GenerativeTaskService, Depends(get_generative_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> GenerativeResultView:
    return service.reject_result(result_id, owner=owner)


__all__ = ["router"]
