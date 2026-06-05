from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.prompt_templates.repositories.prompt_templates import PromptTemplateRepository
from app.domains.prompt_templates.schemas.prompt_templates import (
    CreatePromptTemplateDraftRequest,
    PromptTemplateDetailResponse,
    PromptTemplateEvalResultListResponse,
    PromptTemplateEvalResultResponse,
    PromptTemplateListResponse,
    PromptTemplatePreviewRequest,
    PromptTemplatePreviewResponse,
    PromptTemplateResponse,
    PromptTemplateVersionListResponse,
    PromptTemplateVersionResponse,
    PublishPromptTemplateVersionRequest,
    RollbackPromptTemplateRequest,
    UpdatePromptTemplateVersionRequest,
    validate_prompt_template_key,
)
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.domains.prompt_templates.services.rendering import (
    PromptTemplateValidationError,
    build_schema_from_variables,
    render_prompt_template,
    validate_template_definition,
)
from app.models.enums import OrganizationRole, PromptTemplateVersionState
from app.models.evaluation import EvaluationRun
from app.models.prompt_template import PromptTemplate, PromptTemplateVersion

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])

_repository = PromptTemplateRepository()
_service = PromptTemplateService(_repository)
_audit_service = AuditLogService()

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user context",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _safe_validation_error(
    exc: PromptTemplateValidationError, *, status_code: int
) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


async def _get_template_or_404(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    template_key: str,
) -> PromptTemplate:
    try:
        normalized_key = validate_prompt_template_key(template_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        ) from exc
    await _service.ensure_default_templates(db_session, organization_id=organization_id)
    template = await _repository.get_template_by_key(
        db_session,
        organization_id=organization_id,
        template_key=normalized_key,
    )
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        )
    return template


async def _get_version_or_404(
    db_session: AsyncSession,
    *,
    template: PromptTemplate,
    version_number: int,
) -> PromptTemplateVersion:
    version = await _repository.get_version(
        db_session,
        prompt_template_id=template.id,
        version_number=version_number,
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template version not found",
        )
    return version


