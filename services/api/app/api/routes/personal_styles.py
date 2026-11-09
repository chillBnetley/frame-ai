from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import (
    get_owner_scope,
    get_personal_style_analysis_service,
    get_personal_style_service,
)
from app.core.identity import OwnerScope
from app.models.personal_style import (
    PersonalStyleCompareResponse,
    PersonalStyleCreateRequest,
    PersonalStyleDetailResponse,
    PersonalStyleFavoriteResponse,
    PersonalStyleId,
    PersonalStyleListResponse,
    PersonalStyleReferenceAddRequest,
    PersonalStyleReferenceListResponse,
    PersonalStyleStatus,
    PersonalStyleStatusRequest,
    PersonalStyleStatusResponse,
    PersonalStyleUpdateRequest,
    PersonalStyleVersionDetailResponse,
    PersonalStyleVersionListResponse,
)
from app.models.schemas import ErrorResponse
from app.models.style_profile import StyleProfileVersion
from app.models.visual_dna import (
    PersonalStyleAnalysisResponse,
    PersonalStyleAnalyzeRequest,
    PhotoVisualFeatures,
)
from app.services.personal_style_analysis_service import PersonalStyleAnalysisService
from app.services.personal_style_service import PersonalStyleService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Personal style, version, or reference photo not found",
        409: "Name/version conflict, missing confirmation, or publish prerequisite",
        422: "Invalid request payload",
        503: "Personal style service not ready",
    }.items()
}

router = APIRouter(
    prefix="/personal-styles",
    tags=["personal-styles"],
    responses=_ERROR_RESPONSES,
)

_StylePath = Annotated[PersonalStyleId, Path(description="Personal style identifier.")]
_VersionPath = Annotated[StyleProfileVersion, Path(description="Archived version.")]
_ReferencePath = Annotated[UUID, Path(description="Reference photo identifier.")]


@router.get("", response_model=PersonalStyleListResponse)
def list_personal_styles(
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
    status: Annotated[
        PersonalStyleStatus | None,
        Query(description="Filter by draft, published, or disabled."),
    ] = None,
) -> PersonalStyleListResponse:
    return service.list(owner_id=owner.owner_id, status=status)


