"""Hardened SAML I/O: no DTD/entity expansion, no SSRF to private hosts."""

from __future__ import annotations

import socket
import urllib.error
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
    with patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo("10.0.0.7")):
        target = saml_io.resolve_outbound_target("https://adfs.corp.local/metadata")
    assert (target.ip, target.host) == ("10.0.0.7", "adfs.corp.local")


def test_fetch_metadata_refuses_private_host_without_request() -> None:
    with (
        patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo("10.1.2.3")),
        patch.object(saml_io, "_connection_for") as connection_for,
    ):
        with pytest.raises(ValueError, match="public host"):
            _fetch_metadata_url("https://idp.example.com/metadata")
    connection_for.assert_not_called()


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self.reason = "Reason"
        self.msg: dict[str, str] = {}
        self._body = body
        self.closed = False

    def read(self, amount: int | None = None) -> bytes:
        return self._body if amount is None else self._body[:amount]

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.requests.append((method, path, headers))

    def getresponse(self) -> _FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_request_connects_to_checked_ip_and_sends_real_host() -> None:
    connection = _FakeConnection(_FakeResponse(200, _METADATA))
    with (
        patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")),
        patch.object(saml_io, "_connection_for", return_value=connection) as connection_for,
    ):
        body = _fetch_metadata_url("https://idp.example.com:8443/saml/metadata?tenant=a")
    target = connection_for.call_args.args[0]
    assert target.ip == "93.184.216.34"
    assert target.host == "idp.example.com"
    method, path, headers = connection.requests[0]
    assert (method, path) == ("GET", "/saml/metadata?tenant=a")
    assert headers["Host"] == "idp.example.com:8443"
    assert body == _METADATA
    assert connection.closed


def test_redirect_is_not_followed() -> None:
    connection = _FakeConnection(_FakeResponse(302))
    with (
        patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")),
        patch.object(saml_io, "_connection_for", return_value=connection),
    ):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            saml_io.open_idp_url("https://idp.example.com/sso", method="HEAD", timeout=1)
    assert excinfo.value.code == 302
    assert len(connection.requests) == 1
    assert connection.closed


def test_network_error_is_reported_as_url_error() -> None:
    connection = _FakeConnection(_FakeResponse(200))
    connection.request = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        ConnectionRefusedError("refused")
    )
    with (
        patch.object(saml_io.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")),
        patch.object(saml_io, "_connection_for", return_value=connection),
    ):
        with pytest.raises(ValueError, match="Could not reach"):
            _fetch_metadata_url("https://idp.example.com/metadata")
    assert connection.closed


def test_https_connection_pins_ip_and_verifies_hostname() -> None:
    target = saml_io.OutboundTarget(
        scheme="https", host="idp.example.com", port=443, ip="93.184.216.34", path="/"
    )
    connection = saml_io._connection_for(target, timeout=1)
    assert isinstance(connection, saml_io._PinnedHTTPSConnection)
    assert connection.host == "93.184.216.34"
    assert connection._server_hostname == "idp.example.com"
    assert connection._tls_context.check_hostname is True
    assert target.host_header == "idp.example.com"
