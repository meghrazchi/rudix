"""Celery tasks for the connector sync engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_connector_sync_deferred
from app.db.session import SessionLocal, maintenance_session
from app.domains.connectors.services.ingestion_bridge import ConnectorIngestionBridge
from app.domains.connectors.services.oauth_http_client import HttpOAuthTokenClient
from app.domains.connectors.services.oauth_lifecycle import ConnectorOAuthLifecycleService
from app.domains.connectors.services.sync.lease import reap_stale_runs
from app.domains.connectors.services.sync_engine import ConnectorSyncEngine, SyncEngineError
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app

_logger = get_logger("worker.connector_sync")


async def _run_sync_async(
    *,
    sync_run_id: str,
    organization_id: str,
    lease_owner: str | None = None,
) -> dict[str, Any]:
    """Run or resume one sync run, one transaction per page (R06-11).

    Documents created by a page are dispatched through the outbox when that page commits,
    so nothing is left to dispatch here.
    """
    try:
        run_uuid = UUID(sync_run_id)
        org_uuid = UUID(organization_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid UUID: {exc}") from exc

    engine = ConnectorSyncEngine(
        ingestion_bridge=ConnectorIngestionBridge(),
        oauth_lifecycle=ConnectorOAuthLifecycleService(
            token_client=HttpOAuthTokenClient(),
        ),
    )
    try:
        result = await engine.run_sync(
            SessionLocal,
            sync_run_id=run_uuid,
            organization_id=org_uuid,
            lease_owner=lease_owner,
        )
    except SyncEngineError as exc:
        raise PermanentTaskError(str(exc)) from exc

    return {
        "sync_run_id": sync_run_id,
        "status": result.status,
        "items_seen": result.items_seen,
        "items_upserted": result.items_upserted,
        "items_deleted": result.items_deleted,
        "pages_committed": result.pages_committed,
        "requeue_after_seconds": result.requeue_after_seconds,
    }


def _requeue(*, sync_run_id: str, organization_id: str, countdown: int) -> None:
    """Re-enqueue the same run (long Retry-After, a concurrency cap, or a stale run)."""
    run_connector_sync.apply_async(
        kwargs={"sync_run_id": sync_run_id, "organization_id": organization_id},
        countdown=countdown,
    )
    _logger.info(
        "connector.sync.requeued",
        sync_run_id=sync_run_id,
        organization_id=organization_id,
        countdown=countdown,
    )


async def _mark_run_failed_async(
    *,
    sync_run_id: str,
    organization_id: str,
    error_message: str,
) -> None:
    try:
        run_uuid = UUID(sync_run_id)
        org_uuid = UUID(organization_id)
    except ValueError:
        return

    engine = ConnectorSyncEngine()
    try:
        async with SessionLocal() as session:
            async with session.begin():
                run = await engine.get_sync_run(session, organization_id=org_uuid, run_id=run_uuid)
                if run is not None and run.status == "running":
                    await engine._fail_run(
                        session,
                        run,
                        error_message,
                        error_code="task_terminal_failure",
                    )
    except Exception:
        pass


async def _poll_schedule_async() -> dict[str, Any]:
    engine = ConnectorSyncEngine()
    dispatched_count = 0
    # Cross-tenant beat task: maintenance session (BYPASSRLS role when configured, R04-08).
    async with maintenance_session() as session:
        async with session.begin():
            due = await engine.dispatch_due_syncs(session)

    for run_id, org_id in due:
        celery_app.send_task(
            "connectors.sync.run",
            kwargs={
                "sync_run_id": str(run_id),
                "organization_id": str(org_id),
            },
        )
        dispatched_count += 1

    if dispatched_count:
        _logger.info(
            "connector.sync.schedule_dispatched",
            dispatched=dispatched_count,
            at=datetime.now(UTC).isoformat(),
        )
    return {"dispatched": dispatched_count}


class ConnectorSyncTask(RudixTask):
    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        sync_run_id = kwargs.get("sync_run_id")
        organization_id = kwargs.get("organization_id")
        if not sync_run_id or not organization_id:
            return
        try:
            run_async(
                _mark_run_failed_async(
                    sync_run_id=sync_run_id,
                    organization_id=organization_id,
                    error_message=str(exc),
                )
            )
        except Exception:
            pass
        _logger.warning(
            "connector.sync.task_terminal_failure",
            sync_run_id=sync_run_id,
            organization_id=organization_id,
            error=str(exc),
        )
        try:
            from datetime import UTC
            from datetime import datetime as _dt

            from app.workers.email_helper import emit_connector_sync_failure_email

            _org_owner_id = kwargs.get("owner_user_id")
            emit_connector_sync_failure_email(
                organization_id=organization_id,
                user_id=_org_owner_id,
                connector_name=kwargs.get("connector_name"),
                error_summary=str(exc)[:256],
                failed_at=_dt.now(UTC).strftime("%Y-%m-%d %H:%M"),
            )
        except Exception:
            pass


@celery_app.task(
    name="connectors.sync.run",
    bind=True,
    base=ConnectorSyncTask,
    ignore_result=True,
)
def run_connector_sync(
    self: ConnectorSyncTask,
    *,
    sync_run_id: str,
    organization_id: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Execute (or resume) a single connector sync run."""
    try:
        outcome = run_async(
            _run_sync_async(
                sync_run_id=sync_run_id,
                organization_id=organization_id,
                lease_owner=getattr(self.request, "id", None),
            )
        )
    except TransientTaskError as exc:
        raise self.retry(exc=exc) from exc
    countdown = outcome.get("requeue_after_seconds")
    if countdown:
        _requeue(sync_run_id=sync_run_id, organization_id=organization_id, countdown=countdown)
    return outcome


@celery_app.task(
    name="connectors.sync.schedule_poll",
    bind=True,
    base=RudixTask,
    ignore_result=True,
)
def poll_connector_sync_schedule(self: RudixTask) -> dict[str, Any]:
    """Beat task: poll for due sync jobs and enqueue their runs."""
    return run_async(_poll_schedule_async())


async def _reap_stale_async() -> dict[str, Any]:
    """Re-enqueue running runs whose heartbeat is older than CONNECTOR_SYNC_STALE_SECONDS."""
    # Cross-tenant beat task: maintenance session (BYPASSRLS role when configured).
    async with maintenance_session() as session:
        async with session.begin():
            rows = await reap_stale_runs(
                session,
                now=datetime.now(UTC),
                limit=settings.connector_sync_poll_batch_size,
            )
    for run_id, org_id in rows:
        record_connector_sync_deferred("stale")
        celery_app.send_task(
            "connectors.sync.run",
            kwargs={"sync_run_id": str(run_id), "organization_id": str(org_id)},
        )
    if rows:
        _logger.warning("connector.sync.stale_runs_requeued", count=len(rows))
    return {"requeued": len(rows)}


@celery_app.task(
    name="connectors.sync.reap",
    bind=True,
    base=RudixTask,
    ignore_result=True,
)
def reap_stale_connector_syncs(self: RudixTask) -> dict[str, Any]:
    """Beat task: resume connector sync runs abandoned by a lost worker."""
    return run_async(_reap_stale_async())