def _version_to_response(
    *,
    template: PromptTemplate,
    version: PromptTemplateVersion,
) -> PromptTemplateVersionResponse:
    return PromptTemplateVersionResponse(
        version_id=str(version.id),
        prompt_template_id=str(version.prompt_template_id),
        template_key=template.template_key,  # type: ignore[arg-type]
        version_number=version.version_number,
        state=version.state,  # type: ignore[arg-type]
        is_active=template.active_version_number == version.version_number,
        content=version.content,
        variables=list(version.variables_json or []),
        variable_schema=dict(version.variable_schema_json or {}),
        preview_context=dict(version.preview_context_json or {}),
        change_note=version.change_note,
        source_version_number=version.source_version_number,
        created_by_id=str(version.created_by_id) if version.created_by_id else None,
        reviewed_by_id=str(version.reviewed_by_id) if version.reviewed_by_id else None,
        published_by_id=str(version.published_by_id) if version.published_by_id else None,
        reviewed_at=version.reviewed_at,
        published_at=version.published_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


async def _template_to_response(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    template: PromptTemplate,
) -> PromptTemplateResponse:
    active = await _repository.get_active_version(db_session, template=template)
    eval_count = 0
    if active is not None:
        eval_count = await _repository.count_evaluation_runs_for_version(
            db_session,
            organization_id=organization_id,
            prompt_template_version_id=active.id,
        )
    return PromptTemplateResponse(
        prompt_template_id=str(template.id),
        organization_id=str(template.organization_id),
        template_key=template.template_key,  # type: ignore[arg-type]
        name=template.name,
        description=template.description,
        category=template.category,
        latest_version_number=template.latest_version_number,
        active_version_number=template.active_version_number,
        active_version_id=str(active.id) if active is not None else None,
        active_state=active.state if active is not None else None,  # type: ignore[arg-type]
        active_published_at=active.published_at if active is not None else None,
        eval_run_count=eval_count,
        created_by_id=str(template.created_by_id) if template.created_by_id else None,
        updated_by_id=str(template.updated_by_id) if template.updated_by_id else None,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _summary_from_run(run: EvaluationRun) -> dict[str, Any] | None:
    config = run.config if isinstance(run.config, dict) else {}
    summary = config.get("metrics_summary")
    return dict(summary) if isinstance(summary, dict) else None


def _run_to_eval_response(run: EvaluationRun) -> PromptTemplateEvalResultResponse:
    config = run.config if isinstance(run.config, dict) else {}
    raw_run_name = config.get("run_name")
    return PromptTemplateEvalResultResponse(
        evaluation_run_id=str(run.id),
        evaluation_set_id=str(run.evaluation_set_id),
        run_name=raw_run_name if isinstance(raw_run_name, str) else None,
        status=run.status,
        summary=_summary_from_run(run),
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


async def _eval_results_response(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    template: PromptTemplate,
    version: PromptTemplateVersion,
    limit: int,
    offset: int,
) -> PromptTemplateEvalResultListResponse:
    runs = await _repository.list_evaluation_runs_for_version(
        db_session,
        organization_id=organization_id,
        prompt_template_version_id=version.id,
        limit=limit,
        offset=offset,
    )
    total = await _repository.count_evaluation_runs_for_version(
        db_session,
        organization_id=organization_id,
        prompt_template_version_id=version.id,
    )
    return PromptTemplateEvalResultListResponse(
        prompt_template_id=str(template.id),
        template_key=template.template_key,  # type: ignore[arg-type]
        version_number=version.version_number,
        items=[_run_to_eval_response(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("", response_model=PromptTemplateListResponse)
async def list_prompt_templates(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromptTemplateListResponse:
    organization_id = _org_id(principal)
    await _service.ensure_default_templates(db_session, organization_id=organization_id)
    await db_session.commit()

    templates = await _repository.list_templates(db_session, organization_id=organization_id)
    total = await _repository.count_templates(db_session, organization_id=organization_id)
    page = templates[offset : offset + limit]
    return PromptTemplateListResponse(
        items=[
            await _template_to_response(
                db_session,
                organization_id=organization_id,
                template=template,
            )
            for template in page
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{template_key}", response_model=PromptTemplateDetailResponse)
async def get_prompt_template_detail(
    template_key: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    eval_limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> PromptTemplateDetailResponse:
    organization_id = _org_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    await db_session.commit()
    versions = await _repository.list_versions(db_session, prompt_template_id=template.id)
    active = await _repository.get_active_version(db_session, template=template)
    version_responses = [_version_to_response(template=template, version=v) for v in versions]
    eval_results = (
        await _eval_results_response(
            db_session,
            organization_id=organization_id,
            template=template,
            version=active,
            limit=eval_limit,
            offset=0,
        )
        if active is not None
        else None
    )
    return PromptTemplateDetailResponse(
        template=await _template_to_response(
            db_session,
            organization_id=organization_id,
            template=template,
        ),
        active_version=_version_to_response(template=template, version=active)
        if active is not None
        else None,
        versions=PromptTemplateVersionListResponse(
            prompt_template_id=str(template.id),
            template_key=template.template_key,  # type: ignore[arg-type]
            items=version_responses,
            total=len(version_responses),
        ),
        eval_results=eval_results,
    )


@router.post(
    "/{template_key}/drafts",
    response_model=PromptTemplateVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_template_draft(
    template_key: str,
    payload: CreatePromptTemplateDraftRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromptTemplateVersionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    source = None
    if payload.source_version_number is not None:
        source = await _get_version_or_404(
            db_session,
            template=template,
            version_number=payload.source_version_number,
        )
    try:
        version = await _service.create_draft(
            db_session,
            template=template,
            source=source,
            created_by_id=user_id,
            change_note=payload.change_note,
        )
    except PromptTemplateValidationError as exc:
        raise _safe_validation_error(exc, status_code=status.HTTP_409_CONFLICT) from exc

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="prompt_template.draft.created",
        resource_type="prompt_template",
        resource_id=template.id,
        request_id=_request_id(request),
        metadata={
            "template_key": template.template_key,
            "version_number": version.version_number,
            "source_version_number": version.source_version_number,
        },
    )
    await db_session.commit()
    await db_session.refresh(version)
    return _version_to_response(template=template, version=version)


@router.patch(
    "/{template_key}/versions/{version_number}",
    response_model=PromptTemplateVersionResponse,
)
async def update_prompt_template_version(
    template_key: str,
    version_number: int,
    payload: UpdatePromptTemplateVersionRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromptTemplateVersionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    version = await _get_version_or_404(
        db_session,
        template=template,
        version_number=version_number,
    )
    try:
        updated = await _service.update_mutable_version(
            db_session,
            version=version,
            content=payload.content,
            variables=(
                [variable.model_dump(exclude_none=True) for variable in payload.variables]
                if payload.variables is not None
                else None
            ),
            variable_schema=payload.variable_schema,
            preview_context=payload.preview_context,
            change_note=payload.change_note,
        )
    except PromptTemplateValidationError as exc:
        status_code = (
            status.HTTP_409_CONFLICT
            if version.state == PromptTemplateVersionState.published.value
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise _safe_validation_error(exc, status_code=status_code) from exc

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="prompt_template.version.updated",
        resource_type="prompt_template",
        resource_id=template.id,
        request_id=_request_id(request),
        metadata={
            "template_key": template.template_key,
            "version_number": updated.version_number,
            "state": updated.state,
            "variable_count": len(updated.variables_json or []),
        },
    )
    await db_session.commit()
    await db_session.refresh(updated)
    return _version_to_response(template=template, version=updated)


@router.post(
    "/{template_key}/versions/{version_number}/submit-review",
    response_model=PromptTemplateVersionResponse,
)
async def submit_prompt_template_version_for_review(
    template_key: str,
    version_number: int,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromptTemplateVersionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    version = await _get_version_or_404(
        db_session,
        template=template,
        version_number=version_number,
    )
    try:
        updated = await _service.submit_for_review(
            db_session,
            version=version,
            reviewed_by_id=user_id,
        )
    except PromptTemplateValidationError as exc:
        raise _safe_validation_error(exc, status_code=status.HTTP_409_CONFLICT) from exc

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="prompt_template.version.review_requested",
        resource_type="prompt_template",
        resource_id=template.id,
        request_id=_request_id(request),
        metadata={"template_key": template.template_key, "version_number": updated.version_number},
    )
    await db_session.commit()
    await db_session.refresh(updated)
    return _version_to_response(template=template, version=updated)


@router.post(
    "/{template_key}/versions/{version_number}/publish",
    response_model=PromptTemplateVersionResponse,
)
async def publish_prompt_template_version(
    template_key: str,
    version_number: int,
    payload: PublishPromptTemplateVersionRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromptTemplateVersionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    version = await _get_version_or_404(
        db_session,
        template=template,
        version_number=version_number,
    )
    if (
        payload.change_note is not None
        and version.state != PromptTemplateVersionState.published.value
    ):
        version = await _repository.update_version(
            db_session,
            version=version,
            change_note=payload.change_note,
        )
    try:
        published = await _service.publish_version(
            db_session,
            template=template,
            version=version,
            published_by_id=user_id,
        )
    except PromptTemplateValidationError as exc:
        raise _safe_validation_error(exc, status_code=status.HTTP_409_CONFLICT) from exc

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="prompt_template.version.published",
        resource_type="prompt_template",
        resource_id=template.id,
        request_id=_request_id(request),
        metadata={
            "template_key": template.template_key,
            "version_number": published.version_number,
        },
    )
    await db_session.commit()
    await db_session.refresh(published)
    log_evaluation_event(
        event="prompt_template.version.published",
        organization_id=str(organization_id),
        user_id=str(user_id),
        job_id=str(template.id),
        version_number=published.version_number,
    )
    return _version_to_response(template=template, version=published)


@router.post("/{template_key}/rollback", response_model=PromptTemplateVersionResponse)
async def rollback_prompt_template(
    template_key: str,
    payload: RollbackPromptTemplateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromptTemplateVersionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    source = await _get_version_or_404(
        db_session,
        template=template,
        version_number=payload.version_number,
    )
    try:
        rollback = await _service.rollback_to_published_version(
            db_session,
            template=template,
            source=source,
            user_id=user_id,
            change_note=payload.change_note,
        )
    except PromptTemplateValidationError as exc:
        raise _safe_validation_error(exc, status_code=status.HTTP_409_CONFLICT) from exc

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="prompt_template.rolled_back",
        resource_type="prompt_template",
        resource_id=template.id,
        request_id=_request_id(request),
        metadata={
            "template_key": template.template_key,
            "rolled_back_to": source.version_number,
            "new_version_number": rollback.version_number,
        },
    )
    await db_session.commit()
    await db_session.refresh(rollback)
    return _version_to_response(template=template, version=rollback)


@router.post("/{template_key}/preview", response_model=PromptTemplatePreviewResponse)
async def preview_prompt_template(
    template_key: str,
    payload: PromptTemplatePreviewRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PromptTemplatePreviewResponse:
    organization_id = _org_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    version = (
        await _get_version_or_404(
            db_session,
            template=template,
            version_number=payload.version_number,
        )
        if payload.version_number is not None
        else await _repository.get_active_version(db_session, template=template)
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template version not found",
        )

    content = payload.content if payload.content is not None else version.content
    variables = (
        [variable.model_dump(exclude_none=True) for variable in payload.variables]
        if payload.variables is not None
        else list(version.variables_json or [])
    )
    variable_schema = payload.variable_schema or dict(version.variable_schema_json or {})
    if not variable_schema:
        variable_schema = build_schema_from_variables(variables)
    context = dict(version.preview_context_json or {})
    context.update(payload.context)
    try:
        validate_template_definition(
            content=content,
            variables=variables,
            variable_schema=variable_schema,
            preview_context=context,
        )
        rendered = render_prompt_template(content, context)
    except PromptTemplateValidationError as exc:
        raise _safe_validation_error(
            exc,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc

    return PromptTemplatePreviewResponse(
        template_key=template.template_key,  # type: ignore[arg-type]
        version_number=version.version_number,
        rendered_prompt=rendered,
        context=context,
    )


@router.get(
    "/{template_key}/versions/{version_number}/eval-results",
    response_model=PromptTemplateEvalResultListResponse,
)
async def list_prompt_template_eval_results(
    template_key: str,
    version_number: int,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromptTemplateEvalResultListResponse:
    organization_id = _org_id(principal)
    template = await _get_template_or_404(
        db_session,
        organization_id=organization_id,
        template_key=template_key,
    )
    version = await _get_version_or_404(
        db_session,
        template=template,
        version_number=version_number,
    )
    return await _eval_results_response(
        db_session,
        organization_id=organization_id,
        template=template,
        version=version,
        limit=limit,
        offset=offset,
    )
