"""Pipeline-explorer telemetry for one document run (moved from document_tasks, R06-01).

Behaviour is unchanged; the session factory and repository are read from the facade at
call time (``current_deps()``) so tests that rebind ``document_tasks.SessionLocal`` still
capture the events. Every write uses its own short session.

One processing run spans several tasks in chain mode (and several deliveries in either
mode). ``open_for_run`` resumes the pipeline run whose id the run's extract stage keeps in
its metrics (``PIPELINE_RUN_KEY``), continuing at the next event sequence stored in the
database, and creates a new pipeline run only when there is none (R06-01 part 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import settings
from app.domains.pipeline.services.pipeline_event_service import sanitize_pipeline_payload
from app.models.pipeline import PipelineEvent, PipelineRun
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import safe_duration_ms

# Key of the pipeline-explorer run id in the extract stage row's metrics.
PIPELINE_RUN_KEY = "pipeline_run_id"


class PipelineRunRecorder:
    def __init__(
        self,
        *,
        run_id: UUID | None,
        run_started_at: datetime,
        document_id: str,
        organization_id: str | None,
        user_id: str | None,
    ) -> None:
        self.run_id = run_id
        self.run_started_at = run_started_at
        self.document_id = document_id
        self.organization_id = organization_id
        self.user_id = user_id
        self._sequence = 0
        self._stage_started_at: dict[str, datetime] = {}
        self._stage_finalized: set[str] = set()

    @classmethod
    async def create(
        cls,
        *,
        document_id: str,
        organization_id: str | None,
        user_id: str | None,
        organization_uuid: UUID,
        document_uuid: UUID,
        pipeline_type: str,
        inputs: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> PipelineRunRecorder:
        run_started_at = datetime.now(UTC)
        run_id: UUID | None = None
        deps = current_deps()

        if settings.feature_enable_pipeline_explorer:
            try:
                async with deps.SessionLocal() as telemetry_session:
                    async with telemetry_session.begin():
                        run = await deps.pipeline_repository.create_pipeline_run(
                            telemetry_session,
                            organization_id=organization_uuid,
                            document_id=document_uuid,
                            pipeline_type=pipeline_type,
                            status="running",
                            started_at=run_started_at,
                            inputs=sanitize_pipeline_payload(inputs or {}),
                            config=sanitize_pipeline_payload(config or {}),
                        )
                    run_id = run.id
            except Exception as exc:
                deps.log_document_event(
                    event="document.pipeline.telemetry.failed",
                    document_id=document_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    error=str(exc),
                    telemetry_operation="create_run",
                )

        return cls(
            run_id=run_id,
            run_started_at=run_started_at,
            document_id=document_id,
            organization_id=organization_id,
            user_id=user_id,
        )

    @classmethod
    async def open_for_run(
        cls,
        existing_run_id: Any,
        *,
        document_id: str,
        organization_id: str | None,
        user_id: str | None,
        organization_uuid: UUID,
        document_uuid: UUID,
        pipeline_type: str,
        inputs: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> PipelineRunRecorder:
        """Resume ``existing_run_id`` when it is this document's run, else create one."""
        resumed = await cls._resume(
            existing_run_id,
            document_id=document_id,
            organization_id=organization_id,
            user_id=user_id,
            document_uuid=document_uuid,
        )
        if resumed is not None:
            return resumed
        return await cls.create(
            document_id=document_id,
            organization_id=organization_id,
            user_id=user_id,
            organization_uuid=organization_uuid,
            document_uuid=document_uuid,
            pipeline_type=pipeline_type,
            inputs=inputs,
            config=config,
        )

    @classmethod
    async def _resume(
        cls,
        existing_run_id: Any,
        *,
        document_id: str,
        organization_id: str | None,
        user_id: str | None,
        document_uuid: UUID,
    ) -> PipelineRunRecorder | None:
        if not existing_run_id or not settings.feature_enable_pipeline_explorer:
            return None
        try:
            run_uuid = UUID(str(existing_run_id))
        except ValueError:
            return None
        deps = current_deps()
        try:
            async with deps.SessionLocal() as session:
                row = (
                    await session.execute(
                        select(PipelineRun.started_at).where(
                            PipelineRun.id == run_uuid, PipelineRun.document_id == document_uuid
                        )
                    )
                ).first()
                if row is None:
                    return None
                last = (
                    await session.execute(
                        select(func.max(PipelineEvent.sequence)).where(
                            PipelineEvent.pipeline_run_id == run_uuid
                        )
                    )
                ).scalar_one_or_none()
        except Exception as exc:
            deps.log_document_event(
                event="document.pipeline.telemetry.failed",
                document_id=document_id,
                organization_id=organization_id,
                user_id=user_id,
                error=type(exc).__name__,
                telemetry_operation="resume_run",
            )
            return None
        started_at = row[0]
        if started_at is not None and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        recorder = cls(
            run_id=run_uuid,
            run_started_at=started_at or datetime.now(UTC),
            document_id=document_id,
            organization_id=organization_id,
            user_id=user_id,
        )
        recorder._sequence = int(last) + 1 if last is not None else 0
        return recorder

    async def emit_stage(
        self,
        *,
        stage: str,
        stage_status: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        logs: list[Any] | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        if self.run_id is None:
            return

        now = datetime.now(UTC)
        started_at: datetime | None = None
        completed_at: datetime | None = None
        duration_ms: int | None = None

        if stage_status == "started":
            self._stage_started_at[stage] = now
            started_at = now
        else:
            started_at = self._stage_started_at.get(stage, now)
            completed_at = now
            duration_ms = safe_duration_ms(started_at=started_at, ended_at=now)
            self._stage_finalized.add(stage)

        deps = current_deps()
        try:
            async with deps.SessionLocal() as telemetry_session:
                async with telemetry_session.begin():
                    await deps.pipeline_repository.create_pipeline_event(
                        telemetry_session,
                        pipeline_run_id=self.run_id,
                        sequence=self._sequence,
                        node_name=stage,
                        status=stage_status,
                        started_at=started_at,
                        completed_at=completed_at,
                        duration_ms=duration_ms,
                        inputs=sanitize_pipeline_payload(inputs or {}),
                        outputs=sanitize_pipeline_payload(outputs or {}),
                        config=sanitize_pipeline_payload(config or {}),
                        logs=sanitize_pipeline_payload(logs or []),
                        error_message=sanitize_pipeline_payload(error_message),
                        error_details=sanitize_pipeline_payload(error_details or {}),
                    )
                    self._sequence += 1
        except Exception as exc:
            deps.log_document_event(
                event="document.pipeline.telemetry.failed",
                document_id=self.document_id,
                organization_id=self.organization_id,
                user_id=self.user_id,
                error=str(exc),
                stage=stage,
                stage_status=stage_status,
                telemetry_operation="create_stage_event",
            )

    async def fail_stage_if_open(
        self,
        *,
        stage: str,
        error_message: str,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        if stage in self._stage_finalized:
            return
        await self.emit_stage(
            stage=stage,
            stage_status="failed",
            error_message=error_message,
            error_details=error_details or {},
        )

    async def finalize_run(
        self,
        *,
        status: str,
        outputs: dict[str, Any] | None = None,
        logs: list[Any] | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        if self.run_id is None:
            return
        completed_at = datetime.now(UTC)
        deps = current_deps()
        try:
            async with deps.SessionLocal() as telemetry_session:
                async with telemetry_session.begin():
                    await deps.pipeline_repository.update_pipeline_run(
                        telemetry_session,
                        pipeline_run_id=self.run_id,
                        status=status,
                        completed_at=completed_at,
                        duration_ms=safe_duration_ms(
                            started_at=self.run_started_at, ended_at=completed_at
                        ),
                        outputs=sanitize_pipeline_payload(outputs or {}),
                        logs=sanitize_pipeline_payload(logs or []),
                        error_message=sanitize_pipeline_payload(error_message),
                        error_details=sanitize_pipeline_payload(error_details or {}),
                    )
        except Exception as exc:
            deps.log_document_event(
                event="document.pipeline.telemetry.failed",
                document_id=self.document_id,
                organization_id=self.organization_id,
                user_id=self.user_id,
                error=str(exc),
                status=status,
                telemetry_operation="update_run",
            )
