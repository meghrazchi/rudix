"""Database session scopes of the chat pipeline (R05-01, R05-02).

Stages ask the scope for a session by phase:

- ``read()``: authorisation, configuration, and the shortcut (stages 1, 2, and 4). All
  three share one session; the pipeline ends the phase with ``end_read()`` after stage 4,
  which commits so the connection returns to the pool while loaded values stay usable
  (every chat session factory uses ``expire_on_commit=False``; a rollback would expire them).
- ``short()``: one brief lookup during rewriting, retrieval, or verification. Each use gets
  its own session that is committed and closed before the block returns, so nothing is held
  while a model is called.
- ``write()``: persistence (stage 10); the stage commits once.

``ShortSessionScope`` opens a fresh session per phase from a factory (WebSocket) or reuses
the request session and ends every phase with a commit (HTTP). A phase that fails is not
rolled back explicitly: a factory session is closed (which discards its transaction without
expiring loaded objects) and the request session is closed by ``get_db_session``. Every session is bound to
the run's tenant with ``bind_pipeline_session``. ``SingleSessionScope`` yields one caller-
owned session for every phase and never ends a phase (tests and ad hoc callers).
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import CHAT_DB_SESSION_SECONDS
from app.db.tenant_context import bind_pipeline_session

SessionFactory = Callable[[], Any]


class ChatSessionScope(Protocol):
    def read(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    def short(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    def write(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    async def end_read(self) -> None: ...

    async def close(self) -> None: ...


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

    async def end_read(self) -> None:
        return None

    async def close(self) -> None:
        return None


class ShortSessionScope:
    """Short database sessions per phase (R05-02).

    Pass ``request_session`` (HTTP: the request's session serves every phase and each phase
    ends with a commit) or ``session_factory`` (WebSocket: one new session per phase).
    """

    def __init__(
        self,
        *,
        organization_id: UUID,
        session_factory: SessionFactory | None = None,
        request_session: AsyncSession | None = None,
    ) -> None:
        if (session_factory is None) == (request_session is None):
            raise ValueError("pass exactly one of session_factory and request_session")
        self._organization_id = organization_id
        self._factory = session_factory
        self._request_session = request_session
        self._read_session: AsyncSession | None = None
        self._read_stack: AsyncExitStack | None = None
        self._read_started = 0.0

    @property
    def read_open(self) -> bool:
        return self._read_session is not None

    async def _open(self, stack: AsyncExitStack) -> AsyncSession:
        if self._request_session is not None:
            session = self._request_session
        else:
            assert self._factory is not None
            session = await stack.enter_async_context(self._factory())
        await bind_pipeline_session(session, self._organization_id)
        return session

    # -- read phase (stages 1, 2, 4) ------------------------------------------------

    @asynccontextmanager
    async def _read(self) -> AsyncIterator[AsyncSession]:
        if self._read_session is None:
            stack = AsyncExitStack()
            self._read_started = perf_counter()
            try:
                self._read_session = await self._open(stack)
            except BaseException:
                await stack.aclose()
                raise
            self._read_stack = stack
        try:
            yield self._read_session
        except BaseException:
            await self._abort_read()
            raise

    def read(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._read()

    async def end_read(self) -> None:
        """Commit and release the read session (called after stage 4)."""
        session, stack = self._read_session, self._read_stack
        if session is None:
            return
        self._read_session, self._read_stack = None, None
        try:
            await session.commit()
        finally:
            if stack is not None:
                await stack.aclose()
            CHAT_DB_SESSION_SECONDS.labels(phase="read").observe(
                perf_counter() - self._read_started
            )

    async def _abort_read(self) -> None:
        session, stack = self._read_session, self._read_stack
        if session is None:
            return
        self._read_session, self._read_stack = None, None
        # No explicit rollback: closing a factory session discards its transaction without
        # expiring loaded objects; the request session is closed by its dependency.
        try:
            if stack is not None:
                await stack.aclose()
        finally:
            CHAT_DB_SESSION_SECONDS.labels(phase="read").observe(
                perf_counter() - self._read_started
            )

    # -- short lookups and the write phase -------------------------------------------

    @asynccontextmanager
    async def _phase(self, phase: str, *, commit: bool) -> AsyncIterator[AsyncSession]:
        await self.end_read()
        started = perf_counter()
        try:
            async with AsyncExitStack() as stack:
                session = await self._open(stack)
                # On an error the exit stack closes a factory session, which discards its
                # transaction; the request session is closed by its dependency.
                yield session
                if commit:
                    await session.commit()
        finally:
            CHAT_DB_SESSION_SECONDS.labels(phase=phase).observe(perf_counter() - started)

    def short(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._phase("short", commit=True)

    def write(self) -> AbstractAsyncContextManager[AsyncSession]:
        # The persist stage commits (or rolls back) itself, exactly once.
        return self._phase("write", commit=False)

    async def close(self) -> None:
        """End the run: release a read session that a failed run left open."""
        await self._abort_read()
