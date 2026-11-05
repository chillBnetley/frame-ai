from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from app.ai.base import DecisionRequest, ModelImage, VisionRequest
from app.ai.contracts import DecisionResult, VisionResult
from app.ai.errors import ProviderError
from app.ai.providers.openai_compatible import (
    OpenAICompatibleDecisionProvider,
    OpenAICompatibleVisionProvider,
)
from tests.ai_support import (
    analysis_options,
    chat_response,
    decision_payload,
    issue_candidate,
    json_response,
    measurement_summary,
    vision_payload,
)

BASE_URL = "https://example.test/v1/"
API_KEY = "sk-test-secret-value"
MODEL = "vision-test-model"


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


def vision_request() -> VisionRequest:
    return VisionRequest(
        image=ModelImage(
            data=b"image-bytes",
            mime_type="image/jpeg",
            width=1024,
            height=768,
        ),
        options=analysis_options(),
        measurements=measurement_summary(),
    )


def decision_request() -> DecisionRequest:
    return DecisionRequest(
        vision=VisionResult.model_validate(vision_payload()),
        measurements=measurement_summary(),
        candidates=(issue_candidate(),),
        options=analysis_options(),
    )


def vision_provider(client: FakeClient, *, repair_attempts: int = 0):
    return OpenAICompatibleVisionProvider(
        client,  # type: ignore[arg-type]
        base_url=BASE_URL,
        api_key=API_KEY,
        model=MODEL,
        timeout=30.0,
        max_retries=2,
        repair_attempts=repair_attempts,
    )


def decision_provider(client: FakeClient, *, repair_attempts: int = 0):
    return OpenAICompatibleDecisionProvider(
        client,  # type: ignore[arg-type]
        base_url=BASE_URL,
        api_key=API_KEY,
        model=MODEL,
        timeout=30.0,
        max_retries=2,
        repair_attempts=repair_attempts,
    )


def test_vision_provider_logs_usage_without_image_payload(caplog):
    client = FakeClient(
        [
            json_response(
                vision_payload(),
                usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            )
        ]
    )

    with caplog.at_level("INFO", logger="frame_ai.ai"):
        vision_provider(client).analyze(vision_request())

    messages = [record.getMessage() for record in caplog.records if "model_call" in record.message]
    assert len(messages) == 1
    message = messages[0]
    assert "stage=vision" in message
    assert f"model={MODEL}" in message
    assert "prompt_tokens=11" in message
    assert "completion_tokens=7" in message
    assert "total_tokens=18" in message
    assert "outcome=ok" in message
    assert "image-bytes" not in message
    assert base64.b64encode(b"image-bytes").decode("ascii") not in message


def test_vision_provider_posts_data_url_and_validates_result():
    client = FakeClient(
        [
            json_response(
                vision_payload(),
                usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            )
        ]
    )

    result = vision_provider(client).analyze(vision_request())

    assert isinstance(result, VisionResult)
    assert result.scene.primary == "portrait"
    assert result.color.dominant_colors == ("#C58B6A",)
    assert result.usage is not None
    assert result.usage.prompt_tokens == 11
    assert result.usage.total_tokens == 18

    call = client.calls[0]
    assert call["url"] == "https://example.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert call["payload"]["model"] == MODEL
    assert call["payload"]["temperature"] == 0.0
    assert call["payload"]["stream"] is False
    assert call["payload"]["response_format"] == {"type": "json_object"}

    messages = call["payload"]["messages"]
    user_parts = messages[1]["content"]
    image_part = next(part for part in user_parts if part["type"] == "image_url")
    encoded = base64.b64encode(b"image-bytes").decode("ascii")
    assert image_part["image_url"]["url"] == f"data:image/jpeg;base64,{encoded}"


def test_vision_provider_does_not_send_local_identifiers():
    client = FakeClient([json_response(vision_payload())])

    vision_provider(client).analyze(vision_request())

    serialized = json.dumps(client.calls[0]["payload"], ensure_ascii=False)
    assert "image_id" not in serialized
    assert "imageId" not in serialized
    assert "C:\\\\" not in serialized
    assert ".jpeg" not in serialized


