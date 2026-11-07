from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.ai.errors import ProviderError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_BACKOFF_SECONDS = 8.0

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        raise ValueError("url must be absolute http(s) with a host")
    return scheme, host, parts.port or _DEFAULT_PORTS[scheme]


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only while scheme, host and port stay unchanged.

    ``urllib`` keeps the ``Authorization`` header on redirects, so a third-party
    endpoint could otherwise collect the provider key. Cross-origin hops and
    https-to-http downgrades are refused before the redirected request is built.
    """

    def __init__(self, origin: tuple[str, str, int]) -> None:
        super().__init__()
        self._origin = origin

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        target = urllib.parse.urljoin(req.full_url, newurl)
        try:
            target_origin = _origin(target)
        except ValueError as exc:
            raise ProviderError(
                "provider_endpoint_error",
                "The model provider redirected the request to an invalid URL.",
                retryable=False,
            ) from exc
        if target_origin != self._origin:
            raise ProviderError(
                "provider_endpoint_error",
                "The model provider redirected the request to an untrusted origin.",
                retryable=False,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class JsonTransport(Protocol):
    def post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Send a JSON request body and return the raw response."""
        ...


class UrllibJsonTransport:
    """Minimal standard-library transport; no third-party runtime dependency."""

    def post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            origin = _origin(url)
        except ValueError as exc:
            raise ProviderError(
                "provider_endpoint_error",
                "The configured model provider URL is invalid.",
                retryable=False,
            ) from exc
        opener = urllib.request.build_opener(_SameOriginRedirectHandler(origin))
        try:
            with opener.open(request, timeout=timeout) as response:
                return HttpResponse(
                    status=int(getattr(response, "status", 200)),
                    body=_read_limited(response),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status=exc.code,
                body=_read_limited(exc),
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if _is_timeout(exc):
                raise ProviderError(
                    "provider_timeout",
                    "The model provider did not respond before the timeout.",
                    retryable=True,
                ) from exc
            raise ProviderError(
                "provider_unavailable",
                "The model provider could not be reached.",
                retryable=True,
            ) from exc


class JsonHttpClient:
    """JSON POST client with bounded retries for transient failures."""

    def __init__(
        self,
        transport: JsonTransport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._jitter = jitter

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_retries: int,
    ) -> dict[str, Any]:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        attempt = 0
        while True:
            try:
                response = self._transport.post(url, body, headers, timeout)
            except ProviderError as exc:
                if not exc.retryable or attempt >= max_retries:
                    raise
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue

            if len(response.body) > MAX_RESPONSE_BYTES:
                raise ProviderError(
                    "provider_response_too_large",
                    "The model provider response exceeded the allowed size.",
                    retryable=False,
                )

            if 200 <= response.status < 300:
                return _decode_json(response.body)

            error = _error_for_status(response.status)
            if error.retryable and attempt < max_retries:
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue
            raise error

    def _backoff(self, attempt: int) -> float:
        base = min(2.0**attempt, MAX_BACKOFF_SECONDS)
        return base * (0.9 + 0.2 * self._jitter())


def _read_limited(response: Any) -> bytes:
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ProviderError(
            "provider_response_too_large",
            "The model provider response exceeded the allowed size.",
            retryable=False,
        )
    return bytes(data)


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, TimeoutError)


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


def _error_for_status(status: int) -> ProviderError:
    if status in {408, 504}:
        return ProviderError(
            "provider_timeout",
            "The model provider timed out.",
            retryable=True,
            details={"status": status},
        )
    if status == 429:
        return ProviderError(
            "provider_rate_limited",
            "The model provider is rate limited.",
            retryable=True,
            details={"status": status},
        )
    if status in {500, 502, 503}:
        return ProviderError(
            "provider_unavailable",
            "The model provider is temporarily unavailable.",
            retryable=True,
            details={"status": status},
        )
    if status in {401, 403}:
        return ProviderError(
            "provider_auth_error",
            "The model provider rejected the configured credentials.",
            retryable=False,
            details={"status": status},
        )
    if status == 404:
        return ProviderError(
            "provider_endpoint_error",
            "The model provider endpoint was not found.",
            retryable=False,
            details={"status": status},
        )
    return ProviderError(
        "provider_error",
        "The model provider rejected the request.",
        retryable=False,
        details={"status": status},
    )


__all__ = [
    "HttpResponse",
    "JsonHttpClient",
    "JsonTransport",
    "MAX_RESPONSE_BYTES",
    "UrllibJsonTransport",
]
