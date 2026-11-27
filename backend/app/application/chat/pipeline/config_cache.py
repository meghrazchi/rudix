"""Cached configuration reads of stage 2 (R05-05, 0.4.0 deferral).

Each read is cached as a plain DTO under the organisation scope through
``app.core.cache.get_or_load`` and invalidated on commit by
``app.core.cache_invalidation`` (any write to the rows below bumps the organisation's
version, which orphans every namespace of that organisation):

=====================  =====================================  ============================
namespace              rows read                              TTL setting
=====================  =====================================  ============================
``ai_policy``          OrgAiResponsePolicy (active) and its   CACHE_TTL_POLICIES_SECONDS
                       CollectionAiResponsePolicyOverride
``rag_profile``        RagProfileCollectionOverride,          CACHE_TTL_PROFILES_SECONDS
                       RagProfile (default)
``answer_prompt``      PromptTemplate, PromptTemplateVersion  CACHE_TTL_PROFILES_SECONDS
=====================  =====================================  ============================

The model profile (``model_profile``), the chat tool policy (``chat_tool_policy``), quota
policy limits (``quota_policy``), and verified-answer candidates
(``verified_answer_candidates``) are cached next to their repositories. None of these reads
depend on rows with a NULL organisation id: system defaults come from settings and code and
are computed on every call. Redis down, a missing client, or ``CACHE_ENABLED=false`` reads
the database.
"""

from uuid import UUID

from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.controls import _resolve_answer_prompt_version
from app.application.chat.pipeline.deps import ChatPipelineDeps
from app.application.chat.pipeline.snapshots import PromptVersionSnapshot, RagProfileSnapshot
from app.core.cache import OrgScope, get_or_load
from app.core.cache_invalidation import has_pending_org_invalidation
from app.core.config import settings
from app.domains.ai_response_policy.services.policy_engine import EffectivePolicy
from app.domains.rag_profiles.services.rag_profile_service import resolve_profile_for_context

NAMESPACE_AI_POLICY = "ai_policy"
NAMESPACE_RAG_PROFILE = "rag_profile"
NAMESPACE_ANSWER_PROMPT = "answer_prompt"

_POLICY_ADAPTER: TypeAdapter[EffectivePolicy] = TypeAdapter(EffectivePolicy)
_PROMPT_ADAPTER: TypeAdapter[PromptVersionSnapshot] = TypeAdapter(PromptVersionSnapshot)


class ResolvedRagProfile(BaseModel):
    profile: RagProfileSnapshot | None = None
    source: str = "system_default"


_RAG_PROFILE_ADAPTER: TypeAdapter[ResolvedRagProfile] = TypeAdapter(ResolvedRagProfile)


async def effective_ai_policy(
    db_session: AsyncSession,
    deps: ChatPipelineDeps,
    *,
    organization_id: UUID,
    collection_id: UUID | None,
) -> EffectivePolicy:
    """The merged AI response policy (org policy plus the collection override)."""

    async def load() -> EffectivePolicy:
        org_policy = await deps.ai_policy_repo.get_active(
            db_session, organization_id=organization_id
        )
        override = None
        if org_policy is not None and collection_id is not None:
            override = await deps.ai_policy_repo.get_collection_override(
                db_session, org_policy_id=org_policy.id, collection_id=collection_id
            )
        return deps.ai_policy_engine.resolve(org_policy, override)

    return await get_or_load(
        scope=OrgScope(organization_id),
        namespace=NAMESPACE_AI_POLICY,
        key_id=f"effective:{collection_id or 'org'}",
        ttl=settings.cache_ttl_policies_seconds,
        adapter=_POLICY_ADAPTER,
        loader=load,
    )


async def rag_profile_for_context(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    collection_id: UUID | None,
) -> ResolvedRagProfile:
    """``resolve_profile_for_context`` as a snapshot and its source."""

    async def load() -> ResolvedRagProfile:
        profile, source = await resolve_profile_for_context(
            db_session, organization_id=organization_id, collection_id=collection_id
        )
        snapshot = RagProfileSnapshot.from_model(profile) if profile is not None else None
        return ResolvedRagProfile(profile=snapshot, source=source)

    return await get_or_load(
        scope=OrgScope(organization_id),
        namespace=NAMESPACE_RAG_PROFILE,
        key_id=f"context:{collection_id or 'org'}",
        ttl=settings.cache_ttl_profiles_seconds,
        adapter=_RAG_PROFILE_ADAPTER,
        loader=load,
    )


async def answer_prompt_version(
    db_session: AsyncSession, *, organization_id: UUID
) -> PromptVersionSnapshot:
    """The active published answer-generation prompt version.

    A missing or unpublished template raises (``prompt_template_unavailable``) and nothing
    is cached for it. The first call of an organisation seeds its default templates in the
    open transaction; that snapshot is returned but not cached, because a rollback would
    leave a cached version id that was never committed. The commit bumps the cache version,
    so the next request loads (and caches) once more.
    """

    async def load() -> PromptVersionSnapshot:
        version = await _resolve_answer_prompt_version(db_session, organization_id=organization_id)
        snapshot = PromptVersionSnapshot.from_model(version)
        if has_pending_org_invalidation(db_session, organization_id):
            raise _UncommittedLoad(snapshot)
        return snapshot

    try:
        return await get_or_load(
            scope=OrgScope(organization_id),
            namespace=NAMESPACE_ANSWER_PROMPT,
            key_id="answer_generation",
            ttl=settings.cache_ttl_profiles_seconds,
            adapter=_PROMPT_ADAPTER,
            loader=load,
        )
    except _UncommittedLoad as uncommitted:
        return uncommitted.value


class _UncommittedLoad(Exception):
    """A loaded value that depends on writes the open transaction has not committed."""

    def __init__(self, value: PromptVersionSnapshot) -> None:
        super().__init__("uncommitted_load")
        self.value = value
