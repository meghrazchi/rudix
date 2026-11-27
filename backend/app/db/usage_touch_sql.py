"""Max-guarded bulk UPDATE for buffered credential usage (R04-06).

``last_used_at`` only moves forward::

    last_used_at = CASE WHEN last_used_at IS NULL OR last_used_at < :new
                        THEN :new ELSE last_used_at END

and ``last_used_ip`` follows only when the touch is newer. Both ``SET`` expressions read
the pre-update row (standard SQL, PostgreSQL and SQLite), so the IP guard sees the old
timestamp. One statement executed with many parameter sets per table.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table, bindparam, case, or_, update
from sqlalchemy.ext.asyncio import AsyncSession


async def apply_max_guarded_usage(
    db_session: AsyncSession,
    *,
    model: type[Any],
    touches: Sequence[tuple[UUID, datetime, str | None]],
    with_ip: bool,
) -> None:
    if not touches:
        return
    table = cast(Table, model.__table__)
    columns = table.c
    new_used_at = bindparam("b_used_at", type_=columns.last_used_at.type)
    is_newer = or_(columns.last_used_at.is_(None), columns.last_used_at < new_used_at)
    values: dict[str, Any] = {
        "last_used_at": case((is_newer, new_used_at), else_=columns.last_used_at)
    }
    if with_ip:
        new_ip = bindparam("b_ip", type_=columns.last_used_ip.type)
        values["last_used_ip"] = case((is_newer, new_ip), else_=columns.last_used_ip)
    statement = (
        update(table).where(columns.id == bindparam("b_id", type_=columns.id.type)).values(**values)
    )
    params: list[dict[str, Any]] = []
    for credential_id, used_at, ip_address in touches:
        row: dict[str, Any] = {"b_id": credential_id, "b_used_at": used_at}
        if with_ip:
            row["b_ip"] = ip_address
        params.append(row)
    await db_session.execute(statement, params)
