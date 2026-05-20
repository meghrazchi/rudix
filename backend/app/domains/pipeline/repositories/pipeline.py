from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PipelineEvent, PipelineRun


class PipelineRepository:
    async def create_pipeline_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        pipeline_type: str,
        status: str = "queued",
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        inputs: dict | None = None,
        outputs: dict | None = None,
        config: dict | None = None,
        logs: list | None = None,
        error_message: str | None = None,
        error_details: dict | None = None,
        document_id: UUID | None = None,
        chat_message_id: UUID | None = None,
        evaluation_run_id: UUID | None = None,
    ) -> PipelineRun:
        pipeline_run = PipelineRun(
            organization_id=organization_id,
            pipeline_type=pipeline_type,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            inputs_json=inputs or {},
            outputs_json=outputs or {},
            config_json=config or {},
            logs_json=logs or [],
            error_message=error_message,
            error_details_json=error_details or {},
            document_id=document_id,
            chat_message_id=chat_message_id,
            evaluation_run_id=evaluation_run_id,
        )
        session.add(pipeline_run)
        await session.flush()
        await session.refresh(pipeline_run)
        return pipeline_run

    async def get_pipeline_run(self, session: AsyncSession, *, pipeline_run_id: UUID) -> PipelineRun | None:
        result = await session.execute(select(PipelineRun).where(PipelineRun.id == pipeline_run_id))
        return result.scalar_one_or_none()

    async def get_pipeline_run_for_organization(
        self,
        session: AsyncSession,
        *,
        pipeline_run_id: UUID,
        organization_id: UUID,
    ) -> PipelineRun | None:
        result = await session.execute(
            select(PipelineRun).where(
                PipelineRun.id == pipeline_run_id,
                PipelineRun.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_pipeline_events_for_run(
        self,
        session: AsyncSession,
        *,
        pipeline_run_id: UUID,
    ) -> list[PipelineEvent]:
        result = await session.execute(
            select(PipelineEvent)
            .where(PipelineEvent.pipeline_run_id == pipeline_run_id)
            .order_by(PipelineEvent.sequence.asc())
        )
        return list(result.scalars().all())

    async def list_pipeline_events_for_node(
        self,
        session: AsyncSession,
        *,
        pipeline_run_id: UUID,
        node_name: str,
    ) -> list[PipelineEvent]:
        result = await session.execute(
            select(PipelineEvent)
            .where(
                PipelineEvent.pipeline_run_id == pipeline_run_id,
                PipelineEvent.node_name == node_name,
            )
            .order_by(PipelineEvent.sequence.asc())
        )
        return list(result.scalars().all())

    async def resolve_latest_pipeline_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        pipeline_types: list[str] | None = None,
        document_id: UUID | None = None,
        chat_message_id: UUID | None = None,
        evaluation_run_id: UUID | None = None,
    ) -> PipelineRun | None:
        query = select(PipelineRun).where(PipelineRun.organization_id == organization_id)
        if pipeline_types:
            query = query.where(PipelineRun.pipeline_type.in_(pipeline_types))
        if document_id is not None:
            query = query.where(PipelineRun.document_id == document_id)
        if chat_message_id is not None:
            query = query.where(PipelineRun.chat_message_id == chat_message_id)
        if evaluation_run_id is not None:
            query = query.where(PipelineRun.evaluation_run_id == evaluation_run_id)

        result = await session.execute(
            query.order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def update_pipeline_run(
        self,
        session: AsyncSession,
        *,
        pipeline_run_id: UUID,
        status: str | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        outputs: dict | None = None,
        logs: list | None = None,
        error_message: str | None = None,
        error_details: dict | None = None,
    ) -> PipelineRun | None:
        pipeline_run = await self.get_pipeline_run(session, pipeline_run_id=pipeline_run_id)
        if pipeline_run is None:
            return None
        if status is not None:
            pipeline_run.status = status
        if completed_at is not None:
            pipeline_run.completed_at = completed_at
        if duration_ms is not None:
            pipeline_run.duration_ms = duration_ms
        if outputs is not None:
            pipeline_run.outputs_json = outputs
        if logs is not None:
            pipeline_run.logs_json = logs
        if error_message is not None:
            pipeline_run.error_message = error_message
        if error_details is not None:
            pipeline_run.error_details_json = error_details
        await session.flush()
        await session.refresh(pipeline_run)
        return pipeline_run

    async def create_pipeline_event(
        self,
        session: AsyncSession,
        *,
        pipeline_run_id: UUID,
        sequence: int,
        node_name: str,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        inputs: dict | None = None,
        outputs: dict | None = None,
        config: dict | None = None,
        logs: list | None = None,
        error_message: str | None = None,
        error_details: dict | None = None,
    ) -> PipelineEvent:
        pipeline_event = PipelineEvent(
            pipeline_run_id=pipeline_run_id,
            sequence=sequence,
            node_name=node_name,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            inputs_json=inputs or {},
            outputs_json=outputs or {},
            config_json=config or {},
            logs_json=logs or [],
            error_message=error_message,
            error_details_json=error_details or {},
        )
        session.add(pipeline_event)
        await session.flush()
        await session.refresh(pipeline_event)
        return pipeline_event
