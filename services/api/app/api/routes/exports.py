from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Depends, Response
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.api.deps import get_export_job_manager
from app.models.export import ExportJobRequest, ExportJobResponse
from app.models.schemas import ErrorResponse
from app.services.export_jobs import ExportJobManager

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post(
    "",
    response_model=ExportJobResponse,
    status_code=202,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Export session or revision not found",
        },
        422: {"model": ErrorResponse, "description": "Invalid export request"},
        503: {
            "model": ErrorResponse,
            "description": "Export queue is full or the service is shutting down",
        },
    },
)
def create_export_job(
    payload: ExportJobRequest,
    manager: Annotated[ExportJobManager, Depends(get_export_job_manager)],
) -> ExportJobResponse:
    job = manager.submit(str(payload.session_id), payload)
    return manager.response(job)


@router.get(
    "/{job_id}",
    response_model=ExportJobResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Export job not found"},
    },
)
def get_export_job(
    job_id: str,
    manager: Annotated[ExportJobManager, Depends(get_export_job_manager)],
) -> ExportJobResponse:
    return manager.response(manager.get(job_id))


@router.delete(
    "/{job_id}",
    status_code=204,
    responses={
        404: {"model": ErrorResponse, "description": "Export job not found"},
    },
)
def cancel_export_job(
    job_id: str,
    manager: Annotated[ExportJobManager, Depends(get_export_job_manager)],
) -> Response:
    manager.cancel(job_id)
    return Response(status_code=204)


@router.get(
    "/{job_id}/result",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Rendered export bytes",
            "content": {"image/jpeg": {}, "image/png": {}, "image/tiff": {}},
        },
        404: {
            "model": ErrorResponse,
            "description": "Export job or result file not found",
        },
        409: {
            "model": ErrorResponse,
            "description": "Export is not ready, was cancelled, or failed",
        },
    },
)
def download_export_result(
    job_id: str,
    manager: Annotated[ExportJobManager, Depends(get_export_job_manager)],
) -> StreamingResponse:
    job, stream, size = manager.open_result(job_id)
    headers = {
        "Content-Disposition": f'attachment; filename="{job.filename or job.id}"',
        "Content-Length": str(size),
        "X-Export-Width": str(job.width or ""),
        "X-Export-Height": str(job.height or ""),
        "X-Export-Bit-Depth": str(job.bit_depth),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if job.warnings:
        headers["X-Export-Warning"] = ",".join(job.warnings)
    return StreamingResponse(
        _file_chunks(stream),
        media_type=job.media_type or "application/octet-stream",
        headers=headers,
        background=BackgroundTask(stream.close),
    )


def _file_chunks(stream: BinaryIO, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    while chunk := stream.read(chunk_size):
        yield chunk
