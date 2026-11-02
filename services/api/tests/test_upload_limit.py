from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.upload_limit import UploadSizeLimitMiddleware
from app.main import create_app


def _settings(tmp_path: Path, *, max_upload_bytes: int = 1024) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=max_upload_bytes,
        max_image_pixels=1_000_000,
        content_length_allowance=0,
        allowed_origins="http://testserver",
        log_level="WARNING",
    )


def test_chunked_body_without_content_length_is_rejected(tmp_path: Path, monkeypatch):
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spool_dir))

    boundary = "frame-boundary"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="stream.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    def body_chunks():
        yield head
        for _ in range(8):
            yield b"x" * 512
        yield tail

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/images",
            content=body_chunks(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "payload_too_large"
    assert body["error"]["details"]["maxBytes"] == 1024
    assert response.headers["x-request-id"]
    assert list(spool_dir.iterdir()) == []


def test_declared_oversized_content_length_rejects_without_reading(tmp_path: Path):
    async def run() -> list[dict[str, Any]]:
        async def app(scope, receive, send):
            raise AssertionError("the application must not run")

        middleware = UploadSizeLimitMiddleware(
            app,
            max_upload_bytes=100,
            allowance_bytes=10,
        )
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/images",
            "headers": [(b"content-length", b"111")],
            "state": {"request_id": "test-request"},
        }
        sent: list[dict[str, Any]] = []

        async def receive():
            raise AssertionError("the body must not be read")

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await middleware(scope, receive, send)  # type: ignore[arg-type]
        return sent

    import asyncio

    sent = asyncio.run(run())
    assert sent[0]["status"] == 413
    headers = dict(sent[0]["headers"])
    assert headers[b"x-request-id"] == b"test-request"
    assert sent[1]["body"]


def test_streaming_receive_aborts_even_without_content_length(tmp_path: Path):
    async def run() -> list[dict[str, Any]]:
        async def app(scope, receive, send):
            while True:
                message = await receive()
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = UploadSizeLimitMiddleware(
            app,
            max_upload_bytes=100,
            allowance_bytes=10,
        )
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/images",
            "headers": [],
            "state": {"request_id": uuid4().hex},
        }
        sent: list[dict[str, Any]] = []

        async def receive():
            return {"type": "http.request", "body": b"x" * 64, "more_body": True}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await middleware(scope, receive, send)  # type: ignore[arg-type]
        return sent

    import asyncio

    sent = asyncio.run(run())
    assert sent[0]["status"] == 413
