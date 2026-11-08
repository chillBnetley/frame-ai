from __future__ import annotations

import http.client
import json
import random
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.ai.errors import ProviderError
from app.ai.net_policy import (
    EndpointPolicyError,
    EndpointResolutionError,
    ParsedEndpoint,
    PinnedEndpoint,
    ProviderEndpointPolicy,
    parse_endpoint,
    resolve_and_validate,
)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_BACKOFF_SECONDS = 8.0
MAX_REDIRECTS = 5

_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_GET_REDIRECT_STATUSES = frozenset({301, 302, 303})
_HOP_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection"})
_ENTITY_HEADERS = frozenset({"content-type", "content-length", "transfer-encoding"})
_ENDPOINT_MESSAGE = "The configured model provider endpoint is not allowed."
_UNAVAILABLE_MESSAGE = "The model provider could not be reached."
_TIMEOUT_MESSAGE = "The model provider did not respond before the timeout."


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


class PinnedHttpTransport:
    """JSON transport that validates and pins provider addresses.

    Unlike ``UrllibJsonTransport`` this implementation uses ``http.client``
    directly. It therefore ignores ``HTTP_PROXY``/``HTTPS_PROXY`` and always
    connects to an address that was checked against the endpoint policy.
    """

    def __init__(
        self,
        policy: ProviderEndpointPolicy,
        *,
        resolver: Callable[..., list[tuple[Any, ...]]] | None = None,
        connector: Callable[..., socket.socket] | None = None,
        on_attempt: Callable[[], None] | None = None,
    ) -> None:
        self._policy = policy
        self._resolver = resolver
        self._connector = connector
        self._on_attempt = on_attempt

    def post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        try:
            return self._post(url, body, headers, timeout)
        except EndpointPolicyError as exc:
            raise ProviderError(
                "provider_endpoint_error",
                _ENDPOINT_MESSAGE,
                retryable=False,
            ) from exc
        except EndpointResolutionError as exc:
            raise ProviderError(
                "provider_unavailable",
                _UNAVAILABLE_MESSAGE,
                retryable=True,
            ) from exc

    def _post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        endpoint = parse_endpoint(url)
        method = "POST"
        payload: bytes | None = body
        request_headers = dict(headers)
        redirects = 0

        while True:
            if self._resolver is None:
                pinned = resolve_and_validate(endpoint, self._policy)
            else:
                pinned = resolve_and_validate(endpoint, self._policy, self._resolver)
            # The attempt hook runs only after the address passed the policy and
            # resolved, so blocked or DNS-failed calls are never billed. It runs
            # once per hop, i.e. a redirect chain counts each real send.
            if self._on_attempt is not None:
                self._on_attempt()
            response = self._send(
                endpoint,
                pinned,
                method,
                payload,
                request_headers,
                timeout,
            )
            location = _header_value(response.headers, "location")
            if response.status not in _REDIRECT_STATUSES:
                return response
            if not location or redirects >= MAX_REDIRECTS:
                raise EndpointPolicyError(_ENDPOINT_MESSAGE)
            redirects += 1
            endpoint = _redirect_endpoint(endpoint, location)
            if response.status in _GET_REDIRECT_STATUSES:
                method = "GET"
                payload = None
                request_headers = _without_entity_headers(request_headers)

    def _send(
        self,
        endpoint: ParsedEndpoint,
        pinned: PinnedEndpoint,
        method: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        connection: http.client.HTTPConnection
        if endpoint.scheme == "https":
            connection = _PinnedHTTPSConnection(
                endpoint.host,
                endpoint.port,
                pinned.addresses,
                self._connector,
                context=ssl.create_default_context(),
                timeout=timeout,
            )
        else:
            connection = _PinnedHTTPConnection(
                endpoint.host,
                endpoint.port,
                pinned.addresses,
                self._connector,
                timeout=timeout,
            )
        try:
            connection.request(
                method,
                endpoint.path,
                body=body,
                headers=_request_headers(headers),
            )
            raw = connection.getresponse()
            try:
                status = int(raw.status)
                payload = _read_limited(raw)
                response_headers = dict(raw.getheaders())
            finally:
                raw.close()
            return HttpResponse(status=status, body=payload, headers=response_headers)
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError(
                "provider_timeout",
                _TIMEOUT_MESSAGE,
                retryable=True,
            ) from None
        except (ssl.SSLError, OSError, http.client.HTTPException, UnicodeError, ValueError):
            raise ProviderError(
                "provider_unavailable",
                _UNAVAILABLE_MESSAGE,
                retryable=True,
            ) from None
        finally:
            connection.close()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        addresses: tuple[str, ...],
        connector: Callable[..., socket.socket] | None,
        *,
        timeout: float,
    ) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_addresses = addresses
        self._connector = connector

    def connect(self) -> None:
        self.sock = _connect_pinned_socket(
            self._pinned_addresses,
            self.port,
            self.timeout,
            self._connector,
        )
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        addresses: tuple[str, ...],
        connector: Callable[..., socket.socket] | None,
        *,
        context: ssl.SSLContext,
        timeout: float,
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._pinned_addresses = addresses
        self._connector = connector
        self._secure_context = context

    def connect(self) -> None:
        self.sock = _connect_pinned_socket(
            self._pinned_addresses,
            self.port,
            self.timeout,
            self._connector,
        )
        self.sock = self._secure_context.wrap_socket(self.sock, server_hostname=self.host)


def _connect_pinned_socket(
    addresses: tuple[str, ...],
    port: int,
    timeout: float | None,
    connector: Callable[..., socket.socket] | None,
) -> socket.socket:
    create = connector or socket.create_connection
    last_error: OSError | None = None
    for address in addresses:
        try:
            return create((address, port), timeout)
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError(_UNAVAILABLE_MESSAGE)


def _redirect_endpoint(current: ParsedEndpoint, location: str) -> ParsedEndpoint:
    if not location or any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in location
    ):
        raise EndpointPolicyError(_ENDPOINT_MESSAGE)
    try:
        joined = urllib.parse.urljoin(_endpoint_url(current), location)
    except ValueError:
        raise EndpointPolicyError(_ENDPOINT_MESSAGE) from None
    target = parse_endpoint(joined)
    current_origin = (current.scheme, current.host.lower(), current.port)
    target_origin = (target.scheme, target.host.lower(), target.port)
    if target_origin != current_origin:
        raise EndpointPolicyError(_ENDPOINT_MESSAGE)
    return target


def _endpoint_url(endpoint: ParsedEndpoint) -> str:
    return f"{endpoint.scheme}://{endpoint.host_header}{endpoint.path}"


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() not in _HOP_HEADERS}


def _without_entity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() not in _ENTITY_HEADERS}


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
    "MAX_REDIRECTS",
    "MAX_RESPONSE_BYTES",
    "PinnedHttpTransport",
    "UrllibJsonTransport",
]
