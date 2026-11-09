from __future__ import annotations

from typing import Annotated, Any
from unicodedata import normalize
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    get_deletion_service,
    get_image_service,
    get_semantic_mask_service,
)
from app.core.errors import AppError
from app.models.schemas import (
    ErrorResponse,
    ImageListItem,
    ImageListResponse,
    SemanticMaskRequest,
    SemanticMaskResponse,
    UploadImageResponse,
)
from app.repositories.image_registry import ImageAssetRecord
from app.services.deletion_service import DeletionService
from app.services.image_service import ImageService
from app.services.semantic_mask_service import SemanticMaskService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        400: "Invalid or empty upload",
        404: "Image not found",
        409: "Image is being analyzed or exported",
        413: "Upload or pixel limit exceeded",
        415: "Unsupported or invalid image",
        500: "Storage failure",
        503: "Semantic mask model is unavailable",
        504: "Semantic mask inference timed out",
    }.items()
}

router = APIRouter(prefix="/images", tags=["images"], responses=_ERROR_RESPONSES)


def _content_disposition(disposition: str, filename: str) -> str:
    ascii_name = normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii").strip()
    ascii_name = "".join(
        char for char in ascii_name if char.isprintable() and char not in {'"', "\\"}
    )[:150]
    ascii_name = ascii_name or "image"
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("", response_model=ImageListResponse)
def list_images(
    service: Annotated[ImageService, Depends(get_image_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ImageListResponse:
    records, next_offset = service.list_images(limit=limit, offset=offset)
    return ImageListResponse(
        images=[
            ImageListItem(
                id=UUID(record.id),
                original_name=record.original_name,
                width=record.width,
                height=record.height,
                mime_type=record.mime_type,
                bytes=record.bytes,
                created_at=record.created_at,
            )
            for record in records
        ],
        next_offset=next_offset,
    )


@router.post("", response_model=UploadImageResponse, status_code=201)
async def upload_image(
    file: Annotated[list[UploadFile], File(...)],
    service: Annotated[ImageService, Depends(get_image_service)],
) -> UploadImageResponse:
    if len(file) != 1:
        raise AppError(
            400,
            "invalid_upload",
            "Exactly one image file must be uploaded.",
            {"fileCount": len(file)},
        )
    record = await service.create_from_upload(file[0])
    return UploadImageResponse(
        image_id=UUID(record.id),
        original_name=record.original_name,
        width=record.width,
        height=record.height,
        exif_orientation=record.exif_orientation,
        mime_type=record.mime_type,
        bytes=record.bytes,
    )


@router.post(
    "/{image_id}/semantic-masks",
    response_model=SemanticMaskResponse,
    status_code=201,
)
async def create_semantic_mask(
    image_id: UUID,
    request: SemanticMaskRequest,
    service: Annotated[SemanticMaskService, Depends(get_semantic_mask_service)],
) -> SemanticMaskResponse:
    result = await run_in_threadpool(
        service.create,
        str(image_id),
        request.semantic_class,
    )
    return SemanticMaskResponse(
        matte_id=result.matte_id,
        sha256=result.sha256,
        model_version=result.model_version,
        semantic_class=result.semantic_class,
        width=result.width,
        height=result.height,
    )


@router.get("/{image_id}/original")
def get_original_image(
    image_id: str,
    service: Annotated[ImageService, Depends(get_image_service)],
    download: Annotated[bool, Query()] = False,
) -> FileResponse:
    record: ImageAssetRecord
    record, path = service.get_original(image_id)
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": _content_disposition(disposition, record.original_name),
        "Cache-Control": "private, max-age=31536000, immutable",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(path, media_type=record.mime_type, headers=headers)


@router.delete("/{image_id}", status_code=204)
def delete_image(
    image_id: str,
    service: Annotated[DeletionService, Depends(get_deletion_service)],
) -> Response:
    service.delete_image(image_id)
    return Response(status_code=204)
