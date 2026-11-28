"""Realtime event envelope, payload whitelist, audience, and Redis keys (R07-07).

An event tells a browser that something it shows may be stale; the browser refetches over
the normal API, which applies every access check again. Events are hints: a worker retry
may publish one twice, and a Redis failure drops one (the client then falls back to polling
or the next reconnect invalidates everything).

Frame (contract 4.2.6): ``id: <n>`` / ``event: <type>`` / ``data:
{"type","organization_id","occurred_at","payload"}``. Payloads carry ids and statuses only
(``PAYLOAD_KEYS``), never names, text, or errors. The audience is stored next to the
envelope in the buffer and is never sent to the client.

Keys are per organisation and environment: ``rudix:{env}:org:{org}:events`` (channel),
``...:events:buffer`` (replay list), ``...:events:seq`` (``INCR`` counter for ids).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings

DOCUMENT_STATUS = "document.status"
DOCUMENTS_CHANGED = "documents.changed"
NOTIFICATION_CREATED = "notification.created"
CONNECTOR_SYNC = "connector.sync"
AGENT_RUN = "agent.run"
INCIDENT = "incident"

PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    DOCUMENT_STATUS: frozenset({"document_id", "status"}),
    DOCUMENTS_CHANGED: frozenset(),
    NOTIFICATION_CREATED: frozenset({"notification_id"}),
    CONNECTOR_SYNC: frozenset({"connection_id", "run_id", "status"}),
    AGENT_RUN: frozenset({"run_id", "status"}),
    INCIDENT: frozenset({"incident_id", "status"}),
}
EVENT_TYPES: frozenset[str] = frozenset(PAYLOAD_KEYS)

ADMIN_ROLES: tuple[str, ...] = ("owner", "admin")
_MAX_VALUE_LENGTH = 64


def _scalar(value: Any) -> str | None:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str) and len(value) <= _MAX_VALUE_LENGTH:
        return value
    if hasattr(value, "value") and isinstance(value.value, str):  # StrEnum members
        return _scalar(value.value)
    return None


def safe_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, str]:
    """Only the whitelisted keys of ``event_type``, as short strings (ids, statuses)."""
    allowed = PAYLOAD_KEYS.get(event_type, frozenset())
    cleaned: dict[str, str] = {}
    for key in sorted(allowed):
        value = _scalar(payload.get(key))
        if value is not None:
            cleaned[key] = value
    return cleaned


def _ids(values: Iterable[UUID | str | None]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values if value is not None}))


@dataclass(frozen=True)
class Audience:
    """Who may receive an event: listed users, members holding a role, or every member."""

    user_ids: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    all_members: bool = False

    @classmethod
    def of(
        cls,
        *,
        user_ids: Iterable[UUID | str | None] = (),
        roles: Iterable[str] = (),
        all_members: bool = False,
    ) -> Audience:
        return cls(
            user_ids=_ids(user_ids),
            roles=tuple(sorted({role.strip().lower() for role in roles if role})),
            all_members=all_members,
        )

    def matches(self, *, user_id: str, roles: Iterable[str]) -> bool:
        if self.all_members or user_id in self.user_ids:
            return True
        held = {role.strip().lower() for role in roles}
        return not held.isdisjoint(self.roles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_ids": list(self.user_ids),
            "roles": list(self.roles),
            "all_members": self.all_members,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Audience:
        if not isinstance(raw, dict):
            return cls()  # matches nobody
        user_ids = raw.get("user_ids")
        roles = raw.get("roles")
        return cls(
            user_ids=tuple(str(v) for v in user_ids) if isinstance(user_ids, list) else (),
            roles=tuple(str(v) for v in roles) if isinstance(roles, list) else (),
            all_members=raw.get("all_members") is True,
        )


@dataclass(frozen=True)
class RealtimeEvent:
    type: str
    organization_id: str
    payload: dict[str, str]
    audience: Audience
    occurred_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    @classmethod
    def build(
        cls,
        event_type: str,
        *,
        organization_id: UUID | str,
        payload: Mapping[str, Any],
        audience: Audience,
    ) -> RealtimeEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown realtime event type {event_type!r}")
        return cls(
            type=event_type,
            organization_id=str(organization_id),
            payload=safe_payload(event_type, payload),
            audience=audience,
        )

    def envelope(self) -> dict[str, Any]:
        """The client-visible data of a frame (no audience)."""
        return {
            "type": self.type,
            "organization_id": self.organization_id,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }

    def to_entry(self, event_id: int) -> str:
        """The buffer and channel entry: id, envelope, and audience."""
        body = {"id": event_id, **self.envelope(), "audience": self.audience.to_dict()}
        return json.dumps(body, separators=(",", ":"))


@dataclass(frozen=True)
class BufferedEvent:
    id: int
    event: RealtimeEvent


def decode_entry(raw: Any) -> BufferedEvent | None:
    """Parse a buffer or channel entry; anything malformed is dropped."""
    try:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("id"), int):
        return None
    event_type = value.get("type")
    organization_id = value.get("organization_id")
    payload = value.get("payload")
    if event_type not in EVENT_TYPES or not isinstance(organization_id, str):
        return None
    return BufferedEvent(
        id=int(value["id"]),
        event=RealtimeEvent(
            type=str(event_type),
            organization_id=organization_id,
            payload=safe_payload(str(event_type), payload if isinstance(payload, dict) else {}),
            audience=Audience.from_dict(value.get("audience")),
            occurred_at=str(value.get("occurred_at") or ""),
        ),
    )


def _base_key(organization_id: UUID | str) -> str:
    return f"rudix:{settings.environment.value}:org:{organization_id}:events"


def channel_name(organization_id: UUID | str) -> str:
    return _base_key(organization_id)


def buffer_key(organization_id: UUID | str) -> str:
    return f"{_base_key(organization_id)}:buffer"


def sequence_key(organization_id: UUID | str) -> str:
    return f"{_base_key(organization_id)}:seq"


def connection_key(organization_id: UUID | str, user_id: UUID | str) -> str:
    return f"rudix:{settings.environment.value}:realtime:connections:{organization_id}:{user_id}"


# Builders used by the publishers --------------------------------------------------------


def document_status_events(
    *,
    organization_id: UUID | str,
    document_id: UUID | str,
    status: str,
    uploader_id: UUID | str | None,
) -> list[RealtimeEvent]:
    """The full event for the uploader and admins, an id-free hint for every member."""
    return [
        RealtimeEvent.build(
            DOCUMENT_STATUS,
            organization_id=organization_id,
            payload={"document_id": document_id, "status": status},
            audience=Audience.of(user_ids=[uploader_id], roles=ADMIN_ROLES),
        ),
        RealtimeEvent.build(
            DOCUMENTS_CHANGED,
            organization_id=organization_id,
            payload={},
            audience=Audience.of(all_members=True),
        ),
    ]


def notification_event(
    *, organization_id: UUID | str, notification_id: UUID | str, user_id: UUID | str
) -> RealtimeEvent:
    return RealtimeEvent.build(
        NOTIFICATION_CREATED,
        organization_id=organization_id,
        payload={"notification_id": notification_id},
        audience=Audience.of(user_ids=[user_id]),
    )


def connector_sync_event(
    *,
    organization_id: UUID | str,
    connection_id: UUID | str,
    run_id: UUID | str,
    status: str,
    creator_id: UUID | str | None,
) -> RealtimeEvent:
    return RealtimeEvent.build(
        CONNECTOR_SYNC,
        organization_id=organization_id,
        payload={"connection_id": connection_id, "run_id": run_id, "status": status},
        audience=Audience.of(user_ids=[creator_id], roles=ADMIN_ROLES),
    )


def agent_run_event(
    *, organization_id: UUID | str, run_id: UUID | str, status: str, user_id: UUID | str | None
) -> RealtimeEvent:
    return RealtimeEvent.build(
        AGENT_RUN,
        organization_id=organization_id,
        payload={"run_id": run_id, "status": status},
        audience=Audience.of(user_ids=[user_id], roles=ADMIN_ROLES),
    )


def incident_event(
    *, organization_id: UUID | str, incident_id: UUID | str, status: str
) -> RealtimeEvent:
    return RealtimeEvent.build(
        INCIDENT,
        organization_id=organization_id,
        payload={"incident_id": incident_id, "status": status},
        audience=Audience.of(all_members=True),
    )
