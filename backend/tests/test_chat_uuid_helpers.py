from uuid import UUID, uuid4

from app.interfaces.http.chat import _parse_uuid_or_none


def test_parse_uuid_or_none_returns_uuid_for_valid_input() -> None:
    value = uuid4()

    assert _parse_uuid_or_none(str(value)) == value
    assert _parse_uuid_or_none(value) == value


def test_parse_uuid_or_none_returns_none_for_invalid_input() -> None:
    assert _parse_uuid_or_none("not-a-uuid") is None
    assert _parse_uuid_or_none(None) is None
    assert _parse_uuid_or_none(UUID(int=0)) == UUID(int=0)
