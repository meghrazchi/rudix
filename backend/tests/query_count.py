"""Count SQL statements a block of test code sends (R04-03 N+1 guards).

Usage::

    with count_queries(db_session) as counter:
        await do_something(db_session)
    assert counter.count == 3

The counter listens to ``before_cursor_execute`` on the engine behind the session, so it
sees ORM, Core and ``executemany`` statements alike (an ``executemany`` counts once).
Statements carrying the per-transaction session-context marker (R04-08, plan 4.2 item 2)
and savepoint bookkeeping are ignored so counts do not depend on RLS mode or on the
rolled-back PostgreSQL test fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SESSION_CONTEXT_MARKER = "/* rudix:session-context */"
_IGNORED_PREFIXES = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")


@dataclass
class QueryCounter:
    statements: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.statements)

    def matching(self, fragment: str) -> list[str]:
        needle = fragment.upper()
        return [statement for statement in self.statements if needle in statement.upper()]


def _sync_engine(target: AsyncSession | AsyncEngine | Engine) -> Engine:
    if isinstance(target, Engine):
        return target
    if isinstance(target, AsyncEngine):
        return target.sync_engine
    bind = target.bind
    if bind is None:
        raise ValueError("session is not bound to an engine or connection")
    # ``AsyncEngine`` and ``AsyncConnection`` both expose ``sync_engine``.
    return bind.sync_engine


def _should_ignore(statement: str) -> bool:
    if SESSION_CONTEXT_MARKER in statement:
        return True
    return statement.lstrip().upper().startswith(_IGNORED_PREFIXES)


class count_queries:  # used like a function: ``with count_queries(s) as c``
    """Record statements executed on ``target``'s engine inside a ``with``/``async with``.

    The listener is synchronous and attaches to the sync engine the async session drives,
    so both forms behave the same.
    """

    def __init__(self, target: AsyncSession | AsyncEngine | Engine) -> None:
        self._engine = _sync_engine(target)
        self.counter = QueryCounter()

    def _before_cursor_execute(
        self,
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if not _should_ignore(statement):
            self.counter.statements.append(statement)

    def __enter__(self) -> QueryCounter:
        event.listen(self._engine, "before_cursor_execute", self._before_cursor_execute)
        return self.counter

    def __exit__(self, *_exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._before_cursor_execute)

    async def __aenter__(self) -> QueryCounter:
        return self.__enter__()

    async def __aexit__(self, *exc: object) -> None:
        self.__exit__(*exc)
