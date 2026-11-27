"""Hardened I/O for SAML setup: XML parsing and outbound IdP requests.

SAML metadata and responses come from admins and identity providers, so they
are untrusted. XML is parsed without DTDs or entity expansion, and outbound
requests only reach public http(s) hosts unless
``SSO_METADATA_ALLOW_PRIVATE_HOSTS`` allows an on-prem IdP.

The host is resolved and checked once, and the connection is opened to that
checked IP (TLS still verifies the hostname), so DNS rebinding cannot swap in
an internal address. Redirects are never followed.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.error
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import certifi
from lxml import etree

from app.core.config import settings

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_USER_AGENT = "Rudix-SSO/1.0"


def parse_untrusted_xml(xml_bytes: bytes) -> Any:
    """Parse XML with DTDs, entities and network access disabled.

    Raises ``ValueError`` for malformed XML or any document with a DOCTYPE.
    """
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )
    try:
        root = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc
    if root is None:
        raise ValueError("Invalid XML: empty document")
    if root.getroottree().docinfo.doctype:
        raise ValueError("Invalid XML: DOCTYPE declarations are not allowed")
    return root


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


@dataclass(frozen=True)
class OutboundTarget:
    """A checked outbound request: connect to ``ip``, present ``host``."""

    scheme: str
    host: str
    port: int
    ip: str
    path: str

    @property
    def host_header(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        name = f"[{self.host}]" if ":" in self.host else self.host
        return name if self.port == default_port else f"{name}:{self.port}"


def resolve_outbound_target(url: str) -> OutboundTarget:
    """Resolve and check an IdP URL; raise ``ValueError`` when it is not allowed."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError("IdP URL must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("IdP URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("IdP URL must not contain credentials")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise ValueError("Could not resolve IdP host") from exc
    addresses = [str(info[4][0]) for info in infos]
    if not addresses:
        raise ValueError("Could not resolve IdP host")
    if not settings.sso_metadata_allow_private_hosts and not all(
        _is_public_ip(address) for address in addresses
    ):
        raise ValueError("IdP URL must point to a public host")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return OutboundTarget(scheme=parsed.scheme, host=host, port=port, ip=addresses[0], path=path)


def validate_outbound_url(url: str) -> str:
    """Return ``url`` when it targets an allowed http(s) host; raise ``ValueError`` otherwise."""
    resolve_outbound_target(url)
    return url


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a fixed IP while TLS (SNI and certificate) uses the real hostname."""

    def __init__(self, target: OutboundTarget, timeout: float) -> None:
        # System trust store plus the Mozilla bundle httpx uses, so public IdPs
        # verify everywhere and corporate CAs in the system store still work.
        self._tls_context = ssl.create_default_context()
        self._tls_context.load_verify_locations(certifi.where())
        self._server_hostname = target.host
        super().__init__(target.ip, target.port, timeout=timeout, context=self._tls_context)

    def connect(self) -> None:
        raw = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._tls_context.wrap_socket(raw, server_hostname=self._server_hostname)


class IdpResponse:
    """A successful IdP response; closes the connection with the response."""

    def __init__(self, connection: http.client.HTTPConnection, response: Any) -> None:
        self._connection = connection
        self._response = response
        self.status: int = response.status

    def read(self, amount: int | None = None) -> bytes:
        data: bytes = self._response.read(amount)
        return data

    def close(self) -> None:
        self._response.close()
        self._connection.close()

    def __enter__(self) -> IdpResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _connection_for(target: OutboundTarget, timeout: float) -> http.client.HTTPConnection:
    if target.scheme == "https":
        return _PinnedHTTPSConnection(target, timeout)
    return http.client.HTTPConnection(target.ip, target.port, timeout=timeout)


def open_idp_url(url: str, *, method: str, timeout: float) -> IdpResponse:
    """Request a checked IdP URL on its checked IP, without following redirects.

    Raises ``ValueError`` for a disallowed URL, ``urllib.error.HTTPError`` for a
    non-2xx status (including redirects), and ``urllib.error.URLError`` for
    network or TLS failures.
    """
    target = resolve_outbound_target(url)
    connection = _connection_for(target, timeout)
    headers = {"Host": target.host_header, "User-Agent": _USER_AGENT}
    try:
        connection.request(method, target.path, headers=headers)
        response = connection.getresponse()
    except (OSError, http.client.HTTPException) as exc:
        connection.close()
        raise urllib.error.URLError(str(exc) or type(exc).__name__) from exc
    if not 200 <= response.status < 300:
        status, reason, response_headers = response.status, response.reason, response.msg
        response.close()
        connection.close()
        raise urllib.error.HTTPError(url, status, reason, response_headers, None)
    return IdpResponse(connection, response)


__all__ = [
    "IdpResponse",
    "OutboundTarget",
    "open_idp_url",
    "parse_untrusted_xml",
    "resolve_outbound_target",
    "validate_outbound_url",
]
