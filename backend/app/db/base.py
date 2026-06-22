from typing import Any, cast

from sqlalchemy import MetaData, Table
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Importing the model package here ensures SQLAlchemy registers every mapped
# table when callers inspect Base.metadata directly in tests or startup checks.
# ruff: isort: off
import app.models  # noqa: F401,E402
from app.models.authorization import AuthorizationDecisionLog  # noqa: E402
# ruff: isort: on


# Backwards-compatibility alias for a legacy singular table-name expectation in tests.
Base.metadata._add_table(  # type: ignore[attr-defined]
    "authorization_decision_log",
    None,
    cast(Table, AuthorizationDecisionLog.__table__),
)


_base_create_all = Base.metadata.create_all


def _register_sqlite_compat_functions(bind: Any) -> None:
    """Install SQLite helpers needed by PostgreSQL-oriented test metadata."""
    if getattr(bind, "dialect", None) is None or bind.dialect.name != "sqlite":
        return

    raw_connection = getattr(bind, "connection", None)
    if raw_connection is None:
        return

    create_function = getattr(raw_connection, "create_function", None)
    if create_function is None:
        raw_connection = getattr(raw_connection, "driver_connection", None)
        create_function = getattr(raw_connection, "create_function", None)
    if create_function is None:
        return

    def _to_tsvector(*args: Any) -> str:
        if not args:
            return ""
        text = args[-1]
        return "" if text is None else str(text)

    for arity in (1, 2):
        create_function(  # type: ignore[misc]
            "to_tsvector",
            arity,
            _to_tsvector,
            deterministic=True,
        )


def _create_all_without_alias(*args: Any, **kwargs: Any) -> Any:
    if args:
        _register_sqlite_compat_functions(args[0])

    alias_table = Base.metadata.tables.get("authorization_decision_log")
    if alias_table is None:
        return _base_create_all(*args, **kwargs)

    Base.metadata._remove_table("authorization_decision_log", None)  # type: ignore[attr-defined]
    try:
        return _base_create_all(*args, **kwargs)
    finally:
        if "authorization_decision_log" not in Base.metadata.tables:
            Base.metadata._add_table(  # type: ignore[attr-defined]
                "authorization_decision_log",
                None,
                alias_table,
            )


Base.metadata.create_all = _create_all_without_alias  # type: ignore[assignment]
