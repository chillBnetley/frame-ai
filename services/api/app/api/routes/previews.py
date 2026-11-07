from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_render_service
from app.core.errors import AppError
from app.models.schemas import ErrorResponse
from app.services.render_service import RenderService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Preview expired or unknown"},
}

router = APIRouter(prefix="/previews", tags=["previews"], responses=_ERROR_RESPONSES)


@router.get(
    "/{preview_id}",
    response_class=Response,
    responses={
        200: {
            "description": "Rendered JPEG preview",
            "content": {"image/jpeg": {}},
        }
    },
)
def get_preview(
    preview_id: str,
    service: Annotated[RenderService, Depends(get_render_service)],
) -> Response:
    path = service.previews.resolve(preview_id)
    if path is None:
        raise AppError(
            404,
            "preview_expired",
            "The preview is no longer available; render it again.",
        )
    service.previews.touch(path)
    # Read before returning instead of letting FileResponse reopen the path:
    # a concurrent TTL/capacity cleanup can unlink the file after resolve(),
    # and a late open failure would surface as a 500 after headers. Previews
    # are bounded JPEGs, so buffering them is an acceptable trade-off and the
    # race becomes the same 404 (and client re-render) as any expired preview.
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise AppError(
            404,
            "preview_expired",
            "The preview is no longer available; render it again.",
        ) from None
    headers = {
        "Cache-Control": f"private, max-age={service.previews.ttl_seconds}",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=data, media_type="image/jpeg", headers=headers)
