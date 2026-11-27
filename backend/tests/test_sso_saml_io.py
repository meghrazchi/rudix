"""Hardened SAML I/O: no DTD/entity expansion, no SSRF to private hosts."""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.domains.sso.services import saml_io
from app.domains.sso.services.sso_service import (
    _extract_name_id_from_saml_response,
    _fetch_metadata_url,
    _parse_saml_metadata,
)

_METADATA = b"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    entityID="https://idp.example.com">
  <md:IDPSSODescriptor>
    <md:SingleSignOnService Location="https://idp.example.com/sso"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""

_BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    entityID="&lol2;"/>"""

_XXE = b"""<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<r xmlns="urn:oasis:names:tc:SAML:2.0:assertion"><NameID>&x;</NameID></r>"""


def _addrinfo(ip: str) -> list[tuple[Any, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def test_parse_metadata_extracts_fields() -> None:
    parsed = _parse_saml_metadata(_METADATA)
    assert parsed["entity_id"] == "https://idp.example.com"
    assert parsed["sso_url"] == "https://idp.example.com/sso"


def test_parse_metadata_rejects_entity_expansion() -> None:
    with pytest.raises(ValueError, match="DOCTYPE"):
        _parse_saml_metadata(_BILLION_LAUGHS)


def test_saml_response_with_external_entity_is_ignored() -> None:
    assert _extract_name_id_from_saml_response(_XXE) is None


def test_parse_rejects_malformed_xml() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        saml_io.parse_untrusted_xml(b"<not-closed>")


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "10.0.0.5", "172.16.1.1", "192.168.1.1", "169.254.169.254", "::1"]
)
def test_outbound_url_rejects_private_hosts(ip: str) -> None:
    with patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo(ip)):
        with pytest.raises(ValueError, match="public host"):
            saml_io.validate_outbound_url("https://idp.internal/metadata")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://idp.example.com/m", "https://user:pw@idp.example.com/"]
)
def test_outbound_url_rejects_bad_scheme_or_credentials(url: str) -> None:
    with pytest.raises(ValueError):
        saml_io.validate_outbound_url(url)


def test_outbound_url_allows_public_host() -> None:
    with patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        url = "https://idp.example.com/metadata"
        assert saml_io.validate_outbound_url(url) == url


def test_outbound_url_private_hosts_allowed_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "sso_metadata_allow_private_hosts", True)
    url = "https://adfs.corp.local/metadata"
    assert saml_io.validate_outbound_url(url) == url


def test_fetch_metadata_refuses_private_host_without_request() -> None:
    with (
        patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo("10.1.2.3")),
        patch.object(saml_io._OPENER, "open") as opener,
    ):
        with pytest.raises(ValueError, match="public host"):
            _fetch_metadata_url("https://idp.example.com/metadata")
    opener.assert_not_called()


def test_redirects_are_not_followed() -> None:
    handler = saml_io._NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://10.0.0.1/") is None
