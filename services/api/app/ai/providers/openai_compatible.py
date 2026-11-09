from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.base import DecisionRequest, PatchRequest, PlannerRequest, VisionRequest
from app.ai.contracts import DecisionResult, UsageInfo, VisionResult
from app.ai.errors import ProviderBudgetExceeded, ProviderError, ProviderUsageUnavailable
from app.ai.prompts import (
    DECISION_PROMPT_VERSION,
    PLANNER_PROMPT_VERSION,
    VISION_PROMPT_VERSION,
    build_decision_messages,
    build_patch_messages,
    build_planner_messages,
    build_repair_messages,
    build_vision_messages,
)
from app.ai.transport import JsonHttpClient
from app.models.photographer import (
    PatchDraft,
    PlannerDraft,
    canonical_evidence_refs,
)
from app.models.provider_settings import SecretKind
from app.services.usage_meter import UsageMeter

_FENCED_JSON = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_ModelT = TypeVar("_ModelT", bound=BaseModel)
logger = logging.getLogger("frame_ai.ai")


class _OpenAICompatibleBase:
    def __init__(
        self,
        client: JsonHttpClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        max_retries: int,
        repair_attempts: int,
        prompt_version: str,
        kind: SecretKind,
        usage_meter: UsageMeter | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._repair_attempts = repair_attempts
        self.prompt_version = prompt_version
        self.model = model
        self.name = "openai-compatible"
        self.is_mock = False
        self.kind = kind
        self._usage_meter = usage_meter

    def _post(
        self,
        messages: list[dict[str, Any]],
        prefix: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            response = self._client.post_json(
                f"{self._base_url}/chat/completions",
                payload,
                headers,
                timeout=timeout if timeout is not None else self._timeout,
                max_retries=self._max_retries,
            )
        except (ProviderBudgetExceeded, ProviderUsageUnavailable):
            # A budget stop or a broken usage ledger is a provider-wide failure:
            # keep the code unprefixed and the subclass intact.
            raise
        except ProviderError as exc:
            raise exc.prefixed(prefix) from exc
        if self._usage_meter is not None:
            self._usage_meter.record(
                _extract_usage(response),
                request_bytes=_json_size(payload),
                response_bytes=_json_size(response),
            )
        return response

    def check_connection(self, *, timeout: float | None = None) -> int:
        messages = [
            {
                "role": "system",
                "content": "You are a connectivity check. Always reply with a JSON object.",
            },
            {"role": "user", "content": 'Reply with {"ok": true}.'},
        ]
        started = time.perf_counter()
        usage: UsageInfo | None = None
        try:
            response = self._post(messages, "check", timeout=timeout)
            usage = _extract_usage(response)
            _extract_content(response, "check")
        except ProviderError:
            latency_ms = round((time.perf_counter() - started) * 1000.0)
            self._log_model_call("check", 0, usage, latency_ms, "error")
            raise
        latency_ms = round((time.perf_counter() - started) * 1000.0)
        self._log_model_call("check", 0, usage, latency_ms, "ok")
        return latency_ms

    def _run(
        self,
        messages: list[dict[str, Any]],
        model_type: type[_ModelT],
        prefix: str,
    ) -> _ModelT:
        last_error: ProviderError | None = None
        problem = "the response was not valid"
        content = ""
        for attempt in range(self._repair_attempts + 1):
            started = time.perf_counter()
            response = self._post(messages, prefix)
            latency_ms = round((time.perf_counter() - started) * 1000.0)
            usage = _extract_usage(response)
            try:
                content = _extract_content(response, prefix)
                raw = _extract_json_object(content, prefix)
                _normalise_evidence_refs(raw)
                parsed = model_type.model_validate(raw)
            except ProviderError as exc:
                self._log_model_call(prefix, attempt, usage, latency_ms, "invalid")
                last_error = exc
                problem = "the response was not valid JSON"
            except ValidationError as exc:
                fields = [
                    ".".join(str(part) for part in error["loc"]) for error in exc.errors()[:10]
                ]
                self._log_model_call(prefix, attempt, usage, latency_ms, "invalid")
                last_error = ProviderError(
                    f"{prefix}_invalid_output",
                    "The model response did not match the required schema.",
                    retryable=False,
                    details={"fields": fields},
                )
                problem = "the JSON did not match the required schema at: " + ", ".join(fields)
            else:
                self._log_model_call(prefix, attempt, usage, latency_ms, "ok")
                if usage is None:
                    return parsed
                return parsed.model_copy(update={"usage": usage})

            if attempt >= self._repair_attempts:
                break
            messages = build_repair_messages(messages, content, problem)

        if last_error is None:
            raise ProviderError(
                f"{prefix}_invalid_output",
                "The model response could not be validated.",
                retryable=False,
            )
        raise last_error

    def _log_model_call(
        self,
        stage: str,
        attempt: int,
        usage: UsageInfo | None,
        latency_ms: int,
        outcome: str,
    ) -> None:
        logger.info(
            "model_call provider=%s model=%s stage=%s attempt=%s outcome=%s "
            "prompt_tokens=%s completion_tokens=%s total_tokens=%s latency_ms=%s",
            self.name,
            self.model,
            stage,
            attempt,
            outcome,
            "-" if usage is None or usage.prompt_tokens is None else usage.prompt_tokens,
            "-" if usage is None or usage.completion_tokens is None else usage.completion_tokens,
            "-" if usage is None or usage.total_tokens is None else usage.total_tokens,
            latency_ms,
        )


class OpenAICompatibleVisionProvider(_OpenAICompatibleBase):
    def __init__(
        self,
        client: JsonHttpClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        max_retries: int,
        repair_attempts: int,
        kind: SecretKind = "vision",
        usage_meter: UsageMeter | None = None,
    ) -> None:
        super().__init__(
            client,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            repair_attempts=repair_attempts,
            prompt_version=VISION_PROMPT_VERSION,
            kind=kind,
            usage_meter=usage_meter,
        )

    def analyze(self, request: VisionRequest) -> VisionResult:
        encoded = base64.b64encode(request.image.data).decode("ascii")
        data_url = f"data:{request.image.mime_type};base64,{encoded}"
        messages = build_vision_messages(data_url, request.options, request.measurements)
        return self._run(messages, VisionResult, "vision")


class OpenAICompatibleDecisionProvider(_OpenAICompatibleBase):
    def __init__(
        self,
        client: JsonHttpClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        max_retries: int,
        repair_attempts: int,
        kind: SecretKind = "decision",
        usage_meter: UsageMeter | None = None,
    ) -> None:
        super().__init__(
            client,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            repair_attempts=repair_attempts,
            prompt_version=DECISION_PROMPT_VERSION,
            kind=kind,
            usage_meter=usage_meter,
        )

    def diagnose(self, request: DecisionRequest) -> DecisionResult:
        messages = build_decision_messages(request)
        return self._run(messages, DecisionResult, "decision")


class OpenAICompatiblePlannerProvider(_OpenAICompatibleBase):
    def __init__(
        self,
        client: JsonHttpClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        max_retries: int,
        repair_attempts: int,
        kind: SecretKind = "planner",
        usage_meter: UsageMeter | None = None,
    ) -> None:
        super().__init__(
            client,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            repair_attempts=repair_attempts,
            prompt_version=PLANNER_PROMPT_VERSION,
            kind=kind,
            usage_meter=usage_meter,
        )

    def plan(self, request: PlannerRequest) -> PlannerDraft:
        messages = build_planner_messages(request)
        return self._run(messages, PlannerDraft, "planner")

    def adjust(self, request: PatchRequest) -> PatchDraft:
        messages = build_patch_messages(request)
        return self._run(messages, PatchDraft, "patch")


def _extract_content(response: dict[str, Any], prefix: str) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(
            f"{prefix}_invalid_output",
            "The model provider returned no choices.",
            retryable=False,
        )
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None

    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        joined = "".join(parts).strip()
        if joined:
            return joined

    raise ProviderError(
        f"{prefix}_invalid_output",
        "The model provider returned no text content.",
        retryable=False,
    )


def _extract_json_object(content: str, prefix: str) -> dict[str, Any]:
    stripped = content.strip()
    fenced = _FENCED_JSON.match(stripped)
    if fenced:
        stripped = fenced.group(1).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError(
            f"{prefix}_invalid_output",
            "The model response did not contain a JSON object.",
            retryable=False,
        )
    try:
        payload = json.loads(stripped[start : end + 1])
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProviderError(
            f"{prefix}_invalid_output",
            "The model response contained invalid JSON.",
            retryable=False,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderError(
            f"{prefix}_invalid_output",
            "The model response JSON root was not an object.",
            retryable=False,
        )
    return payload


def _normalise_evidence_refs(value: object) -> None:
    """Rewrite model evidence refs to the documented singular prefix in place."""

    if isinstance(value, dict):
        for key, entry in value.items():
            if key in {"evidenceRefs", "evidence_refs"}:
                value[key] = canonical_evidence_refs(entry)
            else:
                _normalise_evidence_refs(entry)
    elif isinstance(value, list):
        for entry in value:
            _normalise_evidence_refs(entry)


def _extract_usage(response: dict[str, Any]) -> UsageInfo | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        return UsageInfo.model_validate(usage)
    except ValidationError:
        return None


def _json_size(value: object) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "OpenAICompatibleDecisionProvider",
    "OpenAICompatiblePlannerProvider",
    "OpenAICompatibleVisionProvider",
]
