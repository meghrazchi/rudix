import pytest

from app.clients.clamav_client import ClamAVClient, ClamAVProtocolError


def test_parse_clean_response() -> None:
    response = ClamAVClient._parse_response("stream: OK")

    assert response.status == "clean"
    assert response.signature is None


def test_parse_infected_response() -> None:
    response = ClamAVClient._parse_response("stream: Eicar-Test-Signature FOUND")

    assert response.status == "infected"
    assert response.signature == "Eicar-Test-Signature"


def test_parse_error_response_raises_protocol_error() -> None:
    with pytest.raises(ClamAVProtocolError):
        ClamAVClient._parse_response("stream: Temporary file ERROR")


def test_parse_unexpected_response_raises_protocol_error() -> None:
    with pytest.raises(ClamAVProtocolError):
        ClamAVClient._parse_response("stream: maybe")
