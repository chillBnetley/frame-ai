from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_HOST_LENGTH = 253
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_LEGACY_V4_PART = re.compile(r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)$")

_V4_LOCAL_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_V4_LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
_V4_ZERO = ipaddress.ip_network("0.0.0.0/8")
_V4_LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")
_V6_LOCAL_NETWORKS = (ipaddress.ip_network("fc00::/7"),)

_INVALID_URL = "The provider URL is invalid."
_HTTPS_REQUIRED = "The provider URL must use https."
_NOT_ALLOWED = "The provider URL is not allowed by the network policy."
_RESOLUTION_FAILED = "The provider host could not be resolved."

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[..., list[tuple[Any, ...]]]


@dataclass(frozen=True, slots=True)
class ProviderEndpointPolicy:
    """Network boundary policy applied to every provider request."""

    allow_local: bool = False
    allow_insecure_http: bool = False


@dataclass(frozen=True, slots=True)
class ParsedEndpoint:
    scheme: str
    host: str
    port: int
    path: str
    host_header: str
    query: str = ""


@dataclass(frozen=True, slots=True)
class PinnedEndpoint:
    addresses: tuple[str, ...]
    host_header: str
    port: int
    path: str
    scheme: str


class EndpointPolicyError(ValueError):
    """The endpoint is rejected by policy.

    Messages are deliberately static: they never contain the URL, host, IP or
    credentials supplied by the caller.
    """


class EndpointResolutionError(RuntimeError):
    """The host could not be resolved to usable addresses."""


def parse_endpoint(url: str, *, allow_query: bool = False) -> ParsedEndpoint:
    """Parse and normalise an absolute provider URL without any network access.

    ``allow_query`` is only used when following same-origin redirects; saved
    provider base URLs must not carry a query string.
    """

    if not isinstance(url, str) or not url:
        raise EndpointPolicyError(_INVALID_URL)
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in url
    ):
        raise EndpointPolicyError(_INVALID_URL)
    if "\\" in url:
        raise EndpointPolicyError(_INVALID_URL)

    try:
        parts = urllib.parse.urlsplit(url)
        scheme = parts.scheme.lower()
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        raise EndpointPolicyError(_INVALID_URL) from None

    if scheme not in _DEFAULT_PORTS:
        raise EndpointPolicyError(_INVALID_URL)
    if parts.fragment or (parts.query and not allow_query):
        raise EndpointPolicyError(_INVALID_URL)
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in parts.query):
        raise EndpointPolicyError(_INVALID_URL)
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise EndpointPolicyError(_INVALID_URL)
    if not host:
        raise EndpointPolicyError(_INVALID_URL)
    if parts.netloc.endswith(":"):
        raise EndpointPolicyError(_INVALID_URL)

    _validate_host_syntax(host)

    if port is None:
        port = _DEFAULT_PORTS[scheme]
    if port < 1 or port > 65535:
        raise EndpointPolicyError(_INVALID_URL)

    path = parts.path or "/"
    if not path.startswith("/"):
        raise EndpointPolicyError(_INVALID_URL)
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in path):
        raise EndpointPolicyError(_INVALID_URL)

    return ParsedEndpoint(
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        host_header=_host_header(host, port, scheme),
        query=parts.query,
    )


def validate_for_save(endpoint: ParsedEndpoint, policy: ProviderEndpointPolicy) -> None:
    """Validate scheme and literal addresses without performing DNS lookups."""

    if endpoint.scheme == "http" and not policy.allow_insecure_http:
        raise EndpointPolicyError(_HTTPS_REQUIRED)

    literal = _literal_address(endpoint.host)
    if literal is not None and not _is_allowed(literal, policy):
        raise EndpointPolicyError(_NOT_ALLOWED)


def validate_host_for_save(host: str) -> None:
    """Reject legacy numeric IPv4 spellings when saving settings.

    Browsers and some resolvers accept ``127.1``, ``2130706433``,
    ``0x7f000001`` and octal/leading-zero forms as IPv4 addresses, while the
    runtime policy only classifies canonical literals. Refusing them at save
    time keeps the persisted configuration unambiguous without probing DNS.
    Request-time validation is deliberately unchanged.
    """

    if is_legacy_numeric_ipv4(host):
        raise EndpointPolicyError(_NOT_ALLOWED)


