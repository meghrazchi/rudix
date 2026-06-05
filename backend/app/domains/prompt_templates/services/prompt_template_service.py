from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.prompt_templates.repositories.prompt_templates import PromptTemplateRepository
from app.domains.prompt_templates.services.defaults import (
    DEFAULT_PROMPT_TEMPLATE_BY_KEY,
    DEFAULT_PROMPT_TEMPLATES,
    DEFAULT_PUBLISHED_STATE,
)
from app.domains.prompt_templates.services.rendering import (
    PromptTemplateValidationError,
    build_schema_from_variables,
    render_prompt_template,
    validate_template_definition,
)
from app.models.enums import PromptTemplateVersionState
from app.models.prompt_template import PromptTemplate, PromptTemplateVersion


class PromptTemplateService:
    def __init__(self, repository: PromptTemplateRepository | None = None) -> None:
        self._repository = repository or PromptTemplateRepository()

    async def ensure_default_templates(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        created_by_id: UUID | None = None,
    ) -> list[PromptTemplate]:
        templates: list[PromptTemplate] = []
        for definition in DEFAULT_PROMPT_TEMPLATES:
            existing = await self._repository.get_template_by_key(
                session,
                organization_id=organization_id,
                template_key=definition.key.value,
            )
            if existing is not None:
                templates.append(existing)
                continue

            template = await self._repository.create_template(
                session,
                organization_id=organization_id,
                template_key=definition.key.value,
                name=definition.name,
                description=definition.description,
                category=definition.category,
                created_by_id=created_by_id,
            )
            await self._repository.create_version(
                session,
                prompt_template_id=template.id,
                version_number=1,
                state=DEFAULT_PUBLISHED_STATE,
                content=definition.content,
                variables=definition.variables,
                variable_schema=definition.variable_schema,
                preview_context=definition.preview_context,
                change_note="System default",
                source_version_number=None,
                created_by_id=created_by_id,
                published_by_id=created_by_id,
            )
            template = await self._repository.update_template_version_counters(
                session,
                template=template,
                latest_version_number=1,
                active_version_number=1,
                updated_by_id=created_by_id,
            )
            templates.append(template)
        return templates

    async def resolve_active_version(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        template_key: str,
    ) -> PromptTemplateVersion:
        await self.ensure_default_templates(session, organization_id=organization_id)
        template = await self._repository.get_template_by_key(
            session,
            organization_id=organization_id,
            template_key=template_key,
        )
        if template is None:
            raise PromptTemplateValidationError("Prompt template not found")
        version = await self._repository.get_active_version(session, template=template)
        if version is None or version.state != PromptTemplateVersionState.published.value:
            raise PromptTemplateValidationError("Prompt template has no published version")
        return version

    async def create_draft(
        self,
        session: AsyncSession,
        *,
        template: PromptTemplate,
        source: PromptTemplateVersion | None,
        created_by_id: UUID | None,
        change_note: str | None,
    ) -> PromptTemplateVersion:
        base = source
        if base is None:
            base = await self._repository.get_active_version(session, template=template)
        if base is None:
            raise PromptTemplateValidationError("Cannot create draft without a source version")

        next_version_number = template.latest_version_number + 1
        version = await self._repository.create_version(
            session,
            prompt_template_id=template.id,
            version_number=next_version_number,
            state=PromptTemplateVersionState.draft.value,
            content=base.content,
            variables=list(base.variables_json or []),
            variable_schema=dict(base.variable_schema_json or {}),
            preview_context=dict(base.preview_context_json or {}),
            change_note=change_note,
            source_version_number=base.version_number,
            created_by_id=created_by_id,
        )
        await self._repository.update_template_version_counters(
            session,
            template=template,
            latest_version_number=next_version_number,
            updated_by_id=created_by_id,
        )
        return version

    async def update_mutable_version(
        self,
        session: AsyncSession,
        *,
        version: PromptTemplateVersion,
        content: str | None,
        variables: list[dict[str, Any]] | None,
        variable_schema: dict[str, Any] | None,
        preview_context: dict[str, Any] | None,
        change_note: str | None,
    ) -> PromptTemplateVersion:
        if version.state == PromptTemplateVersionState.published.value:
            raise PromptTemplateValidationError("Published prompt versions cannot be edited")

        next_content = content if content is not None else version.content
        next_variables = variables if variables is not None else list(version.variables_json or [])
        next_schema = (
            variable_schema
            if variable_schema is not None
            else dict(version.variable_schema_json or {})
        )
        if not next_schema:
            next_schema = build_schema_from_variables(next_variables)
        next_preview_context = (
            preview_context
            if preview_context is not None
            else dict(version.preview_context_json or {})
        )
        validate_template_definition(
            content=next_content,
            variables=next_variables,
            variable_schema=next_schema,
            preview_context=next_preview_context,
        )
        return await self._repository.update_version(
            session,
            version=version,
            content=next_content,
            variables=next_variables,
            variable_schema=next_schema,
            preview_context=next_preview_context,
            change_note=change_note,
        )

    async def submit_for_review(
        self,
        session: AsyncSession,
        *,
        version: PromptTemplateVersion,
        reviewed_by_id: UUID | None,
    ) -> PromptTemplateVersion:
        if version.state == PromptTemplateVersionState.published.value:
            raise PromptTemplateValidationError("Published prompt versions cannot be changed")
        validate_template_definition(
            content=version.content,
            variables=list(version.variables_json or []),
            variable_schema=dict(version.variable_schema_json or {}),
            preview_context=dict(version.preview_context_json or {}),
        )
        return await self._repository.set_version_state(
            session,
            version=version,
            state=PromptTemplateVersionState.review.value,
            reviewed_by_id=reviewed_by_id,
        )

    async def publish_version(
        self,
        session: AsyncSession,
        *,
        template: PromptTemplate,
        version: PromptTemplateVersion,
        published_by_id: UUID | None,
    ) -> PromptTemplateVersion:
        if version.state == PromptTemplateVersionState.published.value:
            raise PromptTemplateValidationError("Prompt version is already published")
        validate_template_definition(
            content=version.content,
            variables=list(version.variables_json or []),
            variable_schema=dict(version.variable_schema_json or {}),
            preview_context=dict(version.preview_context_json or {}),
        )
        version = await self._repository.set_version_state(
            session,
            version=version,
            state=PromptTemplateVersionState.published.value,
            published_by_id=published_by_id,
        )
        await self._repository.update_template_version_counters(
            session,
            template=template,
            active_version_number=version.version_number,
            updated_by_id=published_by_id,
        )
        return version

    async def rollback_to_published_version(
        self,
        session: AsyncSession,
        *,
        template: PromptTemplate,
        source: PromptTemplateVersion,
        user_id: UUID | None,
        change_note: str | None,
    ) -> PromptTemplateVersion:
        if source.state != PromptTemplateVersionState.published.value:
            raise PromptTemplateValidationError("Rollback target must be a published version")
        if template.active_version_number == source.version_number:
            raise PromptTemplateValidationError("Template is already using the requested version")
        next_version_number = template.latest_version_number + 1
        version = await self._repository.create_version(
            session,
            prompt_template_id=template.id,
            version_number=next_version_number,
            state=PromptTemplateVersionState.published.value,
            content=source.content,
            variables=list(source.variables_json or []),
            variable_schema=dict(source.variable_schema_json or {}),
            preview_context=dict(source.preview_context_json or {}),
            change_note=change_note or f"Rollback to version {source.version_number}",
            source_version_number=source.version_number,
            created_by_id=user_id,
            published_by_id=user_id,
        )
        await self._repository.update_template_version_counters(
            session,
            template=template,
            latest_version_number=next_version_number,
            active_version_number=next_version_number,
            updated_by_id=user_id,
        )
        return version

    def render_version(
        self,
        *,
        version: PromptTemplateVersion,
        context: dict[str, Any] | None = None,
    ) -> str:
        variables = list(version.variables_json or [])
        render_context = dict(version.preview_context_json or {})
        for variable in variables:
            name = str(variable.get("name") or "")
            if name and variable.get("default") is not None and name not in render_context:
                render_context[name] = variable["default"]
        if context:
            render_context.update(context)
        return render_prompt_template(version.content, render_context)

    def default_definition_for_key(self, template_key: str) -> Any | None:
        return DEFAULT_PROMPT_TEMPLATE_BY_KEY.get(template_key)
