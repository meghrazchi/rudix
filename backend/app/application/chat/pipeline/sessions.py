"""Database session scopes of the chat pipeline (R05-01; R05-02 adds short sessions in S2).

Stages ask the scope for a session by phase: ``read()`` for authorisation and configuration,
``short()`` for a brief lookup during retrieval or verification, ``write()`` for persistence.
``SingleSessionScope`` yields the one request session for every phase, which is how the HTTP
route behaves today.
"""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class ChatSessionScope(Protocol):
    def read(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    def short(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    def write(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class SingleSessionScope:
    """Every phase uses the same session; the caller owns its lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    @asynccontextmanager
    async def _yield_session(self) -> AsyncIterator[AsyncSession]:
        yield self._session

    def read(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._yield_session()

    def short(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._yield_session()

    def write(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._yield_session()
