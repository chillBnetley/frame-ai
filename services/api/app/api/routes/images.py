from __future__ import annotations

from typing import Annotated, Any
from unicodedata import normalize
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_analysis_service, get_image_service
from app.core.errors import AppError
from app.models.analysis import AnalyzeRequest, AnalyzeResponse
from app.models.schemas import ErrorResponse, UploadImageResponse
from app.repositories.image_registry import ImageAssetRecord
from app.services.analysis_service import AnalysisService
from app.services.image_service import ImageService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        400: "Invalid or empty upload",
        404: "Image not found",
        413: "Upload or pixel limit exceeded",
        415: "Unsupported or invalid image",
        500: "Storage failure",
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


@router.post("/{image_id}/analyze", response_model=AnalyzeResponse)
def analyze_image(
    image_id: str,
    analysis: Annotated[AnalysisService, Depends(get_analysis_service)],
    payload: Annotated[AnalyzeRequest | None, Body()] = None,
) -> AnalyzeResponse:
    result = analysis.analyze(image_id)
    return AnalyzeResponse(
        analysis_id=result.analysis_id,
        features=result.features,
        analyzer_version=result.analyzer_version,
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
