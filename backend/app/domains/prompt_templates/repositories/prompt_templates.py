from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationRun, EvaluationSet
from app.models.prompt_template import PromptTemplate, PromptTemplateVersion


class PromptTemplateRepository:
    async def create_template(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        template_key: str,
        name: str,
        description: str | None,
        category: str,
        created_by_id: UUID | None,
    ) -> PromptTemplate:
        template = PromptTemplate(
            organization_id=organization_id,
            template_key=template_key,
            name=name,
            description=description,
            category=category,
            latest_version_number=1,
            active_version_number=None,
            created_by_id=created_by_id,
            updated_by_id=created_by_id,
        )
        session.add(template)
        await session.flush()
        await session.refresh(template)
        return template

    async def list_templates(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[PromptTemplate]:
        result = await session.execute(
            select(PromptTemplate)
            .where(PromptTemplate.organization_id == organization_id)
            .order_by(PromptTemplate.category.asc(), PromptTemplate.name.asc())
        )
        return list(result.scalars().all())

    async def count_templates(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(PromptTemplate.id)).where(
                PromptTemplate.organization_id == organization_id
            )
        )
        return int(result.scalar_one())

    async def get_template_by_key(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        template_key: str,
    ) -> PromptTemplate | None:
        result = await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.organization_id == organization_id,
                PromptTemplate.template_key == template_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_template_by_id(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        prompt_template_id: UUID,
    ) -> PromptTemplate | None:
        result = await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.organization_id == organization_id,
                PromptTemplate.id == prompt_template_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_version(
        self,
        session: AsyncSession,
        *,
        prompt_template_id: UUID,
        version_number: int,
        state: str,
        content: str,
        variables: list[dict[str, Any]],
        variable_schema: dict[str, Any],
        preview_context: dict[str, Any],
        change_note: str | None,
        source_version_number: int | None,
        created_by_id: UUID | None,
        reviewed_by_id: UUID | None = None,
        published_by_id: UUID | None = None,
        reviewed_at: datetime | None = None,
        published_at: datetime | None = None,
    ) -> PromptTemplateVersion:
        if state == "published" and published_at is None:
            published_at = datetime.now(UTC)
        version = PromptTemplateVersion(
            prompt_template_id=prompt_template_id,
            version_number=version_number,
            state=state,
            content=content,
            variables_json=variables,
            variable_schema_json=variable_schema,
            preview_context_json=preview_context,
            change_note=change_note,
            source_version_number=source_version_number,
            created_by_id=created_by_id,
            reviewed_by_id=reviewed_by_id,
            published_by_id=published_by_id,
            reviewed_at=reviewed_at,
            published_at=published_at,
        )
        session.add(version)
        await session.flush()
        await session.refresh(version)
        return version

    async def list_versions(
        self,
        session: AsyncSession,
        *,
        prompt_template_id: UUID,
    ) -> list[PromptTemplateVersion]:
        result = await session.execute(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.prompt_template_id == prompt_template_id)
            .order_by(PromptTemplateVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def get_version(
        self,
        session: AsyncSession,
        *,
        prompt_template_id: UUID,
        version_number: int,
    ) -> PromptTemplateVersion | None:
        result = await session.execute(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.prompt_template_id == prompt_template_id,
                PromptTemplateVersion.version_number == version_number,
            )
        )
        return result.scalar_one_or_none()

    async def get_version_by_id(
        self,
        session: AsyncSession,
        *,
        version_id: UUID,
    ) -> PromptTemplateVersion | None:
        result = await session.execute(
            select(PromptTemplateVersion).where(PromptTemplateVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_active_version(
        self,
        session: AsyncSession,
        *,
        template: PromptTemplate,
    ) -> PromptTemplateVersion | None:
        if template.active_version_number is None:
            return None
        return await self.get_version(
            session,
            prompt_template_id=template.id,
            version_number=template.active_version_number,
        )

    async def update_template_version_counters(
        self,
        session: AsyncSession,
        *,
        template: PromptTemplate,
        latest_version_number: int | None = None,
        active_version_number: int | None = None,
        updated_by_id: UUID | None = None,
    ) -> PromptTemplate:
        if latest_version_number is not None:
            template.latest_version_number = latest_version_number
        if active_version_number is not None:
            template.active_version_number = active_version_number
        if updated_by_id is not None:
            template.updated_by_id = updated_by_id
        await session.flush()
        await session.refresh(template)
        return template

    async def update_version(
        self,
        session: AsyncSession,
        *,
        version: PromptTemplateVersion,
        content: str | None = None,
        variables: list[dict[str, Any]] | None = None,
        variable_schema: dict[str, Any] | None = None,
        preview_context: dict[str, Any] | None = None,
        change_note: str | None = None,
    ) -> PromptTemplateVersion:
        if content is not None:
            version.content = content
        if variables is not None:
            version.variables_json = variables
        if variable_schema is not None:
            version.variable_schema_json = variable_schema
        if preview_context is not None:
            version.preview_context_json = preview_context
        if change_note is not None:
            version.change_note = change_note
        await session.flush()
        await session.refresh(version)
        return version

    async def set_version_state(
        self,
        session: AsyncSession,
        *,
        version: PromptTemplateVersion,
        state: str,
        reviewed_by_id: UUID | None = None,
        published_by_id: UUID | None = None,
    ) -> PromptTemplateVersion:
        now = datetime.now(UTC)
        version.state = state
        if state == "review":
            version.reviewed_by_id = reviewed_by_id
            version.reviewed_at = now
        if state == "published":
            version.published_by_id = published_by_id
            version.published_at = now
        await session.flush()
        await session.refresh(version)
        return version

    async def list_evaluation_runs_for_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        prompt_template_version_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[EvaluationRun]:
        result = await session.execute(
            select(EvaluationRun)
            .join(EvaluationSet, EvaluationSet.id == EvaluationRun.evaluation_set_id)
            .where(
                EvaluationSet.organization_id == organization_id,
                EvaluationRun.prompt_template_version_id == prompt_template_version_id,
            )
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_evaluation_runs_for_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        prompt_template_version_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(EvaluationRun.id))
            .join(EvaluationSet, EvaluationSet.id == EvaluationRun.evaluation_set_id)
            .where(
                EvaluationSet.organization_id == organization_id,
                EvaluationRun.prompt_template_version_id == prompt_template_version_id,
            )
        )
        return int(result.scalar_one())
