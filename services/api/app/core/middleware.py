from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models.schemas import error_content

logger = logging.getLogger("frame_ai.http")

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


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
