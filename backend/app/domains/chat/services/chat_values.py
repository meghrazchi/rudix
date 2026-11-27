"""Small value coercion helpers shared by the chat pipeline and routes."""

from uuid import UUID


def _parse_uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _decimal_to_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_or_empty(value: object) -> list[object]:
    if value is None:
        return []
    try:
        return list(value)  # type: ignore[arg-type]
    except TypeError:
        return []
