from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from app.ai.contracts import SceneLabel
from app.api.deps import get_style_library_service
from app.models.photographer import PhotographerStyleId
from app.models.schemas import ErrorResponse
from app.models.style_library import (
    StyleDetailResponse,
    StyleEnabledRequest,
    StyleEnabledResponse,
    StyleFavoriteResponse,
    StyleLibraryListResponse,
    StyleRecentResponse,
    StyleRecommendedResponse,
    StyleVersionListResponse,
)
from app.models.style_profile import StyleKind
from app.services.style_library_service import StyleLibraryService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Style profile or image not found",
        409: "Completed analysis required or report does not match the image",
        422: "Invalid request payload",
        503: "Style library or analysis service not ready",
    }.items()
}

router = APIRouter(prefix="/styles", tags=["styles"], responses=_ERROR_RESPONSES)

_StylePath = Annotated[PhotographerStyleId, Path(description="Style identifier.")]


@router.get("", response_model=StyleLibraryListResponse)
def list_styles(
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
    kind: Annotated[StyleKind | None, Query(description="Filter by master or genre.")] = None,
    scene: Annotated[SceneLabel | None, Query(description="Filter by suitable scene.")] = None,
    search: Annotated[
        str | None,
        Query(description="Match the style name or identifier.", max_length=80),
    ] = None,
    include_disabled: Annotated[bool, Query(description="Include disabled styles.")] = False,
) -> StyleLibraryListResponse:
    return service.list_styles(
        kind=kind,
        scene=scene,
        search=search,
        include_disabled=include_disabled,
    )


@router.get("/favorites", response_model=StyleLibraryListResponse)
def list_favorites(
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
) -> StyleLibraryListResponse:
    return service.list_favorites()


@router.get("/recent", response_model=StyleRecentResponse)
def list_recent(
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> StyleRecentResponse:
    return service.recent(limit=limit)


@router.get("/recommended", response_model=StyleRecommendedResponse)
def list_recommended(
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
    image_id: Annotated[
        str | None,
        Query(description="Rank by the completed analysis of this image."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> StyleRecommendedResponse:
    return service.recommended(image_id=image_id, limit=limit)


@router.get("/{style_id}", response_model=StyleDetailResponse)
def read_style(
    style_id: _StylePath,
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
    version: Annotated[
        str | None,
        Query(description="Read a specific archived version instead of the current one."),
    ] = None,
    include_disabled: Annotated[bool, Query(description="Allow reading a disabled style.")] = False,
) -> StyleDetailResponse:
    return service.detail(style_id, version=version, include_disabled=include_disabled)


@router.get("/{style_id}/versions", response_model=StyleVersionListResponse)
def list_versions(
    style_id: _StylePath,
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
) -> StyleVersionListResponse:
    return service.versions(style_id)


@router.post("/{style_id}/favorite", response_model=StyleFavoriteResponse)
def add_favorite(
    style_id: _StylePath,
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
) -> StyleFavoriteResponse:
    return service.favorite(style_id)


@router.delete("/{style_id}/favorite", response_model=StyleFavoriteResponse)
def remove_favorite(
    style_id: _StylePath,
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
) -> StyleFavoriteResponse:
    return service.unfavorite(style_id)


@router.post("/{style_id}/enabled", response_model=StyleEnabledResponse)
def set_enabled(
    style_id: _StylePath,
    payload: StyleEnabledRequest,
    service: Annotated[StyleLibraryService, Depends(get_style_library_service)],
) -> StyleEnabledResponse:
    return service.set_enabled(style_id, payload.enabled)