def test_decision_provider_sends_no_image_bytes():
    client = FakeClient([json_response(decision_payload())])

    result = decision_provider(client).diagnose(decision_request())

    assert isinstance(result, DecisionResult)
    assert result.issues[0].candidate_id == "c1"
    serialized = json.dumps(client.calls[0]["payload"], ensure_ascii=False)
    assert "data:image" not in serialized
    assert "image-bytes" not in serialized
    assert "candidateId" in serialized
    assert "technicalQuality" in serialized


def test_repair_attempt_is_used_for_invalid_json():
    client = FakeClient(
        [
            chat_response("this is not json"),
            json_response(vision_payload()),
        ]
    )

    result = vision_provider(client, repair_attempts=1).analyze(vision_request())

    assert result.scene.primary == "portrait"
    assert len(client.calls) == 2
    repaired = client.calls[1]["payload"]["messages"]
    assert len(repaired) == 4
    assert repaired[2]["content"] == "this is not json"
    assert "rejected" in repaired[3]["content"]


def test_repair_attempt_is_bounded_and_reports_safe_error():
    client = FakeClient([chat_response("still not json"), chat_response("nope")])

    with pytest.raises(ProviderError) as error:
        vision_provider(client, repair_attempts=1).analyze(vision_request())

    assert error.value.code == "vision_invalid_output"
    assert len(client.calls) == 2
    assert API_KEY not in str(error.value)
    assert "still not json" not in str(error.value)


def test_schema_validation_error_reports_fields_without_content():
    client = FakeClient([json_response({"scene": {"primary": "portrait"}})])

    with pytest.raises(ProviderError) as error:
        vision_provider(client).analyze(vision_request())

    assert error.value.code == "vision_invalid_output"
    assert error.value.retryable is False
    fields = error.value.details["fields"]
    assert any(field.startswith("scene.") for field in fields)
    assert "portrait" not in json.dumps(error.value.details)
    assert API_KEY not in str(error.value)


def test_decision_schema_error_uses_decision_prefix():
    client = FakeClient([json_response({"technicalQuality": {}})])

    with pytest.raises(ProviderError) as error:
        decision_provider(client).diagnose(decision_request())

    assert error.value.code == "decision_invalid_output"


def test_transport_errors_are_prefixed_and_keep_key_secret():
    client = FakeClient(
        [
            ProviderError(
                "provider_auth_error",
                "The model provider rejected the configured credentials.",
            )
        ]
    )

    with pytest.raises(ProviderError) as error:
        vision_provider(client).analyze(vision_request())

    assert error.value.code == "vision_provider_auth_error"
    assert error.value.retryable is False
    assert API_KEY not in str(error.value)
    assert API_KEY not in repr(error.value.details)


def test_provider_does_not_expose_key_in_repr():
    provider = vision_provider(FakeClient([]))

    assert API_KEY not in repr(provider)
    assert provider.is_mock is False
    assert provider.name == "openai-compatible"
    assert provider.model == MODEL
    assert provider.prompt_version == "stage3-vision/2"


def test_fenced_json_and_list_content_are_supported():
    fenced = "```json\n" + json.dumps(vision_payload()) + "\n```"
    client = FakeClient(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": [{"type": "text", "text": fenced}],
                        }
                    }
                ]
            }
        ]
    )

    result = vision_provider(client).analyze(vision_request())

    assert result.scene.primary == "portrait"


def test_invalid_usage_is_ignored():
    client = FakeClient(
        [
            json_response(
                vision_payload(),
                usage={"prompt_tokens": -5, "completion_tokens": "many"},
            )
        ]
    )

    result = vision_provider(client).analyze(vision_request())

    assert result.usage is None


def test_missing_content_is_rejected():
    client = FakeClient([{"choices": []}])

    with pytest.raises(ProviderError) as error:
        vision_provider(client).analyze(vision_request())

    assert error.value.code == "vision_invalid_output"
