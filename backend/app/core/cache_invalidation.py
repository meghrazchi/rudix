"""Post-commit cache invalidation (R04-05).

Writes that change cached state record the affected organisation and user ids in
``session.info`` (ORM flushes through ``after_flush``; Core ``UPDATE``/``DELETE`` statements
through explicit ``mark_dirty`` calls). ``after_commit`` then bumps each scope's version key
synchronously through ``sqlalchemy.util.await_only``, so ``await session.commit()`` returns
only after Redis has been updated. ``after_rollback`` discards the pending bumps.

When Redis is unavailable or a bump fails, cached values stay valid only until their TTL
expires (seconds, see ``CACHE_TTL_*``); the failure is counted in
``rudix_cache_invalidations_total{result="error"|"unavailable"}``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect, select
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction, UOWTransaction
from sqlalchemy.orm.util import identity_key
from sqlalchemy.util import await_only

from app.clients import redis_client as redis_module
from app.core import cache
from app.core.logging import get_logger
from app.models.agent_policy import AgentToolPolicyOverride
from app.models.ai_response_policy import CollectionAiResponsePolicyOverride, OrgAiResponsePolicy
from app.models.auth_session import AuthRefreshSession
from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.feature_flags import OrgFeatureFlagOverride
from app.models.model_profile import OrgModelProfile
from app.models.organization_member import OrganizationMember
from app.models.prompt_template import PromptTemplate, PromptTemplateVersion
from app.models.quotas import OrgQuotaOverride, OrgQuotaPolicy
from app.models.rag_profile import RagProfile, RagProfileCollectionOverride, RagProfileVersion
from app.models.user import User
from app.models.verified_answer import VerifiedAnswer, VerifiedAnswerCitation

logger = get_logger("core.cache_invalidation")

PENDING_INFO_KEY = "rudix_cache_pending_invalidations"
_USER_CACHED_FIELDS = ("is_active", "email", "organization_id")

_installed = False
# A custom-role permission whose role (and so organisation) could not be resolved.
CACHE_UNRESOLVED = cache.CACHE_INVALIDATIONS_TOTAL.labels(scope="org", result="unresolved")


def _pending(session: Session) -> dict[str, set[str]]:
    pending = session.info.get(PENDING_INFO_KEY)
    if pending is None:
        pending = {"org": set(), "user": set()}
        session.info[PENDING_INFO_KEY] = pending
    return pending  # type: ignore[no-any-return]


def mark_dirty(
    session: Session | AsyncSession,
    *,
    org_ids: Iterable[UUID | str | None] = (),
    user_ids: Iterable[UUID | str | None] = (),
) -> None:
    """Record scopes whose cached values must be invalidated when ``session`` commits."""
    sync_session = session.sync_session if isinstance(session, AsyncSession) else session
    pending = _pending(sync_session)
    pending["org"].update(str(org_id) for org_id in org_ids if org_id is not None)
    pending["user"].update(str(user_id) for user_id in user_ids if user_id is not None)


def has_pending_org_invalidation(session: Session | AsyncSession, org_id: UUID | str) -> bool:
    """Whether ``session``'s open transaction has flushed writes that bump ``org_id``.

    A value loaded after such a write may contain rows that are not committed yet; it must
    not be cached under the current version (a rollback would leave it there, R05-05).
    """
    sync_session = session.sync_session if isinstance(session, AsyncSession) else session
    pending = sync_session.info.get(PENDING_INFO_KEY)
    return bool(pending) and str(org_id) in pending.get("org", ())


def _loaded(instance: Any, name: str) -> Any:
    """Read a loaded attribute without triggering a lazy load inside the flush."""
    return inspect(instance).dict.get(name)


def _user_fields_changed(instance: User) -> bool:
    attrs = inspect(instance).attrs
    return any(attrs[name].history.has_changes() for name in _USER_CACHED_FIELDS)


def _revocation_changed(instance: AuthRefreshSession) -> bool:
    return bool(inspect(instance).attrs["revoked_at"].history.has_changes())


def _parent_org(session: Session, parent_model: type[Any], parent_id: UUID | None) -> UUID | None:
    """Organisation of a parent row (custom role, AI policy, RAG profile, template, card)."""
    if parent_id is None:
        return None
    parent = session.identity_map.get(identity_key(parent_model, parent_id))
    if parent is not None:
        return _loaded(parent, "organization_id")  # type: ignore[no-any-return]
    # Not in the identity map: read it on the flush connection (no autoflush).
    result = session.connection().execute(
        select(parent_model.organization_id).where(parent_model.id == parent_id)
    )
    return result.scalar_one_or_none()  # type: ignore[no-any-return]


def _custom_role_org(session: Session, custom_role_id: UUID | None) -> UUID | None:
    return _parent_org(session, CustomRole, custom_role_id)


# R05-05 (0.4.0 deferral): chat configuration cached under the organisation scope. Every row
# carries a non-null organisation id (directly or through its parent); system defaults live
# in settings and code and are never cached as rows.
_ORG_CONFIG_MODELS: tuple[type[Any], ...] = (
    OrgAiResponsePolicy,
    AgentToolPolicyOverride,
    OrgModelProfile,
    RagProfile,
    RagProfileCollectionOverride,
    PromptTemplate,
    OrgQuotaPolicy,
    OrgQuotaOverride,
    VerifiedAnswer,
)
# Child rows: (model, foreign-key attribute, parent model carrying organization_id).
_ORG_CONFIG_CHILDREN: tuple[tuple[type[Any], str, type[Any]], ...] = (
    (CollectionAiResponsePolicyOverride, "org_policy_id", OrgAiResponsePolicy),
    (RagProfileVersion, "rag_profile_id", RagProfile),
    (PromptTemplateVersion, "prompt_template_id", PromptTemplate),
    (VerifiedAnswerCitation, "verified_answer_id", VerifiedAnswer),
)


def _collect_org_config(session: Session, instance: Any) -> bool:
    if isinstance(instance, _ORG_CONFIG_MODELS):
        mark_dirty(session, org_ids=[_loaded(instance, "organization_id")])
        return True
    for model, parent_attr, parent_model in _ORG_CONFIG_CHILDREN:
        if isinstance(instance, model):
            org_id = _parent_org(session, parent_model, _loaded(instance, parent_attr))
            if org_id is None:
                CACHE_UNRESOLVED.inc()
            mark_dirty(session, org_ids=[org_id])
            return True
    return False


def _collect(session: Session, instance: Any, *, is_dirty: bool) -> None:
    if _collect_org_config(session, instance):
        return
    if isinstance(instance, OrganizationMember):
        mark_dirty(
            session,
            org_ids=[_loaded(instance, "organization_id")],
            user_ids=[_loaded(instance, "user_id")],
        )
    elif isinstance(instance, User):
        if not is_dirty or _user_fields_changed(instance):
            mark_dirty(session, user_ids=[_loaded(instance, "id")])
    elif isinstance(instance, CustomRole):
        mark_dirty(session, org_ids=[_loaded(instance, "organization_id")])
    elif isinstance(instance, CustomRolePermission):
        org_id = _custom_role_org(session, _loaded(instance, "custom_role_id"))
        if org_id is None:
            CACHE_UNRESOLVED.inc()
        mark_dirty(session, org_ids=[org_id])
    elif isinstance(instance, OrgFeatureFlagOverride):
        mark_dirty(session, org_ids=[_loaded(instance, "organization_id")])
    elif isinstance(instance, AuthRefreshSession):
        if not is_dirty or _revocation_changed(instance):
            mark_dirty(session, user_ids=[_loaded(instance, "user_id")])


def _after_flush(session: Session, flush_context: UOWTransaction) -> None:
    del flush_context
    for instance in session.new:
        _collect(session, instance, is_dirty=False)
    for instance in session.dirty:
        _collect(session, instance, is_dirty=True)
    for instance in session.deleted:
        _collect(session, instance, is_dirty=False)


async def _bump(client: Any, kind: str, scope_id: str) -> None:
    key = cache.version_key(kind, scope_id)
    try:
        # SET NX first so a missing (evicted) key restarts from the clock, never from 1.
        await cache._call(client.set(key, cache.now_ms(), nx=True))
        await cache._call(client.incr(key))
    except Exception as exc:
        cache.CACHE_INVALIDATIONS_TOTAL.labels(scope=kind, result="error").inc()
        logger.warning(
            "cache.invalidation.failed",
            scope=kind,
            scope_id=scope_id,
            error=exc.__class__.__name__,
        )
        return
    cache.CACHE_INVALIDATIONS_TOTAL.labels(scope=kind, result="ok").inc()


async def apply_invalidations(pending: dict[str, set[str]]) -> None:
    """Bump every pending version key (concurrently); never raises."""
    targets = [(kind, scope_id) for kind, ids in pending.items() for scope_id in sorted(ids)]
    if not targets:
        return
    client = redis_module.redis_client
    if client is None:
        for kind, _ in targets:
            cache.CACHE_INVALIDATIONS_TOTAL.labels(scope=kind, result="unavailable").inc()
        return
    await asyncio.gather(*(_bump(client, kind, scope_id) for kind, scope_id in targets))


def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        # A SAVEPOINT release is not a commit. Bumping now would let a concurrent request
        # read the new version, load the rows the outer transaction has not committed yet
        # (the old values), and cache them under that version until the TTL expires.
        return
    pending = session.info.pop(PENDING_INFO_KEY, None)
    if not pending or not any(pending.values()):
        return
    if redis_module.redis_client is None:
        # Nothing to await; count without needing an event loop.
        for kind, ids in pending.items():
            for _ in ids:
                cache.CACHE_INVALIDATIONS_TOTAL.labels(scope=kind, result="unavailable").inc()
        return
    coroutine = apply_invalidations(pending)
    try:
        await_only(coroutine)
    except MissingGreenlet:
        # Sync Session outside the asyncio greenlet bridge: cannot await Redis here.
        coroutine.close()
        for kind, ids in pending.items():
            for _ in ids:
                cache.CACHE_INVALIDATIONS_TOTAL.labels(scope=kind, result="skipped").inc()
        logger.warning("cache.invalidation.skipped", reason="no_async_context")


def _after_rollback(session: Session) -> None:
    if session.in_nested_transaction():
        # ROLLBACK TO SAVEPOINT: the outer transaction's writes may still commit, so keep
        # every pending bump (an extra bump is harmless; a lost one serves stale data).
        return
    session.info.pop(PENDING_INFO_KEY, None)


def _after_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    """Drop bumps left by a root transaction that ended without committing.

    Covers a full rollback while a SAVEPOINT was open (``_after_rollback`` keeps the bumps
    then) and ``close()``; after a commit ``_after_commit`` has already taken them.
    """
    if transaction.parent is None and not transaction.nested:
        session.info.pop(PENDING_INFO_KEY, None)


def install_cache_invalidation_listeners() -> None:
    """Register the Session listeners once per process (idempotent)."""
    global _installed
    if _installed:
        return
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    event.listen(Session, "after_transaction_end", _after_transaction_end)
    _installed = True
