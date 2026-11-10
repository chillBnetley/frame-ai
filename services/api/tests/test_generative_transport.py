from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.ai.errors import ProviderError
from app.ai.generative import GenerativeProviderError
from app.ai.generative_transport import (
    GenerativeHttpClient,
    MultipartFile,
    encode_multipart,
    normalize_generative_error,
)
from app.ai.net_policy import ProviderEndpointPolicy
from app.ai.transport import PinnedHttpTransport
from tests.conftest import make_image


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.received: list[dict[str, Any]] = []
        self.counters: dict[str, int] = {}
        self.png = make_image()

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A timeout test closes the socket before the handler replies.
        return None


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        import json

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.received.append(
            {
                "method": "POST",
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        if self.path == "/submit":
            self._json({"job_id": "job-1"})
            return
        if self.path == "/retry-once":
            count = self.server.counters.get(self.path, 0) + 1
            self.server.counters[self.path] = count
            if count == 1:
                self._json({"error": "busy"}, status=503)
            else:
                self._json({"ok": True})
            return
        if self.path == "/unauthorized":
            self._json({"error": "auth"}, status=401)
            return
        self._json({"error": "missing"}, status=404)

    def do_GET(self) -> None:
        self.server.received.append(
            {
                "method": "GET",
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": b"",
            }
        )
        if self.path == "/jobs/job-1":
            self._json({"status": "succeeded"})
            return
        if self.path == "/result":
            self._bytes(self.server.png, "image/png")
            return
        if self.path == "/too-large":
            self._bytes(b"x" * 101, "application/octet-stream")
            return
        if self.path == "/bad-json":
            self._bytes(b"not-json", "application/json")
            return
        if self.path == "/slow":
            time.sleep(0.3)
            self._json({"slow": True})
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/result")
            self.end_headers()
            return
        self._json({"error": "missing"}, status=404)


@pytest.fixture
def server():
    instance = _Server()
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def _client(server: _Server) -> GenerativeHttpClient:
    transport = PinnedHttpTransport(
        ProviderEndpointPolicy(allow_local=True, allow_insecure_http=True)
    )
    return GenerativeHttpClient(
        transport,
        sleep=lambda _: None,
        jitter=lambda: 0.0,
        binary_max_bytes=1024,
    )


def _base(server: _Server) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def test_multipart_submit_sends_fields_and_files(server):
    client = _client(server)
    image = b"image-bytes"
    mask = b"mask-bytes"
    response = client.submit_multipart(
        f"{_base(server)}/submit",
        {"model": "m-1", "prompt": "extend"},
        [
            MultipartFile("image", "in.png", "image/png", image),
            MultipartFile("mask", "mask.png", "image/png", mask),
        ],
        {"Authorization": "Bearer test"},
        timeout=5.0,
    )
    assert response == {"job_id": "job-1"}
    received = server.received[0]
    assert received["method"] == "POST"
    assert received["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    body = received["body"]
    assert b'name="model"' in body
    assert b"m-1" in body
    assert b'name="image"' in body
    assert b'filename="in.png"' in body
    assert image in body
    assert mask in body


def test_poll_and_download_use_json_and_binary_limits(server):
    client = _client(server)
    status = client.poll_json(
        f"{_base(server)}/jobs/job-1",
        {},
        timeout=5.0,
    )
    assert status == {"status": "succeeded"}

    body, content_type = client.download(
        f"{_base(server)}/result",
        {},
        timeout=5.0,
    )
    assert content_type == "image/png"
    assert body == server.png

    with pytest.raises(ProviderError) as excinfo:
        client.download(f"{_base(server)}/too-large", {}, timeout=5.0, max_bytes=100)
    assert excinfo.value.code == "provider_response_too_large"


def test_transient_status_is_retried_once(server):
    client = _client(server)
    response = client.submit_multipart(
        f"{_base(server)}/retry-once",
        {"model": "m-1"},
        [],
        {},
        timeout=5.0,
        max_retries=1,
    )
    assert response == {"ok": True}
    assert server.counters["/retry-once"] == 2


def test_auth_error_is_not_retried(server):
    client = _client(server)
    with pytest.raises(ProviderError) as excinfo:
        client.submit_multipart(
            f"{_base(server)}/unauthorized",
            {},
            [],
            {},
            timeout=5.0,
            max_retries=1,
        )
    assert excinfo.value.code == "provider_auth_error"
    assert len(server.received) == 1


def test_invalid_json_and_timeout_are_normalized(server):
    client = _client(server)
    with pytest.raises(ProviderError) as excinfo:
        client.poll_json(f"{_base(server)}/bad-json", {}, timeout=5.0)
    assert excinfo.value.code == "invalid_output"

    with pytest.raises(ProviderError) as timeout_error:
        client.poll_json(f"{_base(server)}/slow", {}, timeout=0.05, max_retries=0)
    assert timeout_error.value.code == "provider_timeout"
    assert timeout_error.value.retryable is True


def test_public_only_policy_rejects_loopback(server):
    transport = PinnedHttpTransport(ProviderEndpointPolicy())
    client = GenerativeHttpClient(transport, sleep=lambda _: None)
    with pytest.raises(ProviderError) as excinfo:
        client.poll_json(f"{_base(server)}/jobs/job-1", {}, timeout=1.0)
    assert excinfo.value.code == "provider_endpoint_error"
    assert server.received == []


def test_same_origin_redirect_is_followed(server):
    client = _client(server)
    body, content_type = client.download(
        f"{_base(server)}/redirect",
        {},
        timeout=5.0,
    )
    assert body == server.png
    assert content_type == "image/png"


def test_normalize_generative_error_maps_codes():
    mapped = normalize_generative_error(ProviderError("provider_timeout", "late", retryable=True))
    assert isinstance(mapped, GenerativeProviderError)
    assert mapped.code == "generative_provider_timeout"
    assert mapped.retryable is True

    unknown = normalize_generative_error(ProviderError("weird", "unknown"))
    assert unknown.code == "generative_provider_error"
    assert unknown.retryable is False


def test_multipart_rejects_header_injection():
    with pytest.raises(ValueError):
        encode_multipart({"bad\r\nname": "x"}, [])
