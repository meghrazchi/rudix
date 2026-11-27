"""Transaction scopes for a sync run (R06-11).

``FactoryScope`` opens a new session and transaction for every unit of work (the run
lease, one provider page, one tombstone batch, the completion) and publishes the outbox
rows of that transaction right after its commit. The worker uses it, so a page is visible
to other sessions as soon as it commits and no transaction is open during a provider call.

``SharedSessionScope`` runs every unit on a session the caller holds and only flushes; the
caller commits. It keeps ``run_sync(session, ...)`` working for tests and tools that own
their transaction (the 0.5 behaviour: the whole run is one transaction).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application import outbox
from app.core.logging import get_logger

_logger = get_logger("connectors.sync_engine")

SessionFactory = Callable[[], Any]


class SharedSessionScope:
    shared = True

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        yield self.session
        await self.session.flush()


class FactoryScope:
    shared = False

    def __init__(self, factory: SessionFactory) -> None:
        self.factory = factory

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self.factory() as session:
            async with session.begin():
                yield session
            try:
                await outbox.publish_after_commit(session)
            except Exception as exc:  # the relay publishes rows left pending
                _logger.warning(
                    "connector.sync.outbox_publish_failed", error_type=type(exc).__name__
                )


SyncScope = SharedSessionScope | FactoryScope


def make_scope(session_or_factory: AsyncSession | SessionFactory) -> SyncScope:
    if isinstance(session_or_factory, AsyncSession):
        return SharedSessionScope(session_or_factory)
    return FactoryScope(session_or_factory)
