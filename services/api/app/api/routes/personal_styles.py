from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import (
    get_custom_style_service,
    get_owner_scope,
    get_personal_style_analysis_service,
    get_personal_style_service,
    get_style_evolution_service,
    get_style_fusion_service,
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
from app.models.style_authoring import (
    CustomStyleParseRequest,
    CustomStyleParseResponse,
    CustomStyleRefineApplyRequest,
    CustomStyleRefineRequest,
    CustomStyleRefineResponse,
    CustomStyleSaveRequest,
)
from app.models.style_evolution import (
    StyleEvolutionApplyRequest,
    StyleEvolutionListResponse,
    StyleEvolutionPreviewRequest,
    StyleEvolutionPreviewResponse,
    StyleFeedbackCreateRequest,
    StyleFeedbackListResponse,
    StyleFeedbackRecord,
    StyleFeedbackScope,
)
from app.models.style_fusion import (
    PersonalStyleFusionRequest,
    PersonalStyleFusionResponse,
)
from app.models.style_profile import StyleProfileVersion
from app.models.visual_dna import (
    PersonalStyleAnalysisResponse,
    PersonalStyleAnalyzeRequest,
    PhotoVisualFeatures,
)
from app.services.custom_style_service import CustomStyleService
from app.services.personal_style_analysis_service import PersonalStyleAnalysisService
from app.services.personal_style_service import PersonalStyleService
from app.services.style_evolution_service import StyleEvolutionService
from app.services.style_fusion_service import StyleFusionService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Personal style, version, or reference photo not found",
        409: "Name/version conflict, missing confirmation, or publish prerequisite",
        422: "Invalid request payload",
        429: "Style authoring daily model budget exhausted",
        502: "Style authoring provider returned invalid output",
        503: "Personal style service not ready",
        504: "Style authoring provider timed out",
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
_FeedbackPath = Annotated[UUID, Path(description="Feedback identifier.")]
_EvolutionPath = Annotated[UUID, Path(description="Evolution proposal identifier.")]


@router.post("/custom/parse", response_model=CustomStyleParseResponse)
def parse_custom_style(
    payload: CustomStyleParseRequest,
    service: Annotated[CustomStyleService, Depends(get_custom_style_service)],
) -> CustomStyleParseResponse:
    return service.parse(payload)


@router.post("/custom", response_model=PersonalStyleDetailResponse, status_code=201)
def save_custom_style(
    payload: CustomStyleSaveRequest,
    service: Annotated[CustomStyleService, Depends(get_custom_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleDetailResponse:
    return service.save(payload, owner_id=owner.owner_id)


@router.post("/{style_id}/refine", response_model=CustomStyleRefineResponse)
def refine_personal_style(
    style_id: _StylePath,
    payload: CustomStyleRefineRequest,
    service: Annotated[CustomStyleService, Depends(get_custom_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> CustomStyleRefineResponse:
    return service.refine(style_id, payload, owner_id=owner.owner_id)


@router.post("/{style_id}/refine/apply", response_model=PersonalStyleDetailResponse)
def apply_personal_style_refinement(
    style_id: _StylePath,
    payload: CustomStyleRefineApplyRequest,
    service: Annotated[CustomStyleService, Depends(get_custom_style_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleDetailResponse:
    return service.apply_refine(style_id, payload, owner_id=owner.owner_id)


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


@router.post("/{style_id}/fuse", response_model=PersonalStyleFusionResponse)
def fuse_personal_style(
    style_id: _StylePath,
    payload: PersonalStyleFusionRequest,
    service: Annotated[StyleFusionService, Depends(get_style_fusion_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleFusionResponse:
    return service.fuse(style_id, payload, owner_id=owner.owner_id)


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


@router.post("/{style_id}/feedback", response_model=StyleFeedbackRecord, status_code=201)
def add_personal_style_feedback(
    style_id: _StylePath,
    payload: StyleFeedbackCreateRequest,
    service: Annotated[StyleEvolutionService, Depends(get_style_evolution_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> StyleFeedbackRecord:
    return service.add_feedback(style_id, payload, owner_id=owner.owner_id)


@router.get("/{style_id}/feedback", response_model=StyleFeedbackListResponse)
def list_personal_style_feedback(
    style_id: _StylePath,
    service: Annotated[StyleEvolutionService, Depends(get_style_evolution_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
    scope: Annotated[
        StyleFeedbackScope | None,
        Query(description="Filter by single_edit or profile scope."),
    ] = None,
) -> StyleFeedbackListResponse:
    return service.list_feedback(style_id, owner_id=owner.owner_id, scope=scope)


@router.delete("/{style_id}/feedback/{feedback_id}", status_code=204)
def delete_personal_style_feedback(
    style_id: _StylePath,
    feedback_id: _FeedbackPath,
    service: Annotated[StyleEvolutionService, Depends(get_style_evolution_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> Response:
    service.delete_feedback(style_id, str(feedback_id), owner_id=owner.owner_id)
    return Response(status_code=204)


@router.post("/{style_id}/evolve/preview", response_model=StyleEvolutionPreviewResponse)
def preview_personal_style_evolution(
    style_id: _StylePath,
    payload: StyleEvolutionPreviewRequest,
    service: Annotated[StyleEvolutionService, Depends(get_style_evolution_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> StyleEvolutionPreviewResponse:
    return service.preview(style_id, payload, owner_id=owner.owner_id)


@router.post(
    "/{style_id}/evolve/{evolution_id}/apply",
    response_model=PersonalStyleDetailResponse,
)
def apply_personal_style_evolution(
    style_id: _StylePath,
    evolution_id: _EvolutionPath,
    payload: StyleEvolutionApplyRequest,
    service: Annotated[StyleEvolutionService, Depends(get_style_evolution_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> PersonalStyleDetailResponse:
    return service.apply(style_id, str(evolution_id), payload, owner_id=owner.owner_id)


@router.post("/{style_id}/evolve/{evolution_id}/discard", status_code=204)
def discard_personal_style_evolution(
    style_id: _StylePath,
    evolution_id: _EvolutionPath,
    service: Annotated[StyleEvolutionService, Depends(get_style_evolution_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> Response:
    service.discard(style_id, str(evolution_id), owner_id=owner.owner_id)
    return Response(status_code=204)


@router.get("/{style_id}/evolutions", response_model=StyleEvolutionListResponse)
def list_personal_style_evolutions(
    style_id: _StylePath,
    service: Annotated[StyleEvolutionService, Depends(get_style_evolution_service)],
    owner: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> StyleEvolutionListResponse:
    return service.list_evolutions(style_id, owner_id=owner.owner_id)
