from __future__ import annotations

import contextlib
import json
import threading
import urllib.request
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.ai.errors import ProviderError
from app.ai.transport import (
    MAX_RESPONSE_BYTES,
    HttpResponse,
    JsonHttpClient,
    UrllibJsonTransport,
    _SameOriginRedirectHandler,
)

URL = "https://provider.test/v1/chat/completions"
HEADERS = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}


class StubTransport:
    def __init__(self, outcomes: list[HttpResponse | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, bytes, Mapping[str, str], float]] = []

    def post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        self.calls.append((url, body, headers, timeout))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_client(
    transport: StubTransport,
    *,
    sleeps: list[float] | None = None,
) -> JsonHttpClient:
    recorded = sleeps if sleeps is not None else []
    return JsonHttpClient(transport, sleep=recorded.append, jitter=lambda: 0.5)


def ok(payload: dict[str, Any]) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


def test_post_json_sends_body_headers_and_decodes_response():
    transport = StubTransport([ok({"choices": []})])
    client = make_client(transport)

    result = client.post_json(URL, {"model": "m"}, HEADERS, timeout=12, max_retries=0)

    assert result == {"choices": []}
    url, body, headers, timeout = transport.calls[0]
    assert url == URL
    assert json.loads(body) == {"model": "m"}
    assert headers["Authorization"] == "Bearer test-key"
    assert timeout == 12


def test_retries_transient_status_with_exponential_backoff():
    transport = StubTransport(
        [
            HttpResponse(status=503, body=b"{}"),
            HttpResponse(status=500, body=b"{}"),
            ok({"ok": True}),
        ]
    )
    sleeps: list[float] = []
    client = make_client(transport, sleeps=sleeps)

    result = client.post_json(URL, {}, HEADERS, timeout=5, max_retries=2)

    assert result == {"ok": True}
    assert len(transport.calls) == 3
    assert sleeps == pytest.approx([1.0, 2.0])


def test_retry_budget_is_bounded_and_reports_unavailable():
    transport = StubTransport([HttpResponse(status=503, body=b"{}")])
    sleeps: list[float] = []
    client = make_client(transport, sleeps=sleeps)

    with pytest.raises(ProviderError) as error:
        client.post_json(URL, {}, HEADERS, timeout=5, max_retries=2)

    assert error.value.code == "provider_unavailable"
    assert error.value.retryable is True
    assert error.value.details["status"] == 503
    assert len(transport.calls) == 3
    assert len(sleeps) == 2


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (408, "provider_timeout", True),
        (429, "provider_rate_limited", True),
        (500, "provider_unavailable", True),
        (502, "provider_unavailable", True),
        (504, "provider_timeout", True),
        (401, "provider_auth_error", False),
        (403, "provider_auth_error", False),
        (404, "provider_endpoint_error", False),
        (400, "provider_error", False),
    ],
)
def test_status_mapping_and_retryability(status, code, retryable):
    transport = StubTransport([HttpResponse(status=status, body=b"{}")])
    client = make_client(transport)

    with pytest.raises(ProviderError) as error:
        client.post_json(URL, {}, HEADERS, timeout=5, max_retries=3 if retryable else 0)

    assert error.value.code == code
    assert error.value.retryable is retryable
    expected_calls = 4 if retryable else 1
    assert len(transport.calls) == expected_calls


def test_retries_transport_level_transient_errors_only():
    transient = ProviderError("provider_timeout", "timed out", retryable=True)
    fatal = ProviderError("provider_auth_error", "bad key", retryable=False)

    recovered = StubTransport([transient, ok({"ok": True})])
    client = make_client(recovered)
    assert client.post_json(URL, {}, HEADERS, timeout=5, max_retries=1) == {"ok": True}

    fatal_transport = StubTransport([fatal])
    with pytest.raises(ProviderError) as error:
        make_client(fatal_transport).post_json(URL, {}, HEADERS, timeout=5, max_retries=3)
    assert error.value.code == "provider_auth_error"
    assert len(fatal_transport.calls) == 1


