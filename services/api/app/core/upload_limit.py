from __future__ import annotations

import json
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models.schemas import error_content

UPLOAD_PATH_PREFIX = "/api/v1/images"
_MUTATING_METHODS = {"POST", "PUT", "PATCH"}


class UploadSizeLimitMiddleware:
    """Pure-ASGI body limiter that counts bytes actually received.

    ``UploadFile`` parsing happens before route handlers, so a Content-Length
    check alone cannot protect against chunked requests. Wrapping ``receive``
    lets us stop reading as soon as the real body crosses the limit.

    FastAPI converts any body-parsing exception into a 400, so the limiter must
    not raise through the app. It ends the request stream early and suppresses
    the app's response, then sends the 413 envelope itself.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_upload_bytes: int,
        allowance_bytes: int,
        path_prefix: str = UPLOAD_PATH_PREFIX,
    ) -> None:
        if max_upload_bytes <= 0 or allowance_bytes < 0:
            raise ValueError("upload limits must be positive")
        self.app = app
        self.max_upload_bytes = max_upload_bytes
        self.max_body_bytes = max_upload_bytes + allowance_bytes
        self.path_prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in _MUTATING_METHODS
            or not scope.get("path", "").startswith(self.path_prefix)
        ):
            await self.app(scope, receive, send)
            return

        raw_length = Headers(scope=scope).get("content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > self.max_body_bytes:
                await self._reject(scope, send)
                return

        received = 0
        too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if too_large:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, tracking_send)

        if too_large and not response_started:
            await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        body = json.dumps(
            error_content(
                "payload_too_large",
                "Request body exceeds the allowed size.",
                {
                    "maxBytes": self.max_upload_bytes,
                    "maxBodyBytes": self.max_body_bytes,
                },
            )
        ).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"connection", b"close"),
        ]
        state: dict[str, Any] = scope.get("state", {})
        request_id = state.get("request_id")
        if isinstance(request_id, str) and request_id:
            headers.append((b"x-request-id", request_id.encode("ascii")))
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})
