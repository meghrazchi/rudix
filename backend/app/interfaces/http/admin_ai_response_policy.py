"""HTTP interface — AI response policy engine admin (F268)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.ai_response_policy.repositories.ai_response_policy import (
    AiResponsePolicyRepository,
)
from app.domains.ai_response_policy.schemas.ai_response_policy import (
    AiResponsePolicyListResponse,
    AiResponsePolicyResponse,
    CollectionPolicyOverrideResponse,
    CreateAiResponsePolicyRequest,
    PolicyEvaluationLogListResponse,
    PolicyEvaluationLogResponse,
    PolicyPreviewRequest,
    PolicyPreviewResponse,
    UpdateAiResponsePolicyRequest,
    UpsertCollectionPolicyOverrideRequest,
)
from app.domains.ai_response_policy.services.policy_engine import AiResponsePolicyEngine
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/admin/ai-response-policy", tags=["admin-ai-response-policy"])

_repo = AiResponsePolicyRepository()
_engine = AiResponsePolicyEngine()
_audit = AuditLogService()

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active organization context"
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid user context"
        ) from exc


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found"
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _to_response(policy) -> AiResponsePolicyResponse:
    return AiResponsePolicyResponse(
        policy_id=str(policy.id),
        organization_id=str(policy.organization_id),
        policy_name=policy.policy_name,
        description=policy.description,
        is_active=policy.is_active,
        citation_mode=policy.citation_mode,  # type: ignore[arg-type]
        min_confidence_threshold=policy.min_confidence_threshold,
        no_answer_behavior=policy.no_answer_behavior,  # type: ignore[arg-type]
        grounded_verification_mode=policy.grounded_verification_mode,  # type: ignore[arg-type]
        grounded_verification_threshold=policy.grounded_verification_threshold,
        stale_source_behavior=policy.stale_source_behavior,  # type: ignore[arg-type]
        blocked_topics=list(policy.blocked_topics_json or []),
        allowed_topics=list(policy.allowed_topics_json)
        if policy.allowed_topics_json is not None
        else None,
        min_sources_required=policy.min_sources_required,
        disclaimer_text=policy.disclaimer_text,
        disclaimer_position=policy.disclaimer_position,  # type: ignore[arg-type]
        refusal_message=policy.refusal_message,
        created_by_id=str(policy.created_by_id) if policy.created_by_id else None,
        updated_by_id=str(policy.updated_by_id) if policy.updated_by_id else None,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _to_override_response(override) -> CollectionPolicyOverrideResponse:
    return CollectionPolicyOverrideResponse(
        override_id=str(override.id),
        org_policy_id=str(override.org_policy_id),
        collection_id=str(override.collection_id),
        citation_mode=override.citation_mode,  # type: ignore[arg-type]
        min_confidence_threshold=override.min_confidence_threshold,
        no_answer_behavior=override.no_answer_behavior,  # type: ignore[arg-type]
        grounded_verification_mode=override.grounded_verification_mode,  # type: ignore[arg-type]
        grounded_verification_threshold=override.grounded_verification_threshold,
        stale_source_behavior=override.stale_source_behavior,  # type: ignore[arg-type]
        blocked_topics=list(override.blocked_topics_json)
        if override.blocked_topics_json is not None
        else None,
        allowed_topics=list(override.allowed_topics_json)
        if override.allowed_topics_json is not None
        else None,
        min_sources_required=override.min_sources_required,
        disclaimer_text=override.disclaimer_text,
        refusal_message=override.refusal_message,
        updated_by_id=str(override.updated_by_id) if override.updated_by_id else None,
        created_at=override.created_at,
        updated_at=override.updated_at,
    )


def _to_log_response(log) -> PolicyEvaluationLogResponse:
    return PolicyEvaluationLogResponse(
        log_id=str(log.id),
        organization_id=str(log.organization_id),
        user_id=str(log.user_id) if log.user_id else None,
        org_policy_id=str(log.org_policy_id) if log.org_policy_id else None,
        collection_id=str(log.collection_id) if log.collection_id else None,
        chat_session_id=str(log.chat_session_id) if log.chat_session_id else None,
        chat_message_id=str(log.chat_message_id) if log.chat_message_id else None,
        outcome=log.outcome,  # type: ignore[arg-type]
        policy_source=log.policy_source,  # type: ignore[arg-type]
        violated_rules=list(log.violated_rules_json or []),
        warning_flags=list(log.warning_flags_json or []),
        question_preview=log.question_preview,
        confidence_score=log.confidence_score,
        citation_count=log.citation_count,
        stale_source_count=log.stale_source_count,
        is_preview_run=log.is_preview_run,
        created_at=log.created_at,
    )


# ---------------------------------------------------------------------------
# Org-level policy CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=AiResponsePolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    request: Request,
    payload: CreateAiResponsePolicyRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AiResponsePolicyResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    policy = await _repo.create(
        db,
        organization_id=org_id,
        policy_name=payload.policy_name,
        description=payload.description,
        citation_mode=payload.citation_mode,
        min_confidence_threshold=payload.min_confidence_threshold,
        no_answer_behavior=payload.no_answer_behavior,
        grounded_verification_mode=payload.grounded_verification_mode,
        grounded_verification_threshold=payload.grounded_verification_threshold,
        stale_source_behavior=payload.stale_source_behavior,
        blocked_topics=payload.blocked_topics,
        allowed_topics=payload.allowed_topics,
        min_sources_required=payload.min_sources_required,
        disclaimer_text=payload.disclaimer_text,
        disclaimer_position=payload.disclaimer_position,
        refusal_message=payload.refusal_message,
        created_by_id=user_id,
    )
    await db.commit()
    await db.refresh(policy)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ai_response_policy.created",
        resource_type="ai_response_policy",
        resource_id=policy.id,
        request_id=_request_id(request),
        metadata={"policy_name": policy.policy_name},
    )
    await db.commit()
    return _to_response(policy)


@router.get("", response_model=AiResponsePolicyListResponse)
async def list_policies(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiResponsePolicyListResponse:
    org_id = _org_id(principal)
    items = await _repo.list(db, organization_id=org_id, limit=limit, offset=offset)
    total = await _repo.count(db, organization_id=org_id)
    return AiResponsePolicyListResponse(
        items=[_to_response(p) for p in items],
        total=total,
    )


@router.get("/active", response_model=AiResponsePolicyResponse | None)
async def get_active_policy(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AiResponsePolicyResponse | None:
    org_id = _org_id(principal)
    policy = await _repo.get_active(db, organization_id=org_id)
    return _to_response(policy) if policy else None


@router.get("/logs", response_model=PolicyEvaluationLogListResponse)
async def list_eval_logs(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    outcome: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PolicyEvaluationLogListResponse:
    org_id = _org_id(principal)
    items = await _repo.list_eval_logs(
        db, organization_id=org_id, outcome=outcome, limit=limit, offset=offset
    )
    total = await _repo.count_eval_logs(db, organization_id=org_id, outcome=outcome)
    return PolicyEvaluationLogListResponse(
        items=[_to_log_response(log) for log in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{policy_id}", response_model=AiResponsePolicyResponse)
async def get_policy(
    policy_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AiResponsePolicyResponse:
    org_id = _org_id(principal)
    policy_uuid = _parse_uuid(policy_id, "AI response policy")
    policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
        )
    return _to_response(policy)


@router.patch("/{policy_id}", response_model=AiResponsePolicyResponse)
async def update_policy(
    policy_id: str,
    request: Request,
    payload: UpdateAiResponsePolicyRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AiResponsePolicyResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    policy_uuid = _parse_uuid(policy_id, "AI response policy")
    policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
        )

    # Handle activation toggle separately (deactivate others first)
    if payload.is_active is not None:
        if payload.is_active:
            await _repo.activate(db, organization_id=org_id, policy=policy)
        else:
            await _repo.deactivate(db, policy)

    await _repo.update(
        db,
        policy,
        policy_name=payload.policy_name,
        description=payload.description,
        citation_mode=payload.citation_mode,
        min_confidence_threshold=payload.min_confidence_threshold,
        no_answer_behavior=payload.no_answer_behavior,
        grounded_verification_mode=payload.grounded_verification_mode,
        grounded_verification_threshold=payload.grounded_verification_threshold,
        stale_source_behavior=payload.stale_source_behavior,
        blocked_topics=payload.blocked_topics,
        allowed_topics=payload.allowed_topics,
        min_sources_required=payload.min_sources_required,
        disclaimer_text=payload.disclaimer_text,
        disclaimer_position=payload.disclaimer_position,
        refusal_message=payload.refusal_message,
        updated_by_id=user_id,
    )
    await db.commit()
    await db.refresh(policy)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ai_response_policy.updated",
        resource_type="ai_response_policy",
        resource_id=policy.id,
        request_id=_request_id(request),
        metadata={"policy_name": policy.policy_name, "is_active": policy.is_active},
    )
    await db.commit()
    return _to_response(policy)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    policy_uuid = _parse_uuid(policy_id, "AI response policy")
    policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
        )
    if policy.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deactivate the policy before deleting it.",
        )

    policy_id_copy = policy.id
    policy_name = policy.policy_name
    await _repo.delete(db, policy)
    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ai_response_policy.deleted",
        resource_type="ai_response_policy",
        resource_id=policy_id_copy,
        request_id=_request_id(request),
        metadata={"policy_name": policy_name},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Policy activate / deactivate convenience endpoints
# ---------------------------------------------------------------------------


@router.post("/{policy_id}/activate", response_model=AiResponsePolicyResponse)
async def activate_policy(
    policy_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AiResponsePolicyResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    policy_uuid = _parse_uuid(policy_id, "AI response policy")
    policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
        )

    await _repo.activate(db, organization_id=org_id, policy=policy)
    await db.commit()
    await db.refresh(policy)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ai_response_policy.activated",
        resource_type="ai_response_policy",
        resource_id=policy.id,
        request_id=_request_id(request),
        metadata={"policy_name": policy.policy_name},
    )
    await db.commit()
    return _to_response(policy)


@router.post("/{policy_id}/deactivate", response_model=AiResponsePolicyResponse)
async def deactivate_policy(
    policy_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AiResponsePolicyResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    policy_uuid = _parse_uuid(policy_id, "AI response policy")
    policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
        )

    await _repo.deactivate(db, policy)
    await db.commit()
    await db.refresh(policy)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ai_response_policy.deactivated",
        resource_type="ai_response_policy",
        resource_id=policy.id,
        request_id=_request_id(request),
        metadata={"policy_name": policy.policy_name},
    )
    await db.commit()
    return _to_response(policy)


# ---------------------------------------------------------------------------
# Collection-level override CRUD
# ---------------------------------------------------------------------------


@router.put(
    "/{policy_id}/collections/{collection_id}", response_model=CollectionPolicyOverrideResponse
)
async def upsert_collection_override(
    policy_id: str,
    collection_id: str,
    request: Request,
    payload: UpsertCollectionPolicyOverrideRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionPolicyOverrideResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    policy_uuid = _parse_uuid(policy_id, "AI response policy")
    collection_uuid = _parse_uuid(collection_id, "Collection")

    policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
        )

    override = await _repo.upsert_collection_override(
        db,
        org_policy_id=policy_uuid,
        collection_id=collection_uuid,
        updated_by_id=user_id,
        citation_mode=payload.citation_mode,
        min_confidence_threshold=payload.min_confidence_threshold,
        no_answer_behavior=payload.no_answer_behavior,
        stale_source_behavior=payload.stale_source_behavior,
        blocked_topics=payload.blocked_topics,
        allowed_topics=payload.allowed_topics,
        min_sources_required=payload.min_sources_required,
        disclaimer_text=payload.disclaimer_text,
        refusal_message=payload.refusal_message,
    )
    await db.commit()
    await db.refresh(override)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ai_response_policy.collection_override_upserted",
        resource_type="ai_response_policy",
        resource_id=policy_uuid,
        request_id=_request_id(request),
        metadata={"collection_id": collection_id},
    )
    await db.commit()
    return _to_override_response(override)


@router.delete("/{policy_id}/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection_override(
    policy_id: str,
    collection_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    policy_uuid = _parse_uuid(policy_id, "AI response policy")
    collection_uuid = _parse_uuid(collection_id, "Collection")

    policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
        )

    override = await _repo.get_collection_override(
        db, org_policy_id=policy_uuid, collection_id=collection_uuid
    )
    if override is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection override not found"
        )

    await _repo.delete_collection_override(db, override)
    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ai_response_policy.collection_override_deleted",
        resource_type="ai_response_policy",
        resource_id=policy_uuid,
        request_id=_request_id(request),
        metadata={"collection_id": collection_id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Policy preview — test before enabling
# ---------------------------------------------------------------------------


@router.post("/preview", response_model=PolicyPreviewResponse)
async def preview_policy(
    payload: PolicyPreviewRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PolicyPreviewResponse:
    """Simulate policy evaluation without affecting the live pipeline.

    Admins can test any policy (active or draft) against a hypothetical query
    scenario before enabling it in production.
    """
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    # Resolve which policy to test
    if payload.policy_id:
        policy_uuid = _parse_uuid(payload.policy_id, "AI response policy")
        policy = await _repo.get(db, policy_id=policy_uuid, organization_id=org_id)
        if policy is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="AI response policy not found"
            )
        # Temporarily treat it as active for preview purposes
        policy.is_active = True
    else:
        policy = await _repo.get_active(db, organization_id=org_id)

    # Resolve collection override if requested
    collection_override = None
    collection_uuid: UUID | None = None
    if payload.collection_id and policy is not None:
        collection_uuid = _parse_uuid(payload.collection_id, "Collection")
        collection_override = await _repo.get_collection_override(
            db, org_policy_id=policy.id, collection_id=collection_uuid
        )

    effective = _engine.resolve(policy, collection_override)

    # Phase 1: pre-generation topic check
    pre_result = _engine.evaluate_pre_generation(payload.question, effective)

    # Phase 2: post-generation checks (using supplied hypothetical values)
    post_result = _engine.evaluate_post_generation(
        confidence_score=payload.confidence_score,
        citation_count=payload.citation_count,
        stale_source_count=payload.stale_source_count,
        not_found=payload.confidence_score < 0.01,
        effective_policy=effective,
    )

    # Merge results — blocked in either phase wins
    blocked = pre_result.blocked or post_result.blocked
    warned = (pre_result.warned or post_result.warned) and not blocked
    violated_rules = pre_result.violated_rules + post_result.violated_rules
    warning_flags = pre_result.warning_flags + post_result.warning_flags

    # Log the preview run for observability
    await _repo.create_eval_log(
        db,
        organization_id=org_id,
        user_id=user_id,
        org_policy_id=UUID(effective.policy_id) if effective.policy_id else None,
        collection_id=collection_uuid,
        chat_session_id=None,
        chat_message_id=None,
        outcome="blocked" if blocked else ("warned" if warned else "allowed"),
        policy_source=effective.source,
        violated_rules=violated_rules,
        warning_flags=warning_flags,
        question_preview=payload.question[:256],
        confidence_score=payload.confidence_score,
        citation_count=payload.citation_count,
        stale_source_count=payload.stale_source_count,
        is_preview_run=True,
    )
    await db.commit()

    effective_refusal = effective.refusal_message or (
        "I'm unable to provide an answer due to your organization's content policy."
    )

    return PolicyPreviewResponse(
        outcome="blocked" if blocked else ("warned" if warned else "allowed"),  # type: ignore[arg-type]
        policy_source=effective.source,  # type: ignore[arg-type]
        policy_id=effective.policy_id,
        violated_rules=violated_rules,
        warning_flags=warning_flags,
        refusal_message=effective_refusal if blocked else None,
        disclaimer_text=effective.disclaimer_text,
        disclaimer_position=effective.disclaimer_position,  # type: ignore[arg-type]
    )
