"""ORM change observers that record realtime events at flush time (R07-07).

One ``after_flush`` listener covers every ORM path that changes what the events describe,
so each choke point (``status_tracking.set_document_status`` / ``mark_document_failed``,
the finalize stage, deletion, upload and reindex workflows, notification creation, sync run
transitions, incident create/update/resolve) publishes without per-call wiring:

* ``Document``: inserted, deleted, or ``status`` / ``graph_extraction_status`` changed ->
  ``document.status`` (uploader and owner/admin) plus ``documents.changed`` (every member).
* ``ConnectorSyncRun``: inserted or ``status`` changed -> ``connector.sync`` (owner/admin
  and the connection's creator).
* ``Notification``: inserted -> ``notification.created`` (the recipient only).
* ``Incident``: inserted, changed, or deleted -> ``incident`` (every member).

Core ``UPDATE`` statements bypass the ORM; those call sites record events explicitly
(processing claim, reaper exhaustion, sync lease). The events are recorded on the session
and published only after the commit (``publisher.py``).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, UOWTransaction
from sqlalchemy.orm.util import identity_key

from app.application.realtime.publisher import record_realtime_event
from app.core.config import settings
from app.domains.realtime.events import (
    RealtimeEvent,
    connector_sync_event,
    document_status_events,
    incident_event,
    notification_event,
)
from app.models.connector import ConnectorConnection
from app.models.connector_sync import ConnectorSyncRun
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.incident import Incident
from app.models.notification import Notification


def _loaded(instance: Any, name: str) -> Any:
    return inspect(instance).dict.get(name)


def _status_changed(instance: Any, *fields: str) -> bool:
    attrs = inspect(instance).attrs
    return any(attrs[name].history.has_changes() for name in fields or ("status",))


def connection_creator(session: Session, connection_id: UUID | None) -> UUID | None:
    """Creator of a connector connection, without a lazy load inside the flush."""
    if connection_id is None:
        return None
    connection = session.identity_map.get(identity_key(ConnectorConnection, connection_id))
    if connection is not None:
        return _loaded(connection, "created_by_user_id")  # type: ignore[no-any-return]
    result = session.connection().execute(
        select(ConnectorConnection.created_by_user_id).where(
            ConnectorConnection.id == connection_id
        )
    )
    return result.scalar_one_or_none()  # type: ignore[no-any-return]


def _document(instance: Document, *, deleted: bool) -> list[RealtimeEvent]:
    status = DocumentStatus.deleted.value if deleted else _loaded(instance, "status")
    organization_id = _loaded(instance, "organization_id")
    document_id = _loaded(instance, "id")
    if organization_id is None or document_id is None or not status:
        return []
    return document_status_events(
        organization_id=organization_id,
        document_id=document_id,
        status=str(status),
        uploader_id=_loaded(instance, "uploaded_by_user_id"),
    )


def _sync_run(session: Session, instance: ConnectorSyncRun) -> list[RealtimeEvent]:
    organization_id = _loaded(instance, "organization_id")
    run_id = _loaded(instance, "id")
    connection_id = _loaded(instance, "connection_id")
    status = _loaded(instance, "status")
    if organization_id is None or run_id is None or connection_id is None or not status:
        return []
    return [
        connector_sync_event(
            organization_id=organization_id,
            connection_id=connection_id,
            run_id=run_id,
            status=str(status),
            creator_id=connection_creator(session, connection_id),
        )
    ]


def _notification(instance: Notification) -> list[RealtimeEvent]:
    organization_id = _loaded(instance, "organization_id")
    notification_id = _loaded(instance, "id")
    user_id = _loaded(instance, "user_id")
    if organization_id is None or notification_id is None or user_id is None:
        return []
    return [
        notification_event(
            organization_id=organization_id, notification_id=notification_id, user_id=user_id
        )
    ]


def _incident(instance: Incident) -> list[RealtimeEvent]:
    organization_id = _loaded(instance, "organization_id")
    incident_id = _loaded(instance, "id")
    if organization_id is None or incident_id is None:
        return []
    return [
        incident_event(
            organization_id=organization_id,
            incident_id=incident_id,
            status=str(_loaded(instance, "status") or ""),
        )
    ]


def _collect(session: Session, instance: Any, change: str) -> list[RealtimeEvent]:
    if isinstance(instance, Document):
        # Graph extraction progress is shown next to the status, so it counts as a change.
        if change == "dirty" and not _status_changed(instance, "status", "graph_extraction_status"):
            return []
        return _document(instance, deleted=change == "deleted")
    if isinstance(instance, ConnectorSyncRun):
        if change == "deleted" or (change == "dirty" and not _status_changed(instance)):
            return []
        return _sync_run(session, instance)
    if isinstance(instance, Notification):
        return _notification(instance) if change == "new" else []
    if isinstance(instance, Incident):
        return _incident(instance)
    return []


def after_flush(session: Session, flush_context: UOWTransaction) -> None:
    del flush_context
    if not settings.realtime_events_enabled:
        return
    events: list[RealtimeEvent] = []
    for change, instances in (
        ("new", session.new),
        ("dirty", session.dirty),
        ("deleted", session.deleted),
    ):
        for instance in instances:
            events.extend(_collect(session, instance, change))
    if events:
        record_realtime_event(session, events)
