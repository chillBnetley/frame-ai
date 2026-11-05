from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_provider_settings_service
from app.models.provider_settings import (
    ProviderSettingsUpdate,
    ProviderSettingsView,
    ProviderTestResponse,
)
from app.models.schemas import ErrorResponse
from app.services.provider_settings_service import ProviderSettingsService

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        422: "Provider settings are incomplete or invalid",
        500: "Provider settings could not be saved",
        503: "Provider settings service is not ready",
    }.items()
}

router = APIRouter(
    prefix="/settings/providers",
    tags=["settings"],
    responses=_ERROR_RESPONSES,
)


@router.get("", response_model=ProviderSettingsView)
def read_provider_settings(
    service: Annotated[ProviderSettingsService, Depends(get_provider_settings_service)],
) -> ProviderSettingsView:
    return service.view()


@router.post("", response_model=ProviderSettingsView)
def save_provider_settings(
    update: ProviderSettingsUpdate,
    service: Annotated[ProviderSettingsService, Depends(get_provider_settings_service)],
) -> ProviderSettingsView:
    return service.apply(update)


@router.post("/test", response_model=ProviderTestResponse)
def test_provider_settings(
    update: ProviderSettingsUpdate,
    service: Annotated[ProviderSettingsService, Depends(get_provider_settings_service)],
) -> ProviderTestResponse:
    return service.test(update)


@router.post("/reset", response_model=ProviderSettingsView)
def reset_provider_settings(
    service: Annotated[ProviderSettingsService, Depends(get_provider_settings_service)],
) -> ProviderSettingsView:
    return service.reset()
