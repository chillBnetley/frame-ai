from __future__ import annotations

from typing import Any

import pytest

from app.ai.errors import ProviderError
from app.ai.providers.openai_compatible import OpenAICompatiblePlannerProvider
from tests.ai_support import chat_response, json_response
from tests.photographer_support import (
    issue,
    patch_draft_payload,
    patch_request,
    planner_draft_payload,
    planner_request,
    report,
)

BASE_URL = "https://example.test/v1/"
API_KEY = "sk-test-secret-value"
MODEL = "planner-test-model"


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
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout": timeout,
                "max_retries": max_retries,
            }
        )
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def provider(client: FakeClient, *, repair_attempts: int = 0) -> OpenAICompatiblePlannerProvider:
    return OpenAICompatiblePlannerProvider(
        client,  # type: ignore[arg-type]
        base_url=BASE_URL,
        api_key=API_KEY,
        model=MODEL,
        timeout=30.0,
        max_retries=2,
        repair_attempts=repair_attempts,
    )


def test_planner_posts_structured_context_without_image_bytes():
    client = FakeClient([json_response(planner_draft_payload())])

    result = provider(client).plan(planner_request(analysis=report(issues=(issue(),))))

    assert result.direction.id == "natural_portrait"
    assert result.adjustments.highlights == -20.0
    call = client.calls[0]
    assert call["url"] == "https://example.test/v1/chat/completions"
    assert call["payload"]["temperature"] == 0.0
    assert call["payload"]["response_format"] == {"type": "json_object"}
    assert call["payload"]["messages"][0]["role"] == "system"
    user_content = call["payload"]["messages"][1]["content"]
    assert isinstance(user_content, str)
    assert "issue_001" in user_content
    assert "data:image" not in user_content
    assert "available local mask ids" in user_content.lower()
    assert API_KEY not in str(call["payload"])


def test_planner_logs_usage_without_prompt_content(caplog):
    client = FakeClient(
        [
            json_response(
                planner_draft_payload(),
                usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
            )
        ]
    )

    with caplog.at_level("INFO", logger="frame_ai.ai"):
        result = provider(client).plan(planner_request())

    assert result.usage is not None
    assert result.usage.total_tokens == 30
    messages = [record.getMessage() for record in caplog.records if "model_call" in record.message]
    assert len(messages) == 1
    assert "stage=planner" in messages[0]
    assert "total_tokens=30" in messages[0]
    assert "issue_001" not in messages[0]


def test_planner_repairs_invalid_json_once():
    client = FakeClient(
        [
            chat_response("not json"),
            json_response(planner_draft_payload()),
        ]
    )

    result = provider(client, repair_attempts=1).plan(planner_request())

    assert result.confidence == 0.8
    assert len(client.calls) == 2
    repair_messages = client.calls[1]["payload"]["messages"]
    assert "rejected" in repair_messages[-1]["content"]
    assert "assistant" in {message["role"] for message in repair_messages}


def test_planner_rejects_schema_mismatch_with_safe_error():
    payload = planner_draft_payload()
    payload.pop("direction")
    client = FakeClient([json_response(payload)])

    with pytest.raises(ProviderError) as error:
        provider(client).plan(planner_request())

    assert error.value.code == "planner_invalid_output"
    assert error.value.retryable is False
    assert API_KEY not in error.value.message
    assert "direction" in str(error.value.details)


def test_planner_timeout_is_prefixed_and_retryable():
    client = FakeClient([ProviderError("provider_timeout", "timed out", retryable=True)])

    with pytest.raises(ProviderError) as error:
        provider(client).plan(planner_request())

    assert error.value.code == "planner_provider_timeout"
    assert error.value.retryable is True


def test_patch_returns_only_the_requested_change_and_does_not_log_the_instruction(caplog):
    instruction = "把饱和度降低一点"
    client = FakeClient([json_response(patch_draft_payload())])

    with caplog.at_level("INFO", logger="frame_ai.ai"):
        result = provider(client).adjust(patch_request(instruction))

    assert result.supported is True
    assert result.adjustments is not None
    assert result.adjustments.model_dump(exclude_none=True) == {"saturation": -8.0}
    user_content = client.calls[0]["payload"]["messages"][1]["content"]
    assert instruction in user_content
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert instruction not in logged


def test_patch_schema_mismatch_uses_the_patch_prefix():
    payload = patch_draft_payload()
    payload["adjustments"] = {"saturation": "very low"}
    client = FakeClient([json_response(payload)])

    with pytest.raises(ProviderError) as error:
        provider(client).adjust(patch_request("把饱和度降低一点"))

    assert error.value.code == "patch_invalid_output"
