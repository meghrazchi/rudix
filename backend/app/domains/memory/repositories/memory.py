"""Repository layer for org workflow memory and user preferences (F343)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_memory import OrgWorkflow, UserMemoryPreference


class OrgWorkflowRepository:
    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        created_by_id: UUID | None,
        name: str,
        description: str | None,
        workflow_type: str,
        steps_json: str | None,
        role_scope_csv: str | None,
        collection_scope_ids_json: str | None,
        verified_knowledge_card_id: UUID | None,
    ) -> OrgWorkflow:
        wf = OrgWorkflow(
            organization_id=organization_id,
            created_by_id=created_by_id,
            name=name,
            description=description,
            workflow_type=workflow_type,
            status="active",
            steps=steps_json,
            role_scope=role_scope_csv,
            collection_scope_ids=collection_scope_ids_json,
            verified_knowledge_card_id=verified_knowledge_card_id,
            use_count=0,
        )
        db.add(wf)
        await db.flush()
        return wf

    async def get(
        self,
        db: AsyncSession,
        *,
        workflow_id: UUID,
        organization_id: UUID,
    ) -> OrgWorkflow | None:
        stmt = select(OrgWorkflow).where(
            OrgWorkflow.id == workflow_id,
            OrgWorkflow.organization_id == organization_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        workflow_type: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrgWorkflow]:
        stmt = select(OrgWorkflow).where(
            OrgWorkflow.organization_id == organization_id,
            OrgWorkflow.status == "active",
        )
        if workflow_type:
            stmt = stmt.where(OrgWorkflow.workflow_type == workflow_type)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    OrgWorkflow.name.ilike(like),
                    OrgWorkflow.description.ilike(like),
                )
            )
        stmt = stmt.order_by(OrgWorkflow.use_count.desc(), OrgWorkflow.updated_at.desc())
        stmt = stmt.limit(limit).offset(offset)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_all_admin(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        workflow_type: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrgWorkflow]:
        stmt = select(OrgWorkflow).where(OrgWorkflow.organization_id == organization_id)
        if status:
            stmt = stmt.where(OrgWorkflow.status == status)
        if workflow_type:
            stmt = stmt.where(OrgWorkflow.workflow_type == workflow_type)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    OrgWorkflow.name.ilike(like),
                    OrgWorkflow.description.ilike(like),
                )
            )
        stmt = stmt.order_by(OrgWorkflow.updated_at.desc()).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_active(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        workflow_type: str | None = None,
        query: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(OrgWorkflow)
            .where(
                OrgWorkflow.organization_id == organization_id,
                OrgWorkflow.status == "active",
            )
        )
        if workflow_type:
            stmt = stmt.where(OrgWorkflow.workflow_type == workflow_type)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    OrgWorkflow.name.ilike(like),
                    OrgWorkflow.description.ilike(like),
                )
            )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def count_all_admin(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        workflow_type: str | None = None,
        query: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(OrgWorkflow)
            .where(OrgWorkflow.organization_id == organization_id)
        )
        if status:
            stmt = stmt.where(OrgWorkflow.status == status)
        if workflow_type:
            stmt = stmt.where(OrgWorkflow.workflow_type == workflow_type)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    OrgWorkflow.name.ilike(like),
                    OrgWorkflow.description.ilike(like),
                )
            )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def update(
        self,
        db: AsyncSession,
        wf: OrgWorkflow,
        *,
        name: str | None,
        description: str | None,
        workflow_type: str | None,
        steps_json: str | None,
        role_scope_csv: str | None,
        collection_scope_ids_json: str | None,
        verified_knowledge_card_id: UUID | None,
        _unset_vkc: bool = False,
    ) -> None:
        if name is not None:
            wf.name = name
        if description is not None:
            wf.description = description
        if workflow_type is not None:
            wf.workflow_type = workflow_type
        if steps_json is not None:
            wf.steps = steps_json
        if role_scope_csv is not None:
            wf.role_scope = role_scope_csv
        if collection_scope_ids_json is not None:
            wf.collection_scope_ids = collection_scope_ids_json
        if verified_knowledge_card_id is not None:
            wf.verified_knowledge_card_id = verified_knowledge_card_id
        elif _unset_vkc:
            wf.verified_knowledge_card_id = None
        await db.flush()
        await db.refresh(wf)

    async def archive(self, db: AsyncSession, wf: OrgWorkflow) -> None:
        wf.status = "archived"
        await db.flush()

    async def delete(self, db: AsyncSession, wf: OrgWorkflow) -> None:
        await db.delete(wf)
        await db.flush()

    async def increment_use_count(self, db: AsyncSession, wf: OrgWorkflow) -> None:
        wf.use_count = (wf.use_count or 0) + 1
        await db.flush()


class UserMemoryPreferenceRepository:
    async def get_or_none(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> UserMemoryPreference | None:
        stmt = select(UserMemoryPreference).where(
            UserMemoryPreference.organization_id == organization_id,
            UserMemoryPreference.user_id == user_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        preferred_scope: str | None,
        preferred_collection_ids_json: str | None,
        rag_profile_id: UUID | None,
        answer_language: str | None,
        extra_defaults_json: str | None,
    ) -> UserMemoryPreference:
        pref = await self.get_or_none(db, organization_id=organization_id, user_id=user_id)
        if pref is None:
            pref = UserMemoryPreference(
                organization_id=organization_id,
                user_id=user_id,
            )
            db.add(pref)

        pref.preferred_scope = preferred_scope
        pref.preferred_collection_ids = preferred_collection_ids_json
        pref.rag_profile_id = rag_profile_id
        pref.answer_language = answer_language
        pref.extra_defaults = extra_defaults_json
        await db.flush()
        return pref

    async def delete(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        pref = await self.get_or_none(db, organization_id=organization_id, user_id=user_id)
        if pref is None:
            return False
        await db.delete(pref)
        await db.flush()
        return True
