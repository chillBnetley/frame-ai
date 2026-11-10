from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_owner_scope, get_style_mix_service
from app.core.identity import OwnerScope
from app.models.personal_style import PersonalStyleDetailResponse
from app.models.schemas import ErrorResponse
from app.models.style_mix import (
    StyleMixPreviewResponse,
    StyleMixRequest,
    StyleMixSaveRequest,
)
from app.services.style_mix_service import StyleMixService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "One of the source styles is not available",
        409: "A personal style with this name already exists",
        422: "Invalid request payload",
        503: "Style mix service not ready",
    }.items()
}

router = APIRouter(
    prefix="/style-mixes",
    tags=["style-mixes"],
    responses=_ERROR_RESPONSES,
)


@router.post("/preview", response_model=StyleMixPreviewResponse)
def preview_style_mix(
    payload: StyleMixRequest,
    service: Annotated[StyleMixService, Depends(get_style_mix_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> StyleMixPreviewResponse:
    return service.preview(payload, owner_id=owner.owner_id)


@router.post("", response_model=PersonalStyleDetailResponse, status_code=201)
def save_style_mix(
    payload: StyleMixSaveRequest,
    service: Annotated[StyleMixService, Depends(get_style_mix_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleDetailResponse:
    return service.save(payload, owner_id=owner.owner_id)