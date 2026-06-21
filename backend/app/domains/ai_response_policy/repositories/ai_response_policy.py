"""Repository layer for AI response policy engine (F268)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_response_policy import (
    CollectionAiResponsePolicyOverride,
    OrgAiResponsePolicy,
    PolicyEvaluationLog,
)


class AiResponsePolicyRepository:
    # ------------------------------------------------------------------
    # Org policy CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        policy_name: str,
        description: str | None = None,
        citation_mode: str = "recommended",
        min_confidence_threshold: float | None = None,
        no_answer_behavior: str = "warn",
        grounded_verification_mode: str = "off",
        grounded_verification_threshold: float | None = None,
        stale_source_behavior: str = "warn",
        blocked_topics: list[str] | None = None,
        allowed_topics: list[str] | None = None,
        min_sources_required: int | None = None,
        disclaimer_text: str | None = None,
        disclaimer_position: str = "prepend",
        refusal_message: str | None = None,
        created_by_id: UUID | None = None,
    ) -> OrgAiResponsePolicy:
        import uuid

        policy = OrgAiResponsePolicy(
            id=uuid.uuid4(),
            organization_id=organization_id,
            policy_name=policy_name,
            description=description,
            is_active=False,
            citation_mode=citation_mode,
            min_confidence_threshold=min_confidence_threshold,
            no_answer_behavior=no_answer_behavior,
            grounded_verification_mode=grounded_verification_mode,
            grounded_verification_threshold=grounded_verification_threshold,
            stale_source_behavior=stale_source_behavior,
            blocked_topics_json=blocked_topics or [],
            allowed_topics_json=allowed_topics,
            min_sources_required=min_sources_required,
            disclaimer_text=disclaimer_text,
            disclaimer_position=disclaimer_position,
            refusal_message=refusal_message,
            created_by_id=created_by_id,
            updated_by_id=created_by_id,
        )
        db.add(policy)
        await db.flush()
        return policy

    async def get(
        self,
        db: AsyncSession,
        *,
        policy_id: UUID,
        organization_id: UUID,
    ) -> OrgAiResponsePolicy | None:
        result = await db.execute(
            select(OrgAiResponsePolicy)
            .options(selectinload(OrgAiResponsePolicy.collection_overrides))
            .where(
                OrgAiResponsePolicy.id == policy_id,
                OrgAiResponsePolicy.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
    ) -> OrgAiResponsePolicy | None:
        result = await db.execute(
            select(OrgAiResponsePolicy)
            .options(selectinload(OrgAiResponsePolicy.collection_overrides))
            .where(
                OrgAiResponsePolicy.organization_id == organization_id,
                OrgAiResponsePolicy.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrgAiResponsePolicy]:
        result = await db.execute(
            select(OrgAiResponsePolicy)
            .where(OrgAiResponsePolicy.organization_id == organization_id)
            .order_by(OrgAiResponsePolicy.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        result = await db.execute(
            select(func.count()).where(OrgAiResponsePolicy.organization_id == organization_id)
        )
        return result.scalar_one()

    async def update(
        self,
        db: AsyncSession,
        policy: OrgAiResponsePolicy,
        *,
        policy_name: str | None = None,
        description: str | None = None,
        citation_mode: str | None = None,
        min_confidence_threshold: float | None = None,
        no_answer_behavior: str | None = None,
        grounded_verification_mode: str | None = None,
        grounded_verification_threshold: float | None = None,
        stale_source_behavior: str | None = None,
        blocked_topics: list[str] | None = None,
        allowed_topics: list[str] | None = None,
        min_sources_required: int | None = None,
        disclaimer_text: str | None = None,
        disclaimer_position: str | None = None,
        refusal_message: str | None = None,
        updated_by_id: UUID | None = None,
    ) -> OrgAiResponsePolicy:
        if policy_name is not None:
            policy.policy_name = policy_name
        if description is not None:
            policy.description = description
        if citation_mode is not None:
            policy.citation_mode = citation_mode
        if min_confidence_threshold is not None:
            policy.min_confidence_threshold = min_confidence_threshold
        if no_answer_behavior is not None:
            policy.no_answer_behavior = no_answer_behavior
        if grounded_verification_mode is not None:
            policy.grounded_verification_mode = grounded_verification_mode
        if grounded_verification_threshold is not None:
            policy.grounded_verification_threshold = grounded_verification_threshold
        if stale_source_behavior is not None:
            policy.stale_source_behavior = stale_source_behavior
        if blocked_topics is not None:
            policy.blocked_topics_json = blocked_topics
        if allowed_topics is not None:
            policy.allowed_topics_json = allowed_topics
        if min_sources_required is not None:
            policy.min_sources_required = min_sources_required
        if disclaimer_text is not None:
            policy.disclaimer_text = disclaimer_text
        if disclaimer_position is not None:
            policy.disclaimer_position = disclaimer_position
        if refusal_message is not None:
            policy.refusal_message = refusal_message
        if updated_by_id is not None:
            policy.updated_by_id = updated_by_id
        await db.flush()
        return policy

    async def activate(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        policy: OrgAiResponsePolicy,
    ) -> OrgAiResponsePolicy:
        """Deactivate any existing active policy, then activate this one."""
        existing = await self.get_active(db, organization_id=organization_id)
        if existing and existing.id != policy.id:
            existing.is_active = False
            await db.flush()
        policy.is_active = True
        await db.flush()
        return policy

    async def deactivate(
        self,
        db: AsyncSession,
        policy: OrgAiResponsePolicy,
    ) -> OrgAiResponsePolicy:
        policy.is_active = False
        await db.flush()
        return policy

    async def delete(self, db: AsyncSession, policy: OrgAiResponsePolicy) -> None:
        await db.delete(policy)
        await db.flush()

    # ------------------------------------------------------------------
    # Collection override CRUD
    # ------------------------------------------------------------------

    async def get_collection_override(
        self,
        db: AsyncSession,
        *,
        org_policy_id: UUID,
        collection_id: UUID,
    ) -> CollectionAiResponsePolicyOverride | None:
        result = await db.execute(
            select(CollectionAiResponsePolicyOverride).where(
                CollectionAiResponsePolicyOverride.org_policy_id == org_policy_id,
                CollectionAiResponsePolicyOverride.collection_id == collection_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_collection_override(
        self,
        db: AsyncSession,
        *,
        org_policy_id: UUID,
        collection_id: UUID,
        updated_by_id: UUID | None = None,
        citation_mode: str | None = None,
        min_confidence_threshold: float | None = None,
        no_answer_behavior: str | None = None,
        grounded_verification_mode: str | None = None,
        grounded_verification_threshold: float | None = None,
        stale_source_behavior: str | None = None,
        blocked_topics: list[str] | None = None,
        allowed_topics: list[str] | None = None,
        min_sources_required: int | None = None,
        disclaimer_text: str | None = None,
        refusal_message: str | None = None,
    ) -> CollectionAiResponsePolicyOverride:
        import uuid

        override = await self.get_collection_override(
            db, org_policy_id=org_policy_id, collection_id=collection_id
        )
        if override is None:
            override = CollectionAiResponsePolicyOverride(
                id=uuid.uuid4(),
                org_policy_id=org_policy_id,
                collection_id=collection_id,
            )
            db.add(override)

        override.updated_by_id = updated_by_id
        override.citation_mode = citation_mode
        override.min_confidence_threshold = min_confidence_threshold
        override.no_answer_behavior = no_answer_behavior
        override.grounded_verification_mode = grounded_verification_mode
        override.grounded_verification_threshold = grounded_verification_threshold
        override.stale_source_behavior = stale_source_behavior
        override.blocked_topics_json = blocked_topics
        override.allowed_topics_json = allowed_topics
        override.min_sources_required = min_sources_required
        override.disclaimer_text = disclaimer_text
        override.refusal_message = refusal_message

        await db.flush()
        return override

    async def delete_collection_override(
        self,
        db: AsyncSession,
        override: CollectionAiResponsePolicyOverride,
    ) -> None:
        await db.delete(override)
        await db.flush()

    # ------------------------------------------------------------------
    # Evaluation log CRUD
    # ------------------------------------------------------------------

    async def create_eval_log(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        org_policy_id: UUID | None,
        collection_id: UUID | None,
        chat_session_id: UUID | None,
        chat_message_id: UUID | None,
        outcome: str,
        policy_source: str,
        violated_rules: list[str],
        warning_flags: list[str],
        question_preview: str | None,
        confidence_score: float | None,
        citation_count: int | None,
        stale_source_count: int | None,
        is_preview_run: bool = False,
    ) -> PolicyEvaluationLog:
        import uuid

        log = PolicyEvaluationLog(
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            org_policy_id=org_policy_id,
            collection_id=collection_id,
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            outcome=outcome,
            policy_source=policy_source,
            violated_rules_json=violated_rules,
            warning_flags_json=warning_flags,
            question_preview=question_preview,
            confidence_score=confidence_score,
            citation_count=citation_count,
            stale_source_count=stale_source_count,
            is_preview_run=is_preview_run,
        )
        db.add(log)
        await db.flush()
        return log

    async def list_eval_logs(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        outcome: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PolicyEvaluationLog]:
        q = select(PolicyEvaluationLog).where(
            PolicyEvaluationLog.organization_id == organization_id,
            PolicyEvaluationLog.is_preview_run.is_(False),
        )
        if outcome:
            q = q.where(PolicyEvaluationLog.outcome == outcome)
        q = q.order_by(PolicyEvaluationLog.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(q)
        return list(result.scalars().all())

    async def count_eval_logs(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        outcome: str | None = None,
    ) -> int:
        q = select(func.count()).where(
            PolicyEvaluationLog.organization_id == organization_id,
            PolicyEvaluationLog.is_preview_run.is_(False),
        )
        if outcome:
            q = q.where(PolicyEvaluationLog.outcome == outcome)
        result = await db.execute(q)
        return result.scalar_one()