def test_invalid_json_is_not_retried():
    transport = StubTransport([HttpResponse(status=200, body=b"not-json")])
    client = make_client(transport)

    with pytest.raises(ProviderError) as error:
        client.post_json(URL, {}, HEADERS, timeout=5, max_retries=3)

    assert error.value.code == "invalid_output"
    assert len(transport.calls) == 1


def test_json_root_must_be_an_object():
    transport = StubTransport([HttpResponse(status=200, body=b"[1,2,3]")])
    with pytest.raises(ProviderError, match="unexpected JSON root"):
        make_client(transport).post_json(URL, {}, HEADERS, timeout=5, max_retries=0)


def test_oversized_response_is_rejected():
    transport = StubTransport([HttpResponse(status=200, body=b"x" * (MAX_RESPONSE_BYTES + 1))])
    with pytest.raises(ProviderError) as error:
        make_client(transport).post_json(URL, {}, HEADERS, timeout=5, max_retries=0)

    assert error.value.code == "provider_response_too_large"


def test_negative_retries_are_rejected():
    client = make_client(StubTransport([]))
    with pytest.raises(ValueError, match="non-negative"):
        client.post_json(URL, {}, HEADERS, timeout=5, max_retries=-1)


class _StubHandler(BaseHTTPRequestHandler):
    status = 200
    payload = b'{"ok":true}'

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args: Any) -> None:
        return


@pytest.fixture
def stub_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/chat/completions"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_urllib_transport_round_trip_against_local_server(stub_server):
    client = JsonHttpClient(UrllibJsonTransport())

    result = client.post_json(stub_server, {"ping": True}, {}, timeout=5, max_retries=0)

    assert result == {"ok": True}


@contextlib.contextmanager
def redirect_server(
    location: str,
) -> Iterator[tuple[str, list[str]]]:
    """A server whose POST redirects to ``location`` and whose GET returns JSON."""
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def _record(self) -> None:
            hits.append(self.path)

        def _reply(self, status: int, payload: bytes, location: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self._record()
            self._reply(302, b"", location=location)

        def do_GET(self) -> None:  # noqa: N802
            self._record()
            self._reply(200, b'{"ok":true}')

        def log_message(self, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/chat/completions", hits
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_same_origin_redirect_is_followed():
    with redirect_server("/final") as (url, hits):
        result = JsonHttpClient(UrllibJsonTransport()).post_json(
            url, {"ping": True}, HEADERS, timeout=5, max_retries=0
        )

    assert result == {"ok": True}
    assert hits == ["/chat/completions", "/final"]


def test_cross_origin_redirect_is_rejected_without_forwarding_credentials():
    with redirect_server("") as (victim_url, victim_hits):
        with redirect_server(victim_url) as (attacker_url, attacker_hits):
            with pytest.raises(ProviderError) as excinfo:
                JsonHttpClient(UrllibJsonTransport()).post_json(
                    attacker_url, {}, HEADERS, timeout=5, max_retries=0
                )

        assert victim_hits == []

    assert attacker_hits == ["/chat/completions"]
    assert excinfo.value.code == "provider_endpoint_error"
    assert excinfo.value.retryable is False
    assert "test-key" not in str(excinfo.value)
    assert "127.0.0.1" not in str(excinfo.value)


def test_https_to_http_downgrade_is_rejected_before_following():
    handler = _SameOriginRedirectHandler(("https", "provider.test", 443))
    request = urllib.request.Request(
        "https://provider.test/v1/chat/completions",
        data=b"{}",
        method="POST",
    )

    with pytest.raises(ProviderError) as excinfo:
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://provider.test/v1/chat/completions",
        )

    assert excinfo.value.code == "provider_endpoint_error"
    assert excinfo.value.retryable is False
    assert "provider.test" not in str(excinfo.value)
