"""Business logic for RAG profile management.

Handles default-flag bookkeeping, version snapshot creation, and config
validation beyond what Pydantic covers (e.g. cross-field rules).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.rag_profiles.repositories.rag_profiles import RagProfileRepository
from app.models.rag_profile import RagProfile, RagProfileVersion

_repo = RagProfileRepository()

# Default config applied when a profile is created without explicit settings
SYSTEM_DEFAULT_CONFIG: dict = {
    "top_k": 10,
    "rerank_enabled": False,
    "rerank_model": None,
    "confidence_threshold": 0.0,
    "citation_strictness": "moderate",
    "model_provider": None,
    "model_name": None,
    "prompt_template": None,
    "safety_mode": "standard",
    "chunk_filter": None,
    "max_context_tokens": None,
}


async def create_profile_with_version(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    name: str,
    description: str | None,
    config: dict,
    set_as_default: bool,
    created_by_id: UUID | None,
    change_note: str | None,
) -> RagProfile:
    """Create a new profile, optionally promoting it to default, and write v1 snapshot."""
    if set_as_default:
        await _repo.clear_default_flag(db_session, organization_id=organization_id)

    profile = await _repo.create_profile(
        db_session,
        organization_id=organization_id,
        name=name,
        description=description,
        config=config,
        is_default=set_as_default,
        created_by_id=created_by_id,
    )

    await _repo.create_version_snapshot(
        db_session,
        rag_profile_id=profile.id,
        version_number=1,
        config_snapshot=dict(config),
        change_note=change_note or "Initial version",
        changed_by_id=created_by_id,
    )
    return profile


async def update_profile_with_version(
    db_session: AsyncSession,
    profile: RagProfile,
    *,
    name: str | None,
    description: str | None,
    config: dict | None,
    set_as_default: bool | None,
    updated_by_id: UUID | None,
    change_note: str | None,
    organization_id: UUID,
) -> RagProfile:
    """Update a profile, bump its version counter, snapshot the new config."""
    if set_as_default is True and not profile.is_default:
        await _repo.clear_default_flag(
            db_session,
            organization_id=organization_id,
            exclude_id=profile.id,
        )

    bump = config is not None
    profile = await _repo.update_profile(
        db_session,
        profile,
        name=name,
        description=description,
        config=config,
        is_default=set_as_default,
        updated_by_id=updated_by_id,
        bump_version=bump,
    )

    if bump:
        await _repo.create_version_snapshot(
            db_session,
            rag_profile_id=profile.id,
            version_number=profile.version,
            config_snapshot=dict(profile.config),
            change_note=change_note,
            changed_by_id=updated_by_id,
        )
    return profile


async def rollback_to_version(
    db_session: AsyncSession,
    profile: RagProfile,
    version: RagProfileVersion,
    *,
    rolled_back_by_id: UUID | None,
    change_note: str | None,
    organization_id: UUID,
) -> RagProfile:
    """Restore a profile's config from an old version snapshot and record a new snapshot."""
    restored_config = dict(version.config_snapshot)
    profile = await _repo.update_profile(
        db_session,
        profile,
        config=restored_config,
        updated_by_id=rolled_back_by_id,
        bump_version=True,
    )
    await _repo.create_version_snapshot(
        db_session,
        rag_profile_id=profile.id,
        version_number=profile.version,
        config_snapshot=restored_config,
        change_note=change_note or f"Rollback to version {version.version_number}",
        changed_by_id=rolled_back_by_id,
    )
    return profile


async def resolve_profile_for_context(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    collection_id: UUID | None,
) -> tuple[RagProfile | None, str]:
    """Return (profile, source) for the given context.

    source is one of: 'collection_override', 'org_default', 'system_default'.
    Returns (None, 'system_default') when no profiles exist.
    """
    repo = RagProfileRepository()

    if collection_id is not None:
        override = await repo.get_collection_override(
            db_session,
            organization_id=organization_id,
            collection_id=collection_id,
        )
        if override is not None:
            profile = await repo.get_profile(
                db_session,
                profile_id=override.rag_profile_id,
                organization_id=organization_id,
            )
            if profile is not None and not profile.is_archived:
                return profile, "collection_override"

    default_profile = await repo.get_default_profile(db_session, organization_id=organization_id)
    if default_profile is not None:
        return default_profile, "org_default"

    return None, "system_default"
