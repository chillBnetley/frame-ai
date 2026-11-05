from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_analysis_task_service
from app.models.analysis_report import AnalysisReport
from app.models.analysis_task import (
    AnalysisTaskCreated,
    AnalysisTaskCreateRequest,
    AnalysisTaskStatusResponse,
)
from app.models.schemas import ErrorResponse
from app.services.analysis_task_service import AnalysisTaskService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        400: "All analysis options were disabled",
        404: "Analysis task or image not found",
        409: "Result not ready or task still processing",
        413: "Analysis input copy exceeded the size limit",
        500: "Analysis failed",
        502: "Provider returned invalid output",
        503: "Provider not configured or unavailable",
        504: "Provider timed out",
    }.items()
}

router = APIRouter(prefix="/analysis", tags=["analysis"], responses=_ERROR_RESPONSES)


@router.post("", response_model=AnalysisTaskCreated, status_code=202)
def create_analysis(
    request: AnalysisTaskCreateRequest,
    response: Response,
    service: Annotated[AnalysisTaskService, Depends(get_analysis_task_service)],
) -> AnalysisTaskCreated:
    outcome = service.create(
        str(request.image_id),
        request.options,
        force=request.force,
    )
    if outcome.deduplicated:
        response.status_code = 200
    return outcome.response()


@router.get("/{analysis_id}", response_model=AnalysisTaskStatusResponse)
def get_analysis(
    analysis_id: UUID,
    service: Annotated[AnalysisTaskService, Depends(get_analysis_task_service)],
) -> AnalysisTaskStatusResponse:
    return service.status(str(analysis_id))


@router.get("/{analysis_id}/result", response_model=AnalysisReport)
def get_analysis_result(
    analysis_id: UUID,
    service: Annotated[AnalysisTaskService, Depends(get_analysis_task_service)],
) -> AnalysisReport:
    return service.result(str(analysis_id))


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(
    analysis_id: UUID,
    service: Annotated[AnalysisTaskService, Depends(get_analysis_task_service)],
) -> Response:
    service.delete(str(analysis_id))
    return Response(status_code=204)
