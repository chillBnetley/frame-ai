from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.auth import ApiTokenService
from app.models.schemas import error_content

logger = logging.getLogger("frame_ai.http")

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_RATE_LIMITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PUBLIC_GET_PATHS = frozenset({"/api/v1/health"})
_UNAUTHORIZED_MESSAGE = "The API token is missing or invalid."
_RATE_LIMITED_MESSAGE = "Too many requests. Try again later."
_CATEGORY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("upload", "/api/v1/images"),
    ("export", "/api/v1/exports"),
    ("analysis", "/api/v1/analysis"),
    ("photographer", "/api/v1/ai/photographer"),
    ("settings", "/api/v1/settings"),
)
_RATE_LIMIT_WINDOW_SECONDS = 60.0


async def _send_error(
    scope: Scope,
    send: Send,
    *,
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(error_content(code, message, details)).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    headers.extend(extra_headers or [])
    state: dict[str, Any] = scope.get("state", {})
    request_id = state.get("request_id")
    if isinstance(request_id, str) and request_id:
        headers.append((b"x-request-id", request_id.encode("ascii")))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else ""
        if not request_id:
            from uuid import uuid4

            request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        start = time.perf_counter()
        status_code = 500
        failed = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            failed = True
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            client = scope.get("client")
            client_host = client[0] if client else "-"
            logger.info(
                "request request_id=%s method=%s path=%s status=%s duration_ms=%.2f client=%s%s",
                request_id,
                scope.get("method", "-"),
                scope.get("path", "-"),
                status_code,
                duration_ms,
                client_host,
                " failed=true" if failed else "",
            )


class CorsPreflightGuardMiddleware:
    """Answer denied preflights with the unified error envelope.

    Without this guard Starlette's ``CORSMiddleware`` replies to a rejected
    method with ``400 text/plain``, which breaks the single error contract.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: list[str],
        allowed_methods: list[str] | None = None,
    ) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)
        self.allowed_methods = {method.upper() for method in (allowed_methods or [])}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "OPTIONS"
            and "access-control-request-method" in Headers(scope=scope)
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin", "")
        if origin and "*" not in self.allowed_origins and origin not in self.allowed_origins:
            await self._reject(
                scope,
                send,
                status=403,
                code="cors_origin_denied",
                message="The request origin is not allowed.",
                details={"origin": origin},
            )
            return

        requested = headers.get("access-control-request-method", "").upper()
        if self.allowed_methods and requested not in self.allowed_methods:
            await self._reject(
                scope,
                send,
                status=405,
                code="cors_method_denied",
                message="The requested method is not allowed for cross-origin calls.",
                details={"method": requested},
            )
            return

        await self.app(scope, receive, send)

    async def _reject(
        self,
        scope: Scope,
        send: Send,
        *,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        await _send_error(
            scope,
            send,
            status=status,
            code=code,
            message=message,
            details=details,
            extra_headers=[(b"vary", b"Origin")],
        )


class LocalOriginGuardMiddleware:
    """Reject cross-site writes and unexpected Host headers (DNS rebinding)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: list[str],
        allowed_hosts: list[str],
    ) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)
        self.allowed_hosts = {host.lower() for host in allowed_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = (urlsplit("//" + headers.get("host", "")).hostname or "").lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            await _send_error(
                scope,
                send,
                status=400,
                code="invalid_host",
                message="The Host header is not allowed.",
            )
            return

        if scope.get("method") not in _SAFE_METHODS:
            origin = headers.get("origin")
            if (
                origin is not None
                and "*" not in self.allowed_origins
                and origin not in self.allowed_origins
            ):
                await _send_error(
                    scope,
                    send,
                    status=403,
                    code="origin_not_allowed",
                    message="The request origin is not allowed.",
                    details={"origin": origin},
                )
                return
            if headers.get("sec-fetch-site") == "cross-site":
                await _send_error(
                    scope,
                    send,
                    status=403,
                    code="origin_not_allowed",
                    message="Cross-site writes are not allowed.",
                )
                return

        await self.app(scope, receive, send)


def rate_limit_category(path: str) -> str:
    for category, prefix in _CATEGORY_PREFIXES:
        if path.startswith(prefix):
            return category
    if path.endswith("/export"):
        return "export"
    if path.endswith("/render") or path.startswith("/api/v1/previews"):
        return "render"
    return "default"


class RateLimiter:
    """Thread-safe per-category token buckets.

    A capacity of 0 disables the category without allocating any state. Buckets
    refill linearly over ``window_seconds``; ``consume`` returns the number of
    seconds to wait when the bucket is empty, or ``None`` when a request is
    allowed.
    """

    def __init__(
        self,
        capacities: Mapping[str, int],
        *,
        window_seconds: float = _RATE_LIMIT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._capacities = {key: max(0, int(value)) for key, value in capacities.items()}
        self._window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    def consume(self, category: str) -> int | None:
        capacity = self._capacities.get(category, 0)
        if capacity <= 0:
            return None
        refill_per_second = capacity / self._window_seconds
        now = self._clock()
        with self._lock:
            tokens, updated = self._buckets.get(category, (float(capacity), now))
            elapsed = max(0.0, now - updated)
            tokens = min(float(capacity), tokens + elapsed * refill_per_second)
            if tokens < 1.0:
                self._buckets[category] = (tokens, now)
                return max(1, math.ceil((1.0 - tokens) / refill_per_second))
            self._buckets[category] = (tokens - 1.0, now)
        return None


class ApiAuthMiddleware:
    """Require a matching token on ``/api/v1`` and apply the write rate limits.

    Runs before the body limiter, so a rejected request never consumes an
    upload. ``OPTIONS`` and the public health probe bypass both checks; root and
    other non-API paths are untouched.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        tokens: ApiTokenService,
        rate_limits: Mapping[str, int],
        limiter: RateLimiter | None = None,
    ) -> None:
        self.app = app
        self._enabled = enabled
        self._tokens = tokens
        self._limiter = limiter or RateLimiter(rate_limits)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._enabled:
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        if (
            not _is_api_path(path)
            or method == "OPTIONS"
            or (method in {"GET", "HEAD"} and path in _PUBLIC_GET_PATHS)
        ):
            await self.app(scope, receive, send)
            return

        provided = Headers(scope=scope).get("x-frame-token")
        if not self._tokens.matches(provided):
            await _send_error(
                scope,
                send,
                status=401,
                code="unauthorized",
                message=_UNAUTHORIZED_MESSAGE,
            )
            return

        if method in _RATE_LIMITED_METHODS:
            category = rate_limit_category(path)
            retry_after = self._limiter.consume(category)
            if retry_after is not None:
                await _send_error(
                    scope,
                    send,
                    status=429,
                    code="rate_limited",
                    message=_RATE_LIMITED_MESSAGE,
                    details={"category": category, "retryAfterSeconds": retry_after},
                    extra_headers=[(b"retry-after", str(retry_after).encode("ascii"))],
                )
                return

        await self.app(scope, receive, send)


def _is_api_path(path: str) -> bool:
    return path == "/api/v1" or path.startswith("/api/v1/")
