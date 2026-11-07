from __future__ import annotations

import contextlib
import json
import socket
import threading
import urllib.request
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.ai.errors import ProviderError
from app.ai.net_policy import ProviderEndpointPolicy
from app.ai.transport import (
    MAX_RESPONSE_BYTES,
    HttpResponse,
    JsonHttpClient,
    PinnedHttpTransport,
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


LOCAL_POLICY = ProviderEndpointPolicy(allow_local=True, allow_insecure_http=True)
PUBLIC_POLICY = ProviderEndpointPolicy()


@contextlib.contextmanager
def pinned_server(
    *,
    location: str | None = None,
    redirect_status: int = 307,
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def _handle(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            requests.append(
                {
                    "method": method,
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                }
            )
            if location is not None and self.path != "/final":
                status = redirect_status
            else:
                status = 200
            payload = b'{"ok":true}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def log_message(self, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/chat/completions", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def local_resolver(*addresses: str):
    def resolve(host: str, port: int, **kwargs: object):
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolve


def test_pinned_transport_round_trip_against_local_server():
    with pinned_server() as (url, requests):
        client = JsonHttpClient(PinnedHttpTransport(LOCAL_POLICY))

        result = client.post_json(url, {"ping": True}, HEADERS, timeout=5, max_retries=0)

    assert result == {"ok": True}
    assert len(requests) == 1
    assert requests[0]["method"] == "POST"
    assert requests[0]["headers"]["Host"] == url.split("/")[2]
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"


def test_pinned_transport_connects_to_the_validated_ip(monkeypatch: pytest.MonkeyPatch):
    seen: list[tuple[str, int]] = []
    real_create = socket.create_connection

    def recording(address, timeout=None, source_address=None):
        seen.append(address)
        return real_create(address, timeout, source_address)

    monkeypatch.setattr(socket, "create_connection", recording)

    with pinned_server() as (url, requests):
        target = url.replace("127.0.0.1", "rebind.example.test")
        transport = PinnedHttpTransport(
            LOCAL_POLICY,
            resolver=local_resolver("127.0.0.1"),
        )
        result = JsonHttpClient(transport).post_json(
            target,
            {"ping": True},
            HEADERS,
            timeout=5,
            max_retries=0,
        )

    assert result == {"ok": True}
    assert len(seen) == 1
    assert seen[0][0] == "127.0.0.1"
    port = url.split(":")[2].split("/")[0]
    assert requests[0]["headers"]["Host"] == f"rebind.example.test:{port}"


def test_pinned_transport_rejects_a_rebound_answer_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
):
    connections: list[tuple[str, int]] = []
    real_create = socket.create_connection

    def recording(address, timeout=None, source_address=None):
        connections.append(address)
        return real_create(address, timeout, source_address)

    monkeypatch.setattr(socket, "create_connection", recording)
    answers = [("127.0.0.1",), ("192.0.2.1",)]

    def resolver(host: str, port: int, **kwargs: object):
        return local_resolver(*answers.pop(0))(host, port, **kwargs)

    with pinned_server() as (url, requests):
        target = url.replace("127.0.0.1", "rebind.example.test")
        transport = PinnedHttpTransport(LOCAL_POLICY, resolver=resolver)
        client = JsonHttpClient(transport)

        assert client.post_json(target, {}, HEADERS, timeout=5, max_retries=0) == {"ok": True}
        with pytest.raises(ProviderError) as excinfo:
            client.post_json(target, {}, HEADERS, timeout=5, max_retries=0)

    assert excinfo.value.code == "provider_endpoint_error"
    assert len(connections) == 1
    assert len(requests) == 1


def test_pinned_transport_ignores_environment_proxies(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:1")

    with pinned_server() as (url, requests):
        result = JsonHttpClient(PinnedHttpTransport(LOCAL_POLICY)).post_json(
            url,
            {"ping": True},
            HEADERS,
            timeout=5,
            max_retries=0,
        )

    assert result == {"ok": True}
    assert len(requests) == 1


def test_pinned_transport_preserves_body_on_307_redirect():
    with pinned_server(location="/final", redirect_status=307) as (url, requests):
        result = JsonHttpClient(PinnedHttpTransport(LOCAL_POLICY)).post_json(
            url,
            {"ping": True},
            HEADERS,
            timeout=5,
            max_retries=0,
        )

    assert result == {"ok": True}
    assert [request["method"] for request in requests] == ["POST", "POST"]
    assert requests[0]["body"] == requests[1]["body"]
    assert json.loads(requests[1]["body"]) == {"ping": True}


def test_pinned_transport_converts_302_to_get_without_body():
    with pinned_server(location="/final", redirect_status=302) as (url, requests):
        result = JsonHttpClient(PinnedHttpTransport(LOCAL_POLICY)).post_json(
            url,
            {"ping": True},
            HEADERS,
            timeout=5,
            max_retries=0,
        )

    assert result == {"ok": True}
    assert [request["method"] for request in requests] == ["POST", "GET"]
    assert requests[1]["body"] == b""
    assert "Content-Type" not in requests[1]["headers"]


def test_pinned_transport_rejects_cross_origin_redirect_without_forwarding_headers():
    with pinned_server() as (victim_url, victim_requests):
        with pinned_server(location=victim_url) as (attacker_url, attacker_requests):
            with pytest.raises(ProviderError) as excinfo:
                JsonHttpClient(PinnedHttpTransport(LOCAL_POLICY)).post_json(
                    attacker_url,
                    {},
                    HEADERS,
                    timeout=5,
                    max_retries=0,
                )

    assert victim_requests == []
    assert len(attacker_requests) == 1
    assert attacker_requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert excinfo.value.code == "provider_endpoint_error"
    assert excinfo.value.retryable is False
    assert "test-key" not in str(excinfo.value)
    assert "127.0.0.1" not in str(excinfo.value)


def test_pinned_transport_rejects_https_to_http_downgrade(monkeypatch: pytest.MonkeyPatch):
    transport = PinnedHttpTransport(
        PUBLIC_POLICY,
        resolver=local_resolver("8.8.8.8"),
    )
    calls: list[str] = []

    def fake_send(endpoint, pinned, method, body, headers, timeout):
        calls.append(endpoint.scheme)
        return HttpResponse(
            status=302,
            body=b"",
            headers={"Location": "http://provider.test/v2/chat/completions"},
        )

    monkeypatch.setattr(transport, "_send", fake_send)

    with pytest.raises(ProviderError) as excinfo:
        transport.post(
            "https://provider.test/v1/chat/completions",
            b"{}",
            HEADERS,
            timeout=5,
        )

    assert calls == ["https"]
    assert excinfo.value.code == "provider_endpoint_error"
    assert excinfo.value.retryable is False
    assert "provider.test" not in str(excinfo.value)


def test_pinned_transport_stops_after_five_redirects():
    with pinned_server(location="/loop", redirect_status=307) as (url, requests):
        with pytest.raises(ProviderError) as excinfo:
            JsonHttpClient(PinnedHttpTransport(LOCAL_POLICY)).post_json(
                url,
                {},
                HEADERS,
                timeout=5,
                max_retries=0,
            )

    assert excinfo.value.code == "provider_endpoint_error"
    assert len(requests) == 6


def test_pinned_transport_rejects_private_literal_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail(*args: object, **kwargs: object):
        raise AssertionError("no connection may be attempted")

    monkeypatch.setattr(socket, "create_connection", fail)

    with pytest.raises(ProviderError) as excinfo:
        PinnedHttpTransport(PUBLIC_POLICY).post(
            "https://10.9.8.7/v1/chat/completions",
            b"{}",
            HEADERS,
            timeout=5,
        )

    assert excinfo.value.code == "provider_endpoint_error"
    assert excinfo.value.retryable is False
    assert "10.9.8.7" not in str(excinfo.value)
    assert "test-key" not in str(excinfo.value)


def test_pinned_transport_reports_resolution_failure_as_retryable():
    def fail(host: str, port: int, **kwargs: object):
        raise socket.gaierror(-2, "Name or service not known")

    with pytest.raises(ProviderError) as excinfo:
        PinnedHttpTransport(PUBLIC_POLICY, resolver=fail).post(
            "https://provider.test/v1/chat/completions",
            b"{}",
            HEADERS,
            timeout=5,
        )

    assert excinfo.value.code == "provider_unavailable"
    assert excinfo.value.retryable is True
    assert "provider.test" not in str(excinfo.value)
    assert "test-key" not in str(excinfo.value)
