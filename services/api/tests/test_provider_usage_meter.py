from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.ai.base import ModelImage, VisionRequest
from app.ai.contracts import UsageInfo
from app.ai.errors import ProviderBudgetExceeded, ProviderError, ProviderUsageUnavailable
from app.ai.factory import build_decision_provider, build_planner_provider, build_vision_provider
from app.ai.providers.openai_compatible import (
    OpenAICompatibleDecisionProvider,
    OpenAICompatiblePlannerProvider,
    OpenAICompatibleVisionProvider,
)
from app.core.config import Settings
from app.models.provider_settings import SecretKind
from app.repositories.db import initialize_database
from app.repositories.provider_usage_repo import ProviderUsageRepository, usage_date
from app.services.usage_meter import UsageMeter, token_counts
from tests.ai_support import analysis_options, chat_response, measurement_summary, vision_payload

COUNTED = datetime(2026, 11, 8, 12, 30, tzinfo=UTC)
LATER = datetime(2026, 11, 9, 0, 30, tzinfo=UTC)


class FakeClient:
    def __init__(self, responses: list[dict[str, Any] | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        *,
        timeout: float,
        max_retries: int,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "payload": payload})
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "frame.db"
    initialize_database(path)
    return path


def make_meter(
    database: Path,
    *,
    kind: SecretKind = "vision",
    clock: Callable[[], datetime] | None = None,
) -> UsageMeter:
    return UsageMeter(
        kind,
        ProviderUsageRepository(database),
        clock=clock or (lambda: COUNTED),
    )


def test_token_counts_prefers_reported_total():
    usage = UsageInfo(prompt_tokens=5, completion_tokens=2, total_tokens=9)

    assert token_counts(usage, request_bytes=100, response_bytes=100) == (9, 0)


def test_token_counts_sums_prompt_and_completion_when_total_is_absent():
    usage = UsageInfo(prompt_tokens=5, completion_tokens=2)

    assert token_counts(usage, request_bytes=100, response_bytes=100) == (7, 0)


def test_token_counts_estimates_from_bytes_when_usage_is_unusable():
    assert token_counts(None, request_bytes=10, response_bytes=6) == (0, 4)
    assert token_counts(UsageInfo(prompt_tokens=5), request_bytes=10, response_bytes=6) == (0, 4)


def test_meter_records_reported_tokens_on_the_reserved_date(database: Path):
    meter = make_meter(database)
    meter.reserve()

    meter.record(UsageInfo(total_tokens=12), request_bytes=10, response_bytes=10)

    [row] = ProviderUsageRepository(database).snapshot(usage_date(COUNTED))
    assert row.requests == 1
    assert row.tokens_reported == 12
    assert row.tokens_estimated == 0


def test_meter_records_estimated_tokens_when_usage_is_missing(database: Path):
    meter = make_meter(database, kind="decision")
    meter.reserve()

    meter.record(None, request_bytes=10, response_bytes=6)

    [row] = ProviderUsageRepository(database).snapshot(usage_date(COUNTED))
    assert row.tokens_estimated == 4
    assert row.tokens_reported == 0


def test_meter_ignores_a_record_without_a_counted_attempt(database: Path):
    meter = make_meter(database)

    meter.record(UsageInfo(total_tokens=12), request_bytes=10, response_bytes=10)

    assert ProviderUsageRepository(database).snapshot(usage_date(COUNTED)) == []


def test_meter_uses_the_reserved_date_across_utc_midnight(database: Path):
    now = [COUNTED]
    meter = make_meter(database, clock=lambda: now[0])
    meter.reserve()
    now[0] = LATER

    meter.record(UsageInfo(total_tokens=12), request_bytes=0, response_bytes=0)

    [first_day] = ProviderUsageRepository(database).snapshot(usage_date(COUNTED))
    assert first_day.tokens_reported == 12
    assert ProviderUsageRepository(database).snapshot(usage_date(LATER)) == []


