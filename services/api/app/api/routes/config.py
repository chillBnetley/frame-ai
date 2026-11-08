from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings, get_semantic_registry
from app.core.config import Settings
from app.imaging.decoder import SUPPORTED_MIME_TYPES
from app.imaging.semantic_models import SemanticModelRegistry
from app.models.schemas import (
    RuntimeConfigResponse,
    RuntimeFeatures,
    SemanticMaskFeature,
    SemanticMaskModels,
)

router = APIRouter(tags=["system"])


@router.get("/config", response_model=RuntimeConfigResponse)
def runtime_config(
    settings: Annotated[Settings, Depends(get_app_settings)],
    registry: Annotated[SemanticModelRegistry, Depends(get_semantic_registry)],
) -> RuntimeConfigResponse:
    if settings.feature_semantic_masks:
        person = registry.status("person")
        sky = registry.status("sky")
        semantic = SemanticMaskFeature(
            enabled=True,
            person=person.available,
            sky=sky.available,
        )
        models = SemanticMaskModels(person=person.version, sky=sky.version)
    else:
        semantic = SemanticMaskFeature(enabled=False, person=False, sky=False)
        models = SemanticMaskModels(person=None, sky=None)
    return RuntimeConfigResponse(
        max_upload_bytes=settings.max_upload_bytes,
        max_json_body_bytes=settings.max_json_body_bytes,
        max_image_pixels=settings.max_image_pixels,
        allowed_mime_types=list(SUPPORTED_MIME_TYPES),
        features=RuntimeFeatures(
            layers=settings.feature_layers,
            semantic_masks=semantic,
            semantic_mask_models=models,
        ),
    )
