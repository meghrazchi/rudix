from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quality_gate import QualityGate, QualityGateRun


class QualityGateRepository:
    async def create_gate(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None,
        thresholds: dict,
        baseline_evaluation_run_id: UUID | None,
        baseline_safety_run_id: UUID | None,
        created_by_id: UUID | None,
    ) -> QualityGate:
        gate = QualityGate(
            organization_id=organization_id,
            name=name,
            description=description,
            thresholds=thresholds,
            baseline_evaluation_run_id=baseline_evaluation_run_id,
            baseline_safety_run_id=baseline_safety_run_id,
            created_by_id=created_by_id,
        )
        db_session.add(gate)
        await db_session.flush()
        return gate

    async def get_gate(
        self,
        db_session: AsyncSession,
        *,
        gate_id: UUID,
        organization_id: UUID,
    ) -> QualityGate | None:
        stmt = select(QualityGate).where(
            QualityGate.id == gate_id,
            QualityGate.organization_id == organization_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_gates(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QualityGate]:
        stmt = (
            select(QualityGate)
            .where(QualityGate.organization_id == organization_id)
            .order_by(QualityGate.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_gates(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        stmt = select(func.count(QualityGate.id)).where(
            QualityGate.organization_id == organization_id
        )
        result = await db_session.execute(stmt)
        return result.scalar_one()

    async def update_gate(
        self,
        db_session: AsyncSession,
        gate: QualityGate,
        *,
        name: str | None = None,
        description: str | None = None,
        thresholds: dict | None = None,
        baseline_evaluation_run_id: UUID | None | str = ...,  # type: ignore[assignment]
        baseline_safety_run_id: UUID | None | str = ...,  # type: ignore[assignment]
    ) -> QualityGate:
        if name is not None:
            gate.name = name
        if description is not None:
            gate.description = description
        if thresholds is not None:
            gate.thresholds = thresholds
        if baseline_evaluation_run_id is not ...:
            gate.baseline_evaluation_run_id = baseline_evaluation_run_id  # type: ignore[assignment]
        if baseline_safety_run_id is not ...:
            gate.baseline_safety_run_id = baseline_safety_run_id  # type: ignore[assignment]
        await db_session.flush()
        return gate

    async def delete_gate(
        self,
        db_session: AsyncSession,
        gate: QualityGate,
    ) -> None:
        await db_session.delete(gate)
        await db_session.flush()

    # ------------------------------------------------------------------
    # Gate runs
    # ------------------------------------------------------------------

    async def create_gate_run(
        self,
        db_session: AsyncSession,
        *,
        quality_gate_id: UUID,
        evaluation_run_id: UUID | None,
        safety_eval_run_id: UUID | None,
        verdict: str,
        report: dict,
        triggered_by_id: UUID | None,
    ) -> QualityGateRun:
        run = QualityGateRun(
            quality_gate_id=quality_gate_id,
            evaluation_run_id=evaluation_run_id,
            safety_eval_run_id=safety_eval_run_id,
            verdict=verdict,
            report=report,
            triggered_by_id=triggered_by_id,
        )
        db_session.add(run)
        await db_session.flush()
        return run

    async def get_gate_run(
        self,
        db_session: AsyncSession,
        *,
        gate_run_id: UUID,
        organization_id: UUID,
    ) -> QualityGateRun | None:
        stmt = (
            select(QualityGateRun)
            .join(QualityGate, QualityGateRun.quality_gate_id == QualityGate.id)
            .where(
                QualityGateRun.id == gate_run_id,
                QualityGate.organization_id == organization_id,
            )
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_gate_runs(
        self,
        db_session: AsyncSession,
        *,
        quality_gate_id: UUID,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QualityGateRun]:
        stmt = (
            select(QualityGateRun)
            .join(QualityGate, QualityGateRun.quality_gate_id == QualityGate.id)
            .where(
                QualityGateRun.quality_gate_id == quality_gate_id,
                QualityGate.organization_id == organization_id,
            )
            .order_by(QualityGateRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_gate_runs(
        self,
        db_session: AsyncSession,
        *,
        quality_gate_id: UUID,
        organization_id: UUID,
    ) -> int:
        stmt = (
            select(func.count(QualityGateRun.id))
            .join(QualityGate, QualityGateRun.quality_gate_id == QualityGate.id)
            .where(
                QualityGateRun.quality_gate_id == quality_gate_id,
                QualityGate.organization_id == organization_id,
            )
        )
        result = await db_session.execute(stmt)
        return result.scalar_one()

    async def apply_override(
        self,
        db_session: AsyncSession,
        gate_run: QualityGateRun,
        *,
        overridden_by_id: UUID,
        override_reason: str,
        overridden_at: object,
    ) -> QualityGateRun:
        from app.models.enums import QualityGateVerdict

        gate_run.verdict = QualityGateVerdict.overridden.value
        gate_run.overridden_by_id = overridden_by_id
        gate_run.override_reason = override_reason
        gate_run.overridden_at = overridden_at  # type: ignore[assignment]
        report = dict(gate_run.report or {})
        report["overridden"] = True
        report["override_reason"] = override_reason
        report["overridden_by_id"] = str(overridden_by_id)
        gate_run.report = report
        await db_session.flush()
        return gate_run
