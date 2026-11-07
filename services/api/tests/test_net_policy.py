from __future__ import annotations

import socket

import pytest

from app.ai.net_policy import (
    EndpointPolicyError,
    EndpointResolutionError,
    ProviderEndpointPolicy,
    parse_endpoint,
    resolve_and_validate,
    validate_for_save,
)

PUBLIC_ONLY = ProviderEndpointPolicy()
ALLOW_LOCAL = ProviderEndpointPolicy(allow_local=True, allow_insecure_http=True)


def addrinfo(*addresses: str) -> list[tuple[object, ...]]:
    entries: list[tuple[object, ...]] = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        entries.append((family, socket.SOCK_STREAM, 6, "", (address, 0)))
    return entries


def sequence_resolver(*answers: list[tuple[str, ...]]):
    remaining = list(answers)

    def resolver(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        return addrinfo(*remaining.pop(0))

    return resolver


@pytest.mark.parametrize(
    ("url", "policy", "allowed"),
    [
        ("https://api.example.com/v1", PUBLIC_ONLY, True),
        ("https://8.8.8.8/v1", PUBLIC_ONLY, True),
        ("https://[2001:4860:4860::8888]/v1", PUBLIC_ONLY, True),
        ("https://10.0.0.5/v1", PUBLIC_ONLY, False),
        ("https://10.0.0.5/v1", ALLOW_LOCAL, True),
        ("https://172.16.0.1/v1", PUBLIC_ONLY, False),
        ("https://192.168.1.10/v1", PUBLIC_ONLY, False),
        ("https://127.0.0.1/v1", PUBLIC_ONLY, False),
        ("https://127.0.0.1/v1", ALLOW_LOCAL, True),
        ("https://169.254.169.254/latest/meta-data", PUBLIC_ONLY, False),
        ("https://169.254.169.254/latest/meta-data", ALLOW_LOCAL, False),
        ("https://[::ffff:127.0.0.1]/v1", PUBLIC_ONLY, False),
        ("https://[::ffff:127.0.0.1]/v1", ALLOW_LOCAL, True),
        ("https://[::ffff:10.0.0.5]/v1", PUBLIC_ONLY, False),
        ("https://[::ffff:10.0.0.5]/v1", ALLOW_LOCAL, True),
        ("https://[::ffff:169.254.169.254]/v1", ALLOW_LOCAL, False),
        ("https://0.0.0.0/v1", PUBLIC_ONLY, False),
        ("https://0.0.0.0/v1", ALLOW_LOCAL, False),
        ("https://0.1.2.3/v1", PUBLIC_ONLY, False),
        ("https://0.1.2.3/v1", ALLOW_LOCAL, False),
        ("https://255.255.255.255/v1", ALLOW_LOCAL, False),
        ("https://224.0.0.1/v1", PUBLIC_ONLY, False),
        ("https://224.0.0.1/v1", ALLOW_LOCAL, False),
        ("https://[ff02::1]/v1", ALLOW_LOCAL, False),
        ("https://[::]/v1", ALLOW_LOCAL, False),
        ("https://240.0.0.1/v1", PUBLIC_ONLY, False),
        ("https://240.0.0.1/v1", ALLOW_LOCAL, False),
        ("https://100.64.0.1/v1", PUBLIC_ONLY, False),
        ("https://100.64.0.1/v1", ALLOW_LOCAL, False),
        ("https://192.0.2.1/v1", PUBLIC_ONLY, False),
        ("https://192.0.2.1/v1", ALLOW_LOCAL, False),
        ("https://[fe80::1]/v1", PUBLIC_ONLY, False),
        ("https://[fe80::1]/v1", ALLOW_LOCAL, False),
        ("https://[fd00::1]/v1", PUBLIC_ONLY, False),
        ("https://[fd00::1]/v1", ALLOW_LOCAL, True),
        ("https://[::1]/v1", PUBLIC_ONLY, False),
        ("https://[::1]/v1", ALLOW_LOCAL, True),
        ("http://api.example.com/v1", PUBLIC_ONLY, False),
        (
            "http://api.example.com/v1",
            ProviderEndpointPolicy(allow_insecure_http=True),
            True,
        ),
        ("http://127.0.0.1/v1", ALLOW_LOCAL, True),
        (
            "http://127.0.0.1/v1",
            ProviderEndpointPolicy(allow_local=True),
            False,
        ),
    ],
)
def test_literal_address_and_scheme_classification(url, policy, allowed):
    endpoint = parse_endpoint(url)

    if allowed:
        validate_for_save(endpoint, policy)
    else:
        with pytest.raises(EndpointPolicyError):
            validate_for_save(endpoint, policy)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://api.example.com/v1",
        "file:///etc/passwd",
        "https:///v1",
        "https://user:pass@api.example.com/v1",
        "https://api.example.com/v1?temperature=0",
        "https://api.example.com/v1#fragment",
        "https://api.example.com:0/v1",
        "https://api.example.com:abc/v1",
        "https://api.example.com:99999/v1",
        "https://api.example.com:/v1",
        "https://api.example.com/v1\n",
        "https://api.example.com /v1",
        "https://api.example.com\\v1",
        "https://api.example.com/v1 path",
        "https://_service.example.com/v1",
        "https://-bad.example.com/v1",
        "https://bad-.example.com/v1",
        "https://api..example.com/v1",
        "https://[::1/v1",
    ],
)
def test_invalid_urls_are_rejected_without_echoing_them(url):
    with pytest.raises(EndpointPolicyError) as error:
        parse_endpoint(url)

    assert str(error.value) == "The provider URL is invalid."
    assert "api.example.com" not in str(error.value)
    assert "127.0.0.1" not in str(error.value)


