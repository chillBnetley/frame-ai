from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.deps import get_render_service
from app.core.errors import AppError
from app.models.schemas import ErrorResponse
from app.services.render_service import RenderService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Preview expired or unknown"},
}

router = APIRouter(prefix="/previews", tags=["previews"], responses=_ERROR_RESPONSES)


@router.get("/{preview_id}", response_class=FileResponse)
def get_preview(
    preview_id: str,
    service: Annotated[RenderService, Depends(get_render_service)],
) -> FileResponse:
    path = service.previews.resolve(preview_id)
    if path is None:
        raise AppError(
            404,
            "preview_expired",
            "The preview is no longer available; render it again.",
        )
    headers = {
        "Cache-Control": f"private, max-age={service.previews.ttl_seconds}",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(path, media_type="image/jpeg", headers=headers)
