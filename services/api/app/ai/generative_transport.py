from __future__ import annotations

import json
import random
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.ai.errors import ProviderError
from app.ai.generative import GenerativeProviderError
from app.ai.transport import (
    MAX_RESPONSE_BYTES,
    HttpResponse,
    HttpTransport,
    error_for_status,
)

MAX_BACKOFF_SECONDS = 8.0
DEFAULT_BINARY_RESPONSE_BYTES = 96 * 1024 * 1024
_ERROR_CODE_MAP = {
    "provider_timeout": "generative_provider_timeout",
    "provider_rate_limited": "generative_provider_rate_limited",
    "provider_unavailable": "generative_provider_unavailable",
    "provider_auth_error": "generative_provider_auth_failed",
    "provider_endpoint_error": "generative_provider_endpoint_error",
    "provider_response_too_large": "generative_provider_response_too_large",
    "provider_budget_exceeded": "generative_provider_budget_exceeded",
    "provider_usage_unavailable": "generative_provider_usage_unavailable",
    "invalid_output": "generative_provider_invalid_response",
}


@dataclass(frozen=True, slots=True)
class MultipartFile:
    field: str
    filename: str
    content_type: str
    data: bytes


def _quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def _field_name(value: str) -> str:
    if not value or any(
        character in {'"', "\\", "\r", "\n"} or ord(character) < 0x20 for character in value
    ):
        raise ValueError("multipart field names must be non-empty printable tokens")
    return value


def encode_multipart(
    fields: Mapping[str, str],
    files: Sequence[MultipartFile],
) -> tuple[bytes, str]:
    """Build an RFC 7578 body; the boundary is random per request."""
    boundary = f"frame-{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        safe_name = _field_name(name)
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{safe_name}"\r\n'
                "\r\n"
                f"{value}\r\n"
            ).encode()
        )
    for file in files:
        safe_name = _field_name(file.field)
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{safe_name}"; '
                f'filename="{_quoted(file.filename)}"\r\n'
                f"Content-Type: {file.content_type}\r\n"
                "\r\n"
            ).encode()
        )
        chunks.append(file.data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def normalize_generative_error(exc: ProviderError) -> GenerativeProviderError:
    code = _ERROR_CODE_MAP.get(exc.code, "generative_provider_error")
    return GenerativeProviderError(
        code,
        exc.message,
        retryable=exc.retryable,
        details=dict(exc.details),
    )


class GenerativeHttpClient:
    """HTTP client for image providers: multipart submit, JSON poll, binary fetch.

    All requests go through an ``HttpTransport`` so the same endpoint policy,
    pinned DNS, redirect rules and attempt accounting apply to every call.
    """

    def __init__(
        self,
        transport: HttpTransport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        json_max_bytes: int = MAX_RESPONSE_BYTES,
        binary_max_bytes: int = DEFAULT_BINARY_RESPONSE_BYTES,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._jitter = jitter
        self._json_max_bytes = json_max_bytes
        self._binary_max_bytes = binary_max_bytes

    def submit_multipart(
        self,
        url: str,
        fields: Mapping[str, str],
        files: Sequence[MultipartFile],
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        body, content_type = encode_multipart(fields, files)
        request_headers = {**headers, "Content-Type": content_type}
        response = self._request(
            "POST",
            url,
            body,
            request_headers,
            timeout,
            self._json_max_bytes,
            max_retries,
        )
        return _decode_json(response.body)

    def poll_json(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            url,
            None,
            headers,
            timeout,
            self._json_max_bytes,
            max_retries,
        )
        return _decode_json(response.body)

    def download(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_retries: int = 1,
        max_bytes: int | None = None,
    ) -> tuple[bytes, str | None]:
        limit = self._binary_max_bytes if max_bytes is None else max_bytes
        if limit <= 0:
            raise ValueError("max_bytes must be positive")
        response = self._request(
            "GET",
            url,
            None,
            headers,
            timeout,
            limit,
            max_retries,
        )
        declared = response.header("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    raise ProviderError(
                        "provider_response_too_large",
                        "The model provider response exceeded the allowed size.",
                        retryable=False,
                    )
            except ValueError:
                pass
        return response.body, response.header("content-type")

    def _request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
        max_response_bytes: int,
        max_retries: int,
    ) -> HttpResponse:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        attempt = 0
        while True:
            try:
                response = self._transport.request(
                    method,
                    url,
                    body,
                    headers,
                    timeout,
                    max_response_bytes,
                )
            except ProviderError as exc:
                if not exc.retryable or attempt >= max_retries:
                    raise
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue

            if 200 <= response.status < 300:
                return response

            error = error_for_status(response.status)
            if error.retryable and attempt < max_retries:
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue
            raise error

    def _backoff(self, attempt: int) -> float:
        base = min(2.0**attempt, MAX_BACKOFF_SECONDS)
        return base * (0.9 + 0.2 * self._jitter())


def _decode_json(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(
            "invalid_output",
            "The model provider returned an invalid JSON response.",
            retryable=False,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderError(
            "invalid_output",
            "The model provider returned an unexpected JSON root.",
            retryable=False,
        )
    return payload


__all__ = [
    "DEFAULT_BINARY_RESPONSE_BYTES",
    "GenerativeHttpClient",
    "MAX_BACKOFF_SECONDS",
    "MultipartFile",
    "encode_multipart",
    "normalize_generative_error",
]
