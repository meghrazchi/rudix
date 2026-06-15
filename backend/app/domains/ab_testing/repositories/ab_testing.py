from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ab_experiment import (
    AbExperiment,
    AbExperimentRun,
    AbExperimentVariant,
    AbExperimentVariantRun,
)


class AbTestingRepository:
    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    async def create_experiment(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None,
        evaluation_set_id: UUID,
        metrics_config: dict,
        created_by_id: UUID | None,
    ) -> AbExperiment:
        experiment = AbExperiment(
            organization_id=organization_id,
            name=name,
            description=description,
            evaluation_set_id=evaluation_set_id,
            metrics_config=metrics_config,
            created_by_id=created_by_id,
        )
        db.add(experiment)
        await db.flush()
        return experiment

    async def get_experiment(
        self,
        db: AsyncSession,
        *,
        experiment_id: UUID,
        organization_id: UUID,
    ) -> AbExperiment | None:
        stmt = (
            select(AbExperiment)
            .options(selectinload(AbExperiment.variants))
            .where(
                AbExperiment.id == experiment_id,
                AbExperiment.organization_id == organization_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_experiments(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AbExperiment]:
        stmt = (
            select(AbExperiment)
            .options(selectinload(AbExperiment.variants))
            .where(AbExperiment.organization_id == organization_id)
            .order_by(AbExperiment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_experiments(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        stmt = select(func.count(AbExperiment.id)).where(
            AbExperiment.organization_id == organization_id
        )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def update_experiment(
        self,
        db: AsyncSession,
        experiment: AbExperiment,
        *,
        name: str | None = None,
        description: str | None = None,
        metrics_config: dict | None = None,
        status: str | None = None,
    ) -> AbExperiment:
        if name is not None:
            experiment.name = name
        if description is not None:
            experiment.description = description
        if metrics_config is not None:
            experiment.metrics_config = metrics_config
        if status is not None:
            experiment.status = status
        await db.flush()
        return experiment

    async def delete_experiment(
        self,
        db: AsyncSession,
        experiment: AbExperiment,
    ) -> None:
        await db.delete(experiment)
        await db.flush()

    # ------------------------------------------------------------------
    # Variants
    # ------------------------------------------------------------------

    async def create_variant(
        self,
        db: AsyncSession,
        *,
        experiment_id: UUID,
        label: str,
        description: str | None,
        rag_profile_id: UUID | None,
        rag_profile_version: int | None,
        prompt_template_version_id: UUID | None,
        model_profile_key: str | None,
        config_snapshot: dict,
    ) -> AbExperimentVariant:
        variant = AbExperimentVariant(
            experiment_id=experiment_id,
            label=label,
            description=description,
            rag_profile_id=rag_profile_id,
            rag_profile_version=rag_profile_version,
            prompt_template_version_id=prompt_template_version_id,
            model_profile_key=model_profile_key,
            config_snapshot=config_snapshot,
        )
        db.add(variant)
        await db.flush()
        return variant

    async def get_variant(
        self,
        db: AsyncSession,
        *,
        variant_id: UUID,
        experiment_id: UUID,
    ) -> AbExperimentVariant | None:
        stmt = select(AbExperimentVariant).where(
            AbExperimentVariant.id == variant_id,
            AbExperimentVariant.experiment_id == experiment_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_variant(
        self,
        db: AsyncSession,
        variant: AbExperimentVariant,
    ) -> None:
        await db.delete(variant)
        await db.flush()

    async def set_variant_approval(
        self,
        db: AsyncSession,
        variant: AbExperimentVariant,
        *,
        approval_status: str,
        approved_by_id: UUID,
        approval_note: str | None,
        approved_at: object,
    ) -> AbExperimentVariant:
        variant.approval_status = approval_status
        variant.approved_by_id = approved_by_id
        variant.approval_note = approval_note
        variant.approved_at = approved_at  # type: ignore[assignment]
        await db.flush()
        return variant

    # ------------------------------------------------------------------
    # Experiment runs
    # ------------------------------------------------------------------

    async def create_experiment_run(
        self,
        db: AsyncSession,
        *,
        experiment_id: UUID,
        status: str,
        triggered_by_id: UUID | None,
        started_at: object,
    ) -> AbExperimentRun:
        run = AbExperimentRun(
            experiment_id=experiment_id,
            status=status,
            triggered_by_id=triggered_by_id,
            started_at=started_at,  # type: ignore[arg-type]
        )
        db.add(run)
        await db.flush()
        return run

    async def get_experiment_run(
        self,
        db: AsyncSession,
        *,
        run_id: UUID,
        organization_id: UUID,
    ) -> AbExperimentRun | None:
        stmt = (
            select(AbExperimentRun)
            .join(AbExperiment, AbExperimentRun.experiment_id == AbExperiment.id)
            .options(selectinload(AbExperimentRun.variant_runs))
            .where(
                AbExperimentRun.id == run_id,
                AbExperiment.organization_id == organization_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_experiment_runs(
        self,
        db: AsyncSession,
        *,
        experiment_id: UUID,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AbExperimentRun]:
        stmt = (
            select(AbExperimentRun)
            .join(AbExperiment, AbExperimentRun.experiment_id == AbExperiment.id)
            .options(selectinload(AbExperimentRun.variant_runs))
            .where(
                AbExperimentRun.experiment_id == experiment_id,
                AbExperiment.organization_id == organization_id,
            )
            .order_by(AbExperimentRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_experiment_runs(
        self,
        db: AsyncSession,
        *,
        experiment_id: UUID,
        organization_id: UUID,
    ) -> int:
        stmt = (
            select(func.count(AbExperimentRun.id))
            .join(AbExperiment, AbExperimentRun.experiment_id == AbExperiment.id)
            .where(
                AbExperimentRun.experiment_id == experiment_id,
                AbExperiment.organization_id == organization_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def update_experiment_run(
        self,
        db: AsyncSession,
        run: AbExperimentRun,
        *,
        status: str | None = None,
        comparison_report: dict | None = None,
        completed_at: object = ...,  # type: ignore[assignment]
    ) -> AbExperimentRun:
        if status is not None:
            run.status = status
        if comparison_report is not None:
            run.comparison_report = comparison_report
        if completed_at is not ...:
            run.completed_at = completed_at  # type: ignore[assignment]
        await db.flush()
        return run

    # ------------------------------------------------------------------
    # Variant runs
    # ------------------------------------------------------------------

    async def create_variant_run(
        self,
        db: AsyncSession,
        *,
        experiment_run_id: UUID,
        variant_id: UUID,
        evaluation_run_id: UUID | None,
        status: str,
    ) -> AbExperimentVariantRun:
        vr = AbExperimentVariantRun(
            experiment_run_id=experiment_run_id,
            variant_id=variant_id,
            evaluation_run_id=evaluation_run_id,
            status=status,
        )
        db.add(vr)
        await db.flush()
        return vr

    async def update_variant_run(
        self,
        db: AsyncSession,
        vr: AbExperimentVariantRun,
        *,
        status: str | None = None,
        evaluation_run_id: UUID | None = None,
        metrics_summary: dict | None = None,
        error_detail: str | None = None,
    ) -> AbExperimentVariantRun:
        if status is not None:
            vr.status = status
        if evaluation_run_id is not None:
            vr.evaluation_run_id = evaluation_run_id
        if metrics_summary is not None:
            vr.metrics_summary = metrics_summary
        if error_detail is not None:
            vr.error_detail = error_detail
        await db.flush()
        return vr
