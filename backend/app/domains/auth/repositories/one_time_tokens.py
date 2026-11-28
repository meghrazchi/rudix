"""Persistence for ``auth_one_time_tokens`` (0.9.0, S1).

Every statement matches on ``token_hash`` (SHA-256 hex); raw tokens never reach this layer.
``consume`` is one conditional ``UPDATE ... RETURNING``, so two concurrent consumers of the
same token cannot both succeed: the row lock serialises them and the second one re-checks
``consumed_at IS NULL`` after the first commits.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, delete, or_, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_one_time_token import AuthOneTimeToken

# UPDATE ... RETURNING needs SQLite 3.35; older builds use the select-then-update fallback.
_SQLITE_RETURNING_MIN = (3, 35, 0)


def sqlite_supports_returning(version: tuple[int, ...] | None = None) -> bool:
    return (version or sqlite3.sqlite_version_info) >= _SQLITE_RETURNING_MIN


def _dialect(session: AsyncSession) -> str:
    return session.get_bind().dialect.name


class OneTimeTokenRepository:
    async def insert(self, session: AsyncSession, values: dict[str, Any]) -> bool:
        """Insert one row; ``False`` when ``token_hash`` already exists (nothing written).

        ``ON CONFLICT DO NOTHING`` keeps the surrounding transaction usable, so a duplicate
        SAML id is reported without aborting the caller's work.
        """
        row = {"id": uuid4(), **values}
        dialect = _dialect(session)
        insert_fn = postgresql.insert if dialect == "postgresql" else sqlite.insert
        statement = (
            insert_fn(AuthOneTimeToken)
            .values(**row)
            .on_conflict_do_nothing(index_elements=["token_hash"])
            .returning(AuthOneTimeToken.id)
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _usable(
        *,
        token_hash: str,
        purpose: str,
        now: datetime,
        user_id: UUID | None,
        session_id: UUID | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [
            AuthOneTimeToken.token_hash == token_hash,
            AuthOneTimeToken.purpose == purpose,
            AuthOneTimeToken.consumed_at.is_(None),
            AuthOneTimeToken.expires_at > now,
            AuthOneTimeToken.attempt_count < AuthOneTimeToken.max_attempts,
        ]
        if user_id is not None:
            conditions.append(AuthOneTimeToken.user_id == user_id)
        if session_id is not None:
            conditions.append(AuthOneTimeToken.session_id == session_id)
        return conditions

    async def consume(
        self,
        session: AsyncSession,
        *,
        token_hash: str,
        purpose: str,
        now: datetime,
        user_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> AuthOneTimeToken | None:
        conditions = self._usable(
            token_hash=token_hash,
            purpose=purpose,
            now=now,
            user_id=user_id,
            session_id=session_id,
        )
        if _dialect(session) == "sqlite" and not sqlite_supports_returning():
            return await self._consume_without_returning(session, conditions, now=now)
        result = await session.execute(
            update(AuthOneTimeToken)
            .where(*conditions)
            .values(consumed_at=now)
            .returning(AuthOneTimeToken)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        return result.scalars().first()

    async def _consume_without_returning(
        self,
        session: AsyncSession,
        conditions: list[ColumnElement[bool]],
        *,
        now: datetime,
    ) -> AuthOneTimeToken | None:
        # SQLite only: a write transaction holds the database lock, so the conditional
        # update by id below still consumes once.
        token_id = (
            await session.execute(select(AuthOneTimeToken.id).where(*conditions))
        ).scalar_one_or_none()
        if token_id is None:
            return None
        result = await session.execute(
            update(AuthOneTimeToken)
            .where(AuthOneTimeToken.id == token_id, *conditions)
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            return None
        return await session.get(AuthOneTimeToken, token_id, populate_existing=True)

    async def record_failed_attempt(
        self,
        session: AsyncSession,
        *,
        token_hash: str,
        purpose: str,
        now: datetime,
    ) -> int | None:
        """Increment the attempt count of a usable token; return the new count or ``None``."""
        conditions = self._usable(
            token_hash=token_hash, purpose=purpose, now=now, user_id=None, session_id=None
        )
        statement = (
            update(AuthOneTimeToken)
            .where(*conditions)
            .values(attempt_count=AuthOneTimeToken.attempt_count + 1)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(statement)
        if int(getattr(result, "rowcount", 0) or 0) == 0:
            return None
        row = (
            await session.execute(
                select(AuthOneTimeToken.attempt_count).where(
                    AuthOneTimeToken.token_hash == token_hash,
                    AuthOneTimeToken.purpose == purpose,
                )
            )
        ).scalar_one()
        return int(row)

    async def revoke_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        purpose: str,
        now: datetime,
    ) -> int:
        result = await session.execute(
            update(AuthOneTimeToken)
            .where(
                AuthOneTimeToken.user_id == user_id,
                AuthOneTimeToken.purpose == purpose,
                AuthOneTimeToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def purge(self, session: AsyncSession, *, cutoff: datetime) -> int:
        """Delete rows that expired, or were consumed, before ``cutoff``."""
        result = await session.execute(
            delete(AuthOneTimeToken)
            .where(
                or_(
                    AuthOneTimeToken.expires_at < cutoff,
                    AuthOneTimeToken.consumed_at < cutoff,
                )
            )
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)
