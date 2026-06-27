"""Service layer for org workflow memory and user preferences (F343).

Handles serialization/deserialization of JSON columns and enforces the
permission-scoping rules:
  - Role-scoped workflows are only visible to users whose role is listed.
  - No raw document text or source content is ever persisted.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.memory.repositories.memory import (
    OrgWorkflowRepository,
    UserMemoryPreferenceRepository,
)
from app.domains.memory.schemas.memory import (
    CreateWorkflowRequest,
    MemoryPreferenceResponse,
    UpdateWorkflowRequest,
    UpsertMemoryPreferenceRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowStepResponse,
)
from app.models.org_memory import OrgWorkflow, UserMemoryPreference

_wf_repo = OrgWorkflowRepository()
_pref_repo = UserMemoryPreferenceRepository()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _steps_to_json(steps) -> str | None:
    if not steps:
        return None
    return json.dumps([s.model_dump() for s in steps])


def _steps_from_json(raw: str | None) -> list[WorkflowStepResponse]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [WorkflowStepResponse(**item) for item in data]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _role_scope_to_csv(role_scope: list[str] | None) -> str | None:
    if not role_scope:
        return None
    return ",".join(role_scope)


def _role_scope_from_csv(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [r.strip() for r in raw.split(",") if r.strip()]


def _collection_ids_to_json(ids: list[str] | None) -> str | None:
    if ids is None:
        return None
    return json.dumps(ids)


def _collection_ids_from_json(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extra_defaults_to_json(d: dict | None) -> str | None:
    if d is None:
        return None
    return json.dumps(d)


def _extra_defaults_from_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _workflow_to_response(wf: OrgWorkflow) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=str(wf.id),
        organization_id=str(wf.organization_id),
        created_by_id=str(wf.created_by_id) if wf.created_by_id else None,
        name=wf.name,
        description=wf.description,
        workflow_type=wf.workflow_type,
        status=wf.status,
        steps=_steps_from_json(wf.steps),
        role_scope=_role_scope_from_csv(wf.role_scope),
        collection_scope_ids=_collection_ids_from_json(wf.collection_scope_ids),
        verified_knowledge_card_id=(
            str(wf.verified_knowledge_card_id) if wf.verified_knowledge_card_id else None
        ),
        use_count=wf.use_count or 0,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


def _pref_to_response(pref: UserMemoryPreference) -> MemoryPreferenceResponse:
    return MemoryPreferenceResponse(
        preference_id=str(pref.id),
        organization_id=str(pref.organization_id),
        user_id=str(pref.user_id),
        preferred_scope=pref.preferred_scope,
        preferred_collection_ids=_collection_ids_from_json(pref.preferred_collection_ids),
        rag_profile_id=str(pref.rag_profile_id) if pref.rag_profile_id else None,
        answer_language=pref.answer_language,
        extra_defaults=_extra_defaults_from_json(pref.extra_defaults),
        created_at=pref.created_at,
        updated_at=pref.updated_at,
    )


def _is_role_visible(wf: OrgWorkflow, user_role: str) -> bool:
    """Return True if this workflow is visible to the given role."""
    roles = _role_scope_from_csv(wf.role_scope)
    if roles is None:
        return True
    return user_role in roles


# ---------------------------------------------------------------------------
# Workflow service
# ---------------------------------------------------------------------------


class OrgWorkflowService:
    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        created_by_id: UUID,
        payload: CreateWorkflowRequest,
    ) -> WorkflowResponse:
        vkc_id: UUID | None = None
        if payload.verified_knowledge_card_id:
            vkc_id = UUID(payload.verified_knowledge_card_id)

        wf = await _wf_repo.create(
            db,
            organization_id=organization_id,
            created_by_id=created_by_id,
            name=payload.name,
            description=payload.description,
            workflow_type=payload.workflow_type,
            steps_json=_steps_to_json(payload.steps),
            role_scope_csv=_role_scope_to_csv(payload.role_scope),
            collection_scope_ids_json=_collection_ids_to_json(payload.collection_scope_ids),
            verified_knowledge_card_id=vkc_id,
        )
        return _workflow_to_response(wf)

    async def get(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        organization_id: UUID,
        user_role: str,
    ) -> WorkflowResponse | None:
        wf = await _wf_repo.get(db, workflow_id=workflow_id, organization_id=organization_id)
        if wf is None:
            return None
        if not _is_role_visible(wf, user_role):
            return None
        return _workflow_to_response(wf)

    async def list_active(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_role: str,
        workflow_type: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> WorkflowListResponse:
        items = await _wf_repo.list_active(
            db,
            organization_id=organization_id,
            workflow_type=workflow_type,
            query=query,
            limit=limit + 100,  # fetch extra to account for role filtering
            offset=0,
        )
        visible = [wf for wf in items if _is_role_visible(wf, user_role)]
        total = len(visible)
        paged = visible[offset : offset + limit]
        return WorkflowListResponse(
            items=[_workflow_to_response(w) for w in paged],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        organization_id: UUID,
        requestor_id: UUID,
        requestor_role: str,
        payload: UpdateWorkflowRequest,
        is_admin: bool,
    ) -> WorkflowResponse | None:
        wf = await _wf_repo.get(db, workflow_id=workflow_id, organization_id=organization_id)
        if wf is None:
            return None
        if wf.status == "archived":
            raise ValueError("Cannot edit an archived workflow")
        if not is_admin and str(wf.created_by_id) != str(requestor_id):
            raise PermissionError("Only the workflow creator or an admin can update it")

        vkc_id: UUID | None = None
        unset_vkc = False
        if payload.verified_knowledge_card_id is not None:
            if payload.verified_knowledge_card_id == "":
                unset_vkc = True
            else:
                vkc_id = UUID(payload.verified_knowledge_card_id)

        await _wf_repo.update(
            db,
            wf,
            name=payload.name,
            description=payload.description,
            workflow_type=payload.workflow_type,
            steps_json=_steps_to_json(payload.steps) if payload.steps is not None else None,
            role_scope_csv=(
                _role_scope_to_csv(payload.role_scope) if payload.role_scope is not None else None
            ),
            collection_scope_ids_json=(
                _collection_ids_to_json(payload.collection_scope_ids)
                if payload.collection_scope_ids is not None
                else None
            ),
            verified_knowledge_card_id=vkc_id,
            _unset_vkc=unset_vkc,
        )
        return _workflow_to_response(wf)

    async def increment_use(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        organization_id: UUID,
    ) -> bool:
        wf = await _wf_repo.get(db, workflow_id=workflow_id, organization_id=organization_id)
        if wf is None or wf.status != "active":
            return False
        await _wf_repo.increment_use_count(db, wf)
        return True

    async def admin_list(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        workflow_type: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> WorkflowListResponse:
        items = await _wf_repo.list_all_admin(
            db,
            organization_id=organization_id,
            status=status,
            workflow_type=workflow_type,
            query=query,
            limit=limit,
            offset=offset,
        )
        total = await _wf_repo.count_all_admin(
            db,
            organization_id=organization_id,
            status=status,
            workflow_type=workflow_type,
            query=query,
        )
        return WorkflowListResponse(
            items=[_workflow_to_response(w) for w in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def admin_archive(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        organization_id: UUID,
    ) -> bool:
        wf = await _wf_repo.get(db, workflow_id=workflow_id, organization_id=organization_id)
        if wf is None:
            return False
        await _wf_repo.archive(db, wf)
        return True

    async def admin_delete(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        organization_id: UUID,
    ) -> bool:
        wf = await _wf_repo.get(db, workflow_id=workflow_id, organization_id=organization_id)
        if wf is None:
            return False
        await _wf_repo.delete(db, wf)
        return True


# ---------------------------------------------------------------------------
# User preference service
# ---------------------------------------------------------------------------


class UserMemoryPreferenceService:
    async def get(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> MemoryPreferenceResponse | None:
        pref = await _pref_repo.get_or_none(db, organization_id=organization_id, user_id=user_id)
        if pref is None:
            return None
        return _pref_to_response(pref)

    async def upsert(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        payload: UpsertMemoryPreferenceRequest,
    ) -> MemoryPreferenceResponse:
        rag_profile_uuid: UUID | None = None
        if payload.rag_profile_id:
            rag_profile_uuid = UUID(payload.rag_profile_id)

        pref = await _pref_repo.upsert(
            db,
            organization_id=organization_id,
            user_id=user_id,
            preferred_scope=payload.preferred_scope,
            preferred_collection_ids_json=_collection_ids_to_json(payload.preferred_collection_ids),
            rag_profile_id=rag_profile_uuid,
            answer_language=payload.answer_language,
            extra_defaults_json=_extra_defaults_to_json(payload.extra_defaults),
        )
        return _pref_to_response(pref)

    async def delete(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        return await _pref_repo.delete(db, organization_id=organization_id, user_id=user_id)
