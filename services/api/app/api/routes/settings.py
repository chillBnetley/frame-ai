from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.ai.errors import ProviderUsageUnavailable
from app.api.deps import get_app_settings, get_provider_settings_service
from app.core.config import Settings
from app.core.errors import AppError
from app.models.provider_settings import (
    ProviderSettingsUpdate,
    ProviderSettingsView,
    ProviderTestResponse,
    ProviderUsageEntry,
    ProviderUsageView,
    SecretKind,
)
from app.models.schemas import ErrorResponse
from app.repositories.provider_usage_repo import (
    ProviderUsageRepository,
    usage_date,
    usage_reset_at,
)
from app.services.provider_settings_service import ProviderSettingsService

_USAGE_KINDS: tuple[SecretKind, ...] = ("vision", "decision", "planner")

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        422: "Provider settings are incomplete or invalid",
        500: "Provider settings could not be saved",
        503: "Provider settings or usage service is not ready",
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


@router.get("/usage", response_model=ProviderUsageView)
def read_provider_usage(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ProviderUsageView:
    now = datetime.now(UTC)
    date = usage_date(now)
    repository = ProviderUsageRepository(
        settings.database_path,
        request_limit=settings.provider_daily_request_limit,
        token_limit=settings.provider_daily_token_limit,
    )
    try:
        rows = {row.provider: row for row in repository.snapshot(date)}
    except ProviderUsageUnavailable as exc:
        raise AppError(503, "provider_usage_unavailable", exc.message) from None
    entries: list[ProviderUsageEntry] = []
    for kind in _USAGE_KINDS:
        row = rows.get(kind)
        entries.append(
            ProviderUsageEntry(
                provider=kind,
                date=date,
                requests=0 if row is None else row.requests,
                tokens_estimated=0 if row is None else row.tokens_estimated,
                tokens_reported=0 if row is None else row.tokens_reported,
                updated_at=None if row is None else row.updated_at,
            )
        )
    return ProviderUsageView(
        date=date,
        request_limit=settings.provider_daily_request_limit,
        token_limit=settings.provider_daily_token_limit,
        reset_at=usage_reset_at(now),
        entries=entries,
    )


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
