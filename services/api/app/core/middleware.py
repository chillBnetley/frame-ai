from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models.schemas import error_content

logger = logging.getLogger("frame_ai.http")

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


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
    """Return the unified error envelope when a preflight origin is denied."""

    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") == "OPTIONS"
            and "access-control-request-method" in Headers(scope=scope)
        ):
            origin = Headers(scope=scope).get("origin", "")
            if origin and "*" not in self.allowed_origins and origin not in self.allowed_origins:
                await self._reject(scope, send)
                return
        await self.app(scope, receive, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        body = json.dumps(
            error_content(
                "cors_origin_denied",
                "The request origin is not allowed.",
                {"origin": Headers(scope=scope).get("origin", "")},
            )
        ).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"vary", b"Origin"),
        ]
        state: dict[str, Any] = scope.get("state", {})
        request_id = state.get("request_id")
        if isinstance(request_id, str) and request_id:
            headers.append((b"x-request-id", request_id.encode("ascii")))
        await send({"type": "http.response.start", "status": 403, "headers": headers})
        await send({"type": "http.response.body", "body": body})
