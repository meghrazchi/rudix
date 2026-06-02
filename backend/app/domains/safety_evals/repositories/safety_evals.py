from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safety_eval import SafetyEvalCase, SafetyEvalResult, SafetyEvalRun


class SafetyEvalRepository:
    # ------------------------------------------------------------------
    # Cases
    # ------------------------------------------------------------------

    async def create_case(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str,
        violation_type: str,
        name: str,
        prompt_text: str,
        severity: str = "high",
        description: str | None = None,
        metadata: dict | None = None,
    ) -> SafetyEvalCase:
        case = SafetyEvalCase(
            organization_id=organization_id,
            suite_name=suite_name,
            violation_type=violation_type,
            name=name,
            prompt_text=prompt_text,
            severity=severity,
            description=description,
            metadata_json=metadata or {},
        )
        session.add(case)
        await session.flush()
        await session.refresh(case)
        return case

    async def get_case_by_id(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        organization_id: UUID,
    ) -> SafetyEvalCase | None:
        result = await session.execute(
            select(SafetyEvalCase).where(
                SafetyEvalCase.id == case_id,
                SafetyEvalCase.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_cases(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str | None = None,
        violation_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SafetyEvalCase]:
        stmt = select(SafetyEvalCase).where(
            SafetyEvalCase.organization_id == organization_id
        )
        if suite_name is not None:
            stmt = stmt.where(SafetyEvalCase.suite_name == suite_name)
        if violation_type is not None:
            stmt = stmt.where(SafetyEvalCase.violation_type == violation_type)
        stmt = stmt.order_by(SafetyEvalCase.suite_name, SafetyEvalCase.created_at)
        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_cases_for_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str | None = None,
    ) -> list[SafetyEvalCase]:
        stmt = select(SafetyEvalCase).where(
            SafetyEvalCase.organization_id == organization_id
        )
        if suite_name is not None:
            stmt = stmt.where(SafetyEvalCase.suite_name == suite_name)
        stmt = stmt.order_by(SafetyEvalCase.suite_name, SafetyEvalCase.created_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count_cases(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str | None = None,
        violation_type: str | None = None,
    ) -> int:
        stmt = select(func.count(SafetyEvalCase.id)).where(
            SafetyEvalCase.organization_id == organization_id
        )
        if suite_name is not None:
            stmt = stmt.where(SafetyEvalCase.suite_name == suite_name)
        if violation_type is not None:
            stmt = stmt.where(SafetyEvalCase.violation_type == violation_type)
        result = await session.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def create_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str | None = None,
        config: dict | None = None,
    ) -> SafetyEvalRun:
        run = SafetyEvalRun(
            organization_id=organization_id,
            suite_name=suite_name,
            status="queued",
            config=config or {},
            summary={},
        )
        session.add(run)
        await session.flush()
        await session.refresh(run)
        return run

    async def get_run_by_id(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        organization_id: UUID,
    ) -> SafetyEvalRun | None:
        result = await session.execute(
            select(SafetyEvalRun).where(
                SafetyEvalRun.id == run_id,
                SafetyEvalRun.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SafetyEvalRun]:
        stmt = select(SafetyEvalRun).where(
            SafetyEvalRun.organization_id == organization_id
        )
        if suite_name is not None:
            stmt = stmt.where(SafetyEvalRun.suite_name == suite_name)
        stmt = stmt.order_by(SafetyEvalRun.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count_runs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str | None = None,
    ) -> int:
        stmt = select(func.count(SafetyEvalRun.id)).where(
            SafetyEvalRun.organization_id == organization_id
        )
        if suite_name is not None:
            stmt = stmt.where(SafetyEvalRun.suite_name == suite_name)
        result = await session.execute(stmt)
        return result.scalar_one()

    async def update_run_status(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        status: str,
        mark_started: bool = False,
        mark_completed: bool = False,
        pass_count: int | None = None,
        fail_count: int | None = None,
        total_count: int | None = None,
        summary: dict | None = None,
    ) -> SafetyEvalRun | None:
        values: dict = {"status": status}
        if mark_started:
            values["started_at"] = datetime.now(tz=UTC)
        if mark_completed:
            values["completed_at"] = datetime.now(tz=UTC)
        if pass_count is not None:
            values["pass_count"] = pass_count
        if fail_count is not None:
            values["fail_count"] = fail_count
        if total_count is not None:
            values["total_count"] = total_count
        if summary is not None:
            values["summary"] = summary
        stmt = (
            update(SafetyEvalRun)
            .where(SafetyEvalRun.id == run_id)
            .values(**values)
            .returning(SafetyEvalRun)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_completed_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        suite_name: str | None = None,
        before_run_id: UUID | None = None,
    ) -> SafetyEvalRun | None:
        stmt = select(SafetyEvalRun).where(
            SafetyEvalRun.organization_id == organization_id,
            SafetyEvalRun.status == "completed",
        )
        if suite_name is not None:
            stmt = stmt.where(SafetyEvalRun.suite_name == suite_name)
        if before_run_id is not None:
            stmt = stmt.where(SafetyEvalRun.id != before_run_id)
        stmt = stmt.order_by(SafetyEvalRun.completed_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    async def create_result(
        self,
        session: AsyncSession,
        *,
        safety_eval_run_id: UUID,
        safety_eval_case_id: UUID,
        passed: bool,
        violation_detected: bool,
        violation_type: str | None = None,
        score: float | None = None,
        latency_ms: int | None = None,
        details: dict | None = None,
    ) -> SafetyEvalResult:
        result = SafetyEvalResult(
            safety_eval_run_id=safety_eval_run_id,
            safety_eval_case_id=safety_eval_case_id,
            passed=passed,
            violation_detected=violation_detected,
            violation_type=violation_type,
            score=score,
            latency_ms=latency_ms,
            details=details or {},
        )
        session.add(result)
        await session.flush()
        await session.refresh(result)
        return result

    async def list_results_for_run(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        limit: int = 200,
        offset: int = 0,
    ) -> list[SafetyEvalResult]:
        stmt = (
            select(SafetyEvalResult)
            .where(SafetyEvalResult.safety_eval_run_id == run_id)
            .order_by(SafetyEvalResult.created_at)
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count_results_for_run(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
    ) -> int:
        stmt = select(func.count(SafetyEvalResult.id)).where(
            SafetyEvalResult.safety_eval_run_id == run_id
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def delete_results_for_run(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
    ) -> int:
        from sqlalchemy import delete as sql_delete

        stmt = sql_delete(SafetyEvalResult).where(
            SafetyEvalResult.safety_eval_run_id == run_id
        )
        result = await session.execute(stmt)
        return result.rowcount
