"""Hardened I/O for SAML setup: XML parsing and outbound IdP requests.

SAML metadata and responses come from admins and identity providers, so they
are untrusted. XML is parsed without DTDs or entity expansion, and outbound
requests only reach public http(s) hosts (no redirects) unless
``SSO_METADATA_ALLOW_PRIVATE_HOSTS`` allows an on-prem IdP.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

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


def validate_outbound_url(url: str) -> str:
    """Return ``url`` when it targets a public http(s) host; raise ``ValueError`` otherwise."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError("IdP URL must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("IdP URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("IdP URL must not contain credentials")
    if settings.sso_metadata_allow_private_hosts:
        return url
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise ValueError("Could not resolve IdP host") from exc
    if not infos or not all(_is_public_ip(str(info[4][0])) for info in infos):
        raise ValueError("IdP URL must point to a public host")
    return url


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so a public URL cannot bounce to an internal host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def open_idp_url(url: str, *, method: str, timeout: float) -> Any:
    """Open a validated IdP URL without following redirects."""
    safe_url = validate_outbound_url(url)
    request = urllib.request.Request(safe_url, method=method, headers={"User-Agent": _USER_AGENT})
    return _OPENER.open(request, timeout=timeout)


__all__ = [
    "open_idp_url",
    "parse_untrusted_xml",
    "validate_outbound_url",
]