def is_legacy_numeric_ipv4(host: str) -> bool:
    """True for 1-4 all-numeric labels that are not a canonical IPv4 literal.

    Domains that contain a non-numeric label (``123.com``,
    ``1.2.3.4.example.com``) are not affected, and a canonical dotted quad is
    left to the policy check so ``allow-local`` can still accept it.
    """

    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return False
    return all(_LEGACY_V4_PART.match(part) for part in parts)


def resolve_and_validate(
    endpoint: ParsedEndpoint,
    policy: ProviderEndpointPolicy,
    resolver: Resolver = socket.getaddrinfo,
) -> PinnedEndpoint:
    """Resolve a host and pin every approved address for the connection."""

    validate_for_save(endpoint, policy)

    literal = _literal_address(endpoint.host)
    if literal is not None:
        return _pinned(endpoint, (str(_normalise(literal)),))

    try:
        results = resolver(endpoint.host, endpoint.port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise EndpointResolutionError(_RESOLUTION_FAILED) from None

    addresses: list[str] = []
    try:
        entries = list(results)
    except TypeError:
        raise EndpointResolutionError(_RESOLUTION_FAILED) from None

    for entry in entries:
        address = _address_from_getaddrinfo(entry)
        normalised = _normalise(address)
        if not _is_allowed(normalised, policy):
            raise EndpointPolicyError(_NOT_ALLOWED)
        text = str(normalised)
        if text not in addresses:
            addresses.append(text)

    if not addresses:
        raise EndpointResolutionError(_RESOLUTION_FAILED)

    return _pinned(endpoint, tuple(addresses))


def _pinned(endpoint: ParsedEndpoint, addresses: tuple[str, ...]) -> PinnedEndpoint:
    return PinnedEndpoint(
        addresses=addresses,
        host_header=endpoint.host_header,
        port=endpoint.port,
        path=endpoint.path,
        scheme=endpoint.scheme,
    )


def _validate_host_syntax(host: str) -> None:
    if _literal_address(host) is not None:
        return
    if len(host) > _MAX_HOST_LENGTH or "%" in host:
        raise EndpointPolicyError(_INVALID_URL)
    labels = host.split(".")
    if any(not _HOST_LABEL.match(label) for label in labels):
        raise EndpointPolicyError(_INVALID_URL)


def _literal_address(host: str) -> IPAddress | None:
    if not host:
        return None
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _address_from_getaddrinfo(entry: tuple[Any, ...]) -> IPAddress:
    if len(entry) < 5:
        raise EndpointResolutionError(_RESOLUTION_FAILED)
    sockaddr = entry[4]
    if not isinstance(sockaddr, tuple) or not sockaddr:
        raise EndpointResolutionError(_RESOLUTION_FAILED)
    raw = sockaddr[0]
    if not isinstance(raw, str):
        raise EndpointResolutionError(_RESOLUTION_FAILED)
    try:
        return ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        raise EndpointResolutionError(_RESOLUTION_FAILED) from None


def _normalise(address: IPAddress) -> IPAddress:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _is_allowed(address: IPAddress, policy: ProviderEndpointPolicy) -> bool:
    address = _normalise(address)
    if address.is_multicast or address.is_unspecified:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        if (
            address in _V4_ZERO
            or address in _V4_LINK_LOCAL
            or address.is_link_local
            or address.is_reserved
        ):
            return False
        if address.is_loopback or address in _V4_LOOPBACK:
            return policy.allow_local
        if any(address in network for network in _V4_LOCAL_NETWORKS):
            return policy.allow_local
        return address.is_global
    if address.is_link_local or address.is_site_local:
        return False
    if address.is_loopback or any(address in network for network in _V6_LOCAL_NETWORKS):
        return policy.allow_local
    if address.is_reserved:
        return False
    return address.is_global


def _host_header(host: str, port: int, scheme: str) -> str:
    rendered = f"[{host}]" if ":" in host else host
    if port == _DEFAULT_PORTS[scheme]:
        return rendered
    return f"{rendered}:{port}"


__all__ = [
    "EndpointPolicyError",
    "EndpointResolutionError",
    "ParsedEndpoint",
    "PinnedEndpoint",
    "ProviderEndpointPolicy",
    "is_legacy_numeric_ipv4",
    "parse_endpoint",
    "resolve_and_validate",
    "validate_for_save",
    "validate_host_for_save",
]