def test_saving_a_dns_name_never_resolves(monkeypatch: pytest.MonkeyPatch):
    def fail(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        raise AssertionError("DNS must not run while validating for save")

    monkeypatch.setattr(socket, "getaddrinfo", fail)

    validate_for_save(parse_endpoint("https://api.example.com/v1"), PUBLIC_ONLY)


@pytest.mark.parametrize(
    ("url", "host_header"),
    [
        ("https://api.example.com/v1", "api.example.com"),
        ("https://api.example.com:443/v1", "api.example.com"),
        ("https://api.example.com:8443/v1", "api.example.com:8443"),
        ("http://api.example.com:80/v1", "api.example.com"),
        ("http://api.example.com:8080/v1", "api.example.com:8080"),
        ("https://[2001:db8::1]/v1", "[2001:db8::1]"),
        ("https://[2001:db8::1]:8443/v1", "[2001:db8::1]:8443"),
    ],
)
def test_host_header_preserves_the_original_host(url, host_header):
    assert parse_endpoint(url).host_header == host_header


def test_empty_path_defaults_to_root():
    assert parse_endpoint("https://api.example.com").path == "/"


def test_resolve_pins_every_validated_address_in_order():
    resolver = sequence_resolver(("8.8.8.8", "1.1.1.1"))

    pinned = resolve_and_validate(
        parse_endpoint("https://api.example.com/v1"),
        PUBLIC_ONLY,
        resolver,
    )

    assert pinned.addresses == ("8.8.8.8", "1.1.1.1")
    assert pinned.host_header == "api.example.com"
    assert pinned.port == 443
    assert pinned.path == "/v1"


def test_resolve_rejects_the_whole_answer_when_any_address_is_private():
    resolver = sequence_resolver(("8.8.8.8", "127.0.0.1"))

    with pytest.raises(EndpointPolicyError):
        resolve_and_validate(
            parse_endpoint("https://api.example.com/v1"),
            PUBLIC_ONLY,
            resolver,
        )


def test_resolve_normalizes_ipv4_mapped_addresses():
    resolver = sequence_resolver(("::ffff:8.8.8.8",))

    pinned = resolve_and_validate(
        parse_endpoint("https://api.example.com/v1"),
        PUBLIC_ONLY,
        resolver,
    )

    assert pinned.addresses == ("8.8.8.8",)


def test_resolve_does_not_call_dns_for_literal_addresses():
    def fail(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        raise AssertionError("literal addresses must not be resolved")

    pinned = resolve_and_validate(
        parse_endpoint("https://8.8.8.8/v1"),
        PUBLIC_ONLY,
        fail,
    )

    assert pinned.addresses == ("8.8.8.8",)


def test_resolution_failure_is_retryable_and_safe():
    def fail(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        raise socket.gaierror(-2, "Name or service not known")

    with pytest.raises(EndpointResolutionError) as error:
        resolve_and_validate(
            parse_endpoint("https://private.example.test/v1"),
            PUBLIC_ONLY,
            fail,
        )

    message = str(error.value)
    assert "private.example.test" not in message
    assert "Name or service" not in message


def test_empty_resolution_fails_closed():
    with pytest.raises(EndpointResolutionError):
        resolve_and_validate(
            parse_endpoint("https://api.example.com/v1"),
            PUBLIC_ONLY,
            sequence_resolver(()),
        )


def test_dns_rebinding_second_answer_is_rejected_before_connect():
    resolver = sequence_resolver(("8.8.8.8",), ("127.0.0.1",))
    endpoint = parse_endpoint("https://api.example.com/v1")

    first = resolve_and_validate(endpoint, PUBLIC_ONLY, resolver)
    assert first.addresses == ("8.8.8.8",)

    with pytest.raises(EndpointPolicyError):
        resolve_and_validate(endpoint, PUBLIC_ONLY, resolver)


def test_policy_messages_do_not_echo_addresses():
    with pytest.raises(EndpointPolicyError) as error:
        validate_for_save(parse_endpoint("https://10.9.8.7/v1"), PUBLIC_ONLY)

    message = str(error.value)
    assert "10.9.8.7" not in message
    assert "https://" not in message
