from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Response

from app.ai.contracts import SceneLabel
from app.api.deps import get_owner_scope, get_photographer_service
from app.core.identity import OwnerScope
from app.models.photographer import (
    MAX_FEEDBACK_ROWS,
    AcceptPlanRequest,
    ConversionModeListResponse,
    CritiqueApplyRequest,
    CritiqueApplyResponse,
    CritiqueResponse,
    PhotographerCritiqueRequest,
    PhotographerFeedbackListResponse,
    PhotographerFeedbackRequest,
    PhotographerFeedbackResponse,
    PhotographerPatchRequest,
    PhotographerPatchResponse,
    PhotographerPlanRequest,
    PhotographerPlanResponse,
    PhotographerStyleId,
    StyleCategory,
    StyleDefinition,
    StyleListResponse,
)
from app.models.schemas import ErrorResponse
from app.models.sessions import SessionState
from app.photographer.service import PhotographerService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Session, analysis, plan, style, or feedback record not found",
        409: "Analysis required or report does not match the image",
        422: "Request payload or generated recipe invalid",
        500: "Plan or patch could not be stored",
        502: "Planner returned invalid output",
        503: "Planner not configured, unavailable, or busy",
        504: "Planner timed out",
    }.items()
}

router = APIRouter(prefix="/ai/photographer", tags=["photographer"], responses=_ERROR_RESPONSES)


@router.get("/styles", response_model=StyleListResponse)
def list_styles(
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
    category: Annotated[
        StyleCategory | None, Query(description="Filter by style category.")
    ] = None,
    scene: Annotated[SceneLabel | None, Query(description="Filter by supported scene.")] = None,
    include_disabled: Annotated[
        bool, Query(description="Include styles that are switched off.")
    ] = False,
) -> StyleListResponse:
    return service.list_styles(
        category=category,
        scene=scene,
        include_disabled=include_disabled,
    )


@router.get("/styles/{style_id}", response_model=StyleDefinition)
def read_style(
    style_id: Annotated[PhotographerStyleId, Path(description="Style identifier.")],
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
) -> StyleDefinition:
    return service.style_detail(style_id)


@router.get("/conversion-modes", response_model=ConversionModeListResponse)
def list_conversion_modes(
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
) -> ConversionModeListResponse:
    return service.list_conversion_modes()


@router.post("/plan", response_model=PhotographerPlanResponse)
def create_plan(
    payload: PhotographerPlanRequest,
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PhotographerPlanResponse:
    return service.plan(payload, owner_id=owner.owner_id)


@router.post("/plan/{plan_id}/accept", response_model=SessionState)
def accept_plan(
    plan_id: UUID,
    payload: AcceptPlanRequest,
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> SessionState:
    key = idempotency_key.strip() if idempotency_key else None
    return service.accept_plan(str(plan_id), payload, idempotency_key=key or None)


@router.post(
    "/chat",
    response_model=PhotographerPatchResponse,
    responses={
        200: {
            "description": (
                "Always a full patch result. Requests the engine cannot satisfy return "
                "supported=false with the recipe unchanged, not an error code."
            )
        }
    },
)
def create_patch(
    payload: PhotographerPatchRequest,
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
) -> PhotographerPatchResponse:
    return service.patch(payload)


@router.post("/critique", response_model=CritiqueResponse)
def create_critique(
    payload: PhotographerCritiqueRequest,
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
) -> CritiqueResponse:
    return service.critique(payload)


@router.post("/critique/apply", response_model=CritiqueApplyResponse)
def apply_critique(
    payload: CritiqueApplyRequest,
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
) -> CritiqueApplyResponse:
    return service.apply_critique(payload)


@router.post(
    "/feedback",
    response_model=PhotographerFeedbackResponse,
    responses={
        200: {
            "description": (
                "One stored user decision. 'modified' is derived by the server when the "
                "referenced revision no longer matches the plan it came from."
            )
        }
    },
)
def create_feedback(
    payload: PhotographerFeedbackRequest,
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
) -> PhotographerFeedbackResponse:
    return service.record_feedback(payload)


@router.get("/feedback", response_model=PhotographerFeedbackListResponse)
def read_feedback(
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
    session_id: Annotated[
        UUID | None, Query(alias="sessionId", description="Only this session's records.")
    ] = None,
    image_id: Annotated[
        UUID | None, Query(alias="imageId", description="Only this image's records.")
    ] = None,
    plan_id: Annotated[
        UUID | None, Query(alias="planId", description="Only records about this plan.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_FEEDBACK_ROWS)] = 50,
) -> PhotographerFeedbackListResponse:
    return service.list_feedback(
        session_id=session_id,
        image_id=image_id,
        plan_id=plan_id,
        limit=limit,
    )


@router.delete("/feedback/{feedback_id}", status_code=204)
def remove_feedback(
    feedback_id: Annotated[UUID, Path(description="Feedback record identifier.")],
    service: Annotated[PhotographerService, Depends(get_photographer_service)],
) -> Response:
    service.delete_feedback(feedback_id)
    return Response(status_code=204)