@router.post("", response_model=PersonalStyleDetailResponse, status_code=201)
def create_personal_style(
    payload: PersonalStyleCreateRequest,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleDetailResponse:
    return service.create(payload, owner_id=owner.owner_id)


@router.get("/{style_id}", response_model=PersonalStyleDetailResponse)
def read_personal_style(
    style_id: _StylePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
    version: Annotated[
        StyleProfileVersion | None,
        Query(description="Read an archived version instead of the current one."),
    ] = None,
) -> PersonalStyleDetailResponse:
    return service.detail(style_id, owner_id=owner.owner_id, version=version)


@router.patch("/{style_id}", response_model=PersonalStyleDetailResponse)
def update_personal_style(
    style_id: _StylePath,
    payload: PersonalStyleUpdateRequest,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleDetailResponse:
    return service.update(style_id, payload, owner_id=owner.owner_id)


@router.delete("/{style_id}", status_code=204)
def delete_personal_style(
    style_id: _StylePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
    confirm: Annotated[
        bool,
        Query(description="Must be true; deletion removes versions and reference features."),
    ] = False,
) -> Response:
    service.delete(style_id, owner_id=owner.owner_id, confirm=confirm)
    return Response(status_code=204)


@router.post("/{style_id}/status", response_model=PersonalStyleStatusResponse)
def set_personal_style_status(
    style_id: _StylePath,
    payload: PersonalStyleStatusRequest,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleStatusResponse:
    return service.set_status(style_id, payload.status, owner_id=owner.owner_id)


@router.post("/{style_id}/favorite", response_model=PersonalStyleFavoriteResponse)
def favorite_personal_style(
    style_id: _StylePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleFavoriteResponse:
    return service.favorite(style_id, owner_id=owner.owner_id, favorite=True)


@router.delete("/{style_id}/favorite", response_model=PersonalStyleFavoriteResponse)
def unfavorite_personal_style(
    style_id: _StylePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleFavoriteResponse:
    return service.favorite(style_id, owner_id=owner.owner_id, favorite=False)


@router.get("/{style_id}/references", response_model=PersonalStyleReferenceListResponse)
def list_personal_style_references(
    style_id: _StylePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleReferenceListResponse:
    return service.list_references(style_id, owner_id=owner.owner_id)


@router.post(
    "/{style_id}/references",
    response_model=PersonalStyleReferenceListResponse,
    status_code=201,
)
def add_personal_style_references(
    style_id: _StylePath,
    payload: PersonalStyleReferenceAddRequest,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleReferenceListResponse:
    return service.add_references(style_id, payload, owner_id=owner.owner_id)


@router.delete("/{style_id}/references/{reference_id}", status_code=204)
def remove_personal_style_reference(
    style_id: _StylePath,
    reference_id: _ReferencePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> Response:
    service.remove_reference(style_id, str(reference_id), owner_id=owner.owner_id)
    return Response(status_code=204)


@router.post(
    "/{style_id}/analyze",
    response_model=PersonalStyleAnalysisResponse,
    status_code=202,
)
def analyze_personal_style_references(
    style_id: _StylePath,
    payload: PersonalStyleAnalyzeRequest,
    service: Annotated[
        PersonalStyleAnalysisService,
        Depends(get_personal_style_analysis_service),
    ],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleAnalysisResponse:
    return service.analyze(style_id, payload, owner_id=owner.owner_id)


@router.get("/{style_id}/analysis", response_model=PersonalStyleAnalysisResponse)
def read_personal_style_analysis(
    style_id: _StylePath,
    service: Annotated[
        PersonalStyleAnalysisService,
        Depends(get_personal_style_analysis_service),
    ],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleAnalysisResponse:
    return service.status(style_id, owner_id=owner.owner_id)


@router.get(
    "/{style_id}/references/{reference_id}/features",
    response_model=PhotoVisualFeatures,
)
def read_personal_style_reference_features(
    style_id: _StylePath,
    reference_id: _ReferencePath,
    service: Annotated[
        PersonalStyleAnalysisService,
        Depends(get_personal_style_analysis_service),
    ],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PhotoVisualFeatures:
    return service.features(style_id, str(reference_id), owner_id=owner.owner_id)


@router.get("/{style_id}/versions", response_model=PersonalStyleVersionListResponse)
def list_personal_style_versions(
    style_id: _StylePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleVersionListResponse:
    return service.versions(style_id, owner_id=owner.owner_id)


@router.get(
    "/{style_id}/versions/{version}",
    response_model=PersonalStyleVersionDetailResponse,
)
def read_personal_style_version(
    style_id: _StylePath,
    version: _VersionPath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleVersionDetailResponse:
    return service.version_detail(style_id, version, owner_id=owner.owner_id)


@router.post(
    "/{style_id}/versions/{version}/restore",
    response_model=PersonalStyleDetailResponse,
)
def restore_personal_style_version(
    style_id: _StylePath,
    version: _VersionPath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleDetailResponse:
    return service.restore(style_id, version, owner_id=owner.owner_id)


@router.get("/{style_id}/compare", response_model=PersonalStyleCompareResponse)
def compare_personal_style_versions(
    style_id: _StylePath,
    service: Annotated[PersonalStyleService, Depends(get_personal_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
    from_version: Annotated[
        StyleProfileVersion,
        Query(alias="from", description="Older version."),
    ],
    to_version: Annotated[
        StyleProfileVersion,
        Query(alias="to", description="Newer version."),
    ],
) -> PersonalStyleCompareResponse:
    return service.compare(
        style_id,
        from_version,
        to_version,
        owner_id=owner.owner_id,
    )