def test_token_write_failure_only_logs_a_warning(
    database: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    meter = make_meter(database)
    meter.reserve()

    def broken(*args: object, **kwargs: object) -> None:
        raise ProviderUsageUnavailable("provider_usage_unavailable", "ledger down")

    monkeypatch.setattr(meter._repository, "add_tokens", broken)

    with caplog.at_level(logging.WARNING, logger="frame_ai.usage"):
        meter.record(UsageInfo(total_tokens=3), request_bytes=0, response_bytes=0)

    assert "provider_usage_token_write_failed" in caplog.text
    assert "ledger down" not in caplog.text


def vision_provider(client: FakeClient, meter: UsageMeter) -> OpenAICompatibleVisionProvider:
    return OpenAICompatibleVisionProvider(
        client,  # type: ignore[arg-type]
        base_url="https://example.test/v1",
        api_key="sk-test-secret",
        model="vision-test",
        timeout=10.0,
        max_retries=0,
        repair_attempts=0,
        usage_meter=meter,
    )


def vision_request() -> VisionRequest:
    return VisionRequest(
        image=ModelImage(data=b"image-bytes", mime_type="image/jpeg", width=64, height=48),
        options=analysis_options(),
        measurements=measurement_summary(),
    )


def test_check_connection_records_reported_tokens(database: Path):
    meter = make_meter(database)
    client = FakeClient(
        [
            chat_response(
                '{"ok": true}',
                usage={"promptTokens": 5, "completionTokens": 2, "totalTokens": 7},
            )
        ]
    )
    provider = vision_provider(client, meter)

    meter.reserve()
    provider.check_connection()

    [row] = ProviderUsageRepository(database).snapshot(usage_date(COUNTED))
    assert row.requests == 1
    assert row.tokens_reported == 7
    assert row.tokens_estimated == 0


def test_provider_estimates_tokens_when_the_response_has_no_usage(database: Path):
    meter = make_meter(database)
    provider = vision_provider(
        FakeClient([chat_response(json.dumps(vision_payload()))]),
        meter,
    )

    meter.reserve()
    provider.analyze(vision_request())

    [row] = ProviderUsageRepository(database).snapshot(usage_date(COUNTED))
    assert row.requests == 1
    assert row.tokens_estimated > 0
    assert row.tokens_reported == 0


@pytest.mark.parametrize(
    "error",
    [
        ProviderBudgetExceeded(
            "provider_budget_exceeded",
            "budget",
            retryable=False,
            details={"limit": 1, "used": 1, "remaining": 0, "resetAt": "2026-11-09T00:00:00Z"},
        ),
        ProviderUsageUnavailable("provider_usage_unavailable", "ledger", retryable=False),
    ],
)
def test_provider_re_raises_budget_errors_without_prefix_or_subclass_loss(
    database: Path,
    error: ProviderError,
):
    provider = vision_provider(FakeClient([error]), make_meter(database))

    with pytest.raises(type(error)) as raised:
        provider.check_connection()

    assert raised.value is error
    assert raised.value.code == error.code
    assert not raised.value.code.startswith("check_")


def test_factory_providers_carry_their_own_kind():
    def client() -> FakeClient:
        return FakeClient([chat_response("{}")])

    vision = build_vision_provider(
        Settings(
            data_dir=Path("unused-data"),
            vision_provider="openai",
            vision_api_key="sk-test",
            vision_model="vision-test",
            vision_api_base_url="https://example.test/v1",
        ),
        client=client(),  # type: ignore[arg-type]
    )
    decision = build_decision_provider(
        Settings(
            data_dir=Path("unused-data"),
            decision_provider="openai",
            decision_api_key="sk-test",
            decision_model="decision-test",
            decision_api_base_url="https://example.test/v1",
        ),
        client=client(),  # type: ignore[arg-type]
    )
    planner = build_planner_provider(
        Settings(
            data_dir=Path("unused-data"),
            decision_provider="openai",
            decision_api_key="sk-test",
            decision_model="decision-test",
            decision_api_base_url="https://example.test/v1",
        ),
        client=client(),  # type: ignore[arg-type]
    )

    assert isinstance(vision, OpenAICompatibleVisionProvider)
    assert isinstance(decision, OpenAICompatibleDecisionProvider)
    assert isinstance(planner, OpenAICompatiblePlannerProvider)
    assert (vision.kind, decision.kind, planner.kind) == ("vision", "decision", "planner")


def test_prompt_content_never_reaches_the_usage_ledger(
    database: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    canary = "CANARY-PROMPT-CONTENT-DO-NOT-STORE"
    meter = make_meter(database)
    provider = vision_provider(
        FakeClient([chat_response(json.dumps({"echo": canary}))]),
        meter,
    )

    meter.reserve()
    with caplog.at_level(logging.DEBUG, logger="frame_ai.usage"):
        provider._post([{"role": "user", "content": canary}], "check")

    [row] = ProviderUsageRepository(database).snapshot(usage_date(COUNTED))
    assert row.tokens_estimated > 0
    assert canary not in str(row)
    assert canary not in caplog.text
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert canary.encode() not in path.read_bytes()
