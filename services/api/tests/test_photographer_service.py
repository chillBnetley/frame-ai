from __future__ import annotations

import pytest

from app.ai.base import PatchRequest, PlannerRequest
from app.ai.errors import ProviderError
from app.ai.prompts import PLANNER_PROMPT_VERSION
from app.ai.providers.mock import MockPlannerProvider
from app.core.errors import AppError
from app.models.photographer import PatchDraft, PlannerDraft, PlannerMode
from app.photographer.service import PhotographerService
from tests.photographer_support import patch_request, planner_request


class FailingPlanner:
    name = "failing"
    model = "failing-model"
    is_mock = False
    prompt_version = PLANNER_PROMPT_VERSION

    def __init__(self, error: ProviderError) -> None:
        self.error = error

    def plan(self, request: PlannerRequest) -> PlannerDraft:
        del request
        raise self.error

    def adjust(self, request: PatchRequest) -> PatchDraft:
        del request
        raise self.error

    def check_connection(self, *, timeout: float | None = None) -> int:
        del timeout
        raise self.error


def test_service_delegates_to_the_current_planner():
    service = PhotographerService(MockPlannerProvider())

    draft = service.draft_plan(planner_request())
    patch = service.draft_adjust(patch_request("提高对比度"))

    assert isinstance(draft, PlannerDraft)
    assert isinstance(patch, PatchDraft)
    assert patch.supported is True


def test_service_returns_a_mock_connection_latency():
    assert PhotographerService(MockPlannerProvider()).check_connection() == 0


@pytest.mark.parametrize(
    ("provider_error", "status", "code"),
    [
        ("planner_provider_timeout", 504, "photographer_timeout"),
        ("planner_provider_unavailable", 503, "photographer_unavailable"),
        ("planner_provider_rate_limited", 503, "photographer_unavailable"),
        ("planner_invalid_output", 502, "photographer_invalid_output"),
        ("planner_provider_auth_error", 502, "photographer_provider_error"),
    ],
)
def test_provider_errors_map_to_stable_app_errors(provider_error, status, code):
    service = PhotographerService(
        FailingPlanner(ProviderError(provider_error, "raw provider detail", retryable=True))
    )

    with pytest.raises(AppError) as error:
        service.draft_plan(planner_request())

    assert error.value.status_code == status
    assert error.value.code == code
    assert "raw provider detail" not in error.value.message
    assert error.value.details["retryable"] is True


def test_patch_errors_are_mapped_the_same_way():
    service = PhotographerService(
        FailingPlanner(ProviderError("patch_provider_unavailable", "down", retryable=True))
    )

    with pytest.raises(AppError) as error:
        service.draft_adjust(patch_request("提高对比度"))

    assert error.value.status_code == 503
    assert error.value.code == "photographer_unavailable"


def test_service_rejects_concurrent_requests_beyond_its_limit():
    service = PhotographerService(MockPlannerProvider(), max_concurrency=1)
    assert service._slots.acquire(blocking=False) is True
    try:
        with pytest.raises(AppError) as error:
            service.draft_plan(planner_request())
        assert error.value.status_code == 503
        assert error.value.code == "photographer_busy"
    finally:
        service._slots.release()


def test_service_rejects_invalid_concurrency():
    with pytest.raises(ValueError):
        PhotographerService(MockPlannerProvider(), max_concurrency=0)


def test_service_can_swap_planner_without_restarting():
    service = PhotographerService(MockPlannerProvider())
    replacement = MockPlannerProvider()

    service.update_planner(replacement)

    assert service.planner is replacement


def test_resolve_style_only_returns_a_style_in_style_mode():
    service = PhotographerService(MockPlannerProvider())

    assert service.resolve_style(PlannerMode.AUTO, None) is None
    assert service.resolve_style(PlannerMode.STYLE, "natural") is not None

    with pytest.raises(AppError) as error:
        service.resolve_style(PlannerMode.STYLE, None)
    assert error.value.code == "style_required"


def test_resolve_style_reports_missing_catalog_entries(monkeypatch: pytest.MonkeyPatch):
    service = PhotographerService(MockPlannerProvider())
    monkeypatch.setattr("app.photographer.service.get_style", lambda _style_id: None)

    with pytest.raises(AppError) as error:
        service.resolve_style(PlannerMode.STYLE, "film")
    assert error.value.code == "style_not_found"


def test_service_logs_metadata_but_not_the_instruction(caplog):
    instruction = "把高光压低一点"
    service = PhotographerService(MockPlannerProvider())

    with caplog.at_level("INFO", logger="frame_ai.photographer"):
        service.draft_adjust(patch_request(instruction))

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "stage=patch" in logged
    assert "outcome=ok" in logged
    assert instruction not in logged
