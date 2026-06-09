"""Profile resolution and policy validation service (F220).

Precedence (lowest → highest):
  1. env_default  — derived from app_settings
  2. org_profile  — row in org_model_profiles for the org + task_type
  3. request_override — caller-supplied, only when feature flag allows

Secrets (API keys) never flow through this layer.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.domains.ai.profile.schemas import (
    EMBEDDING_TASKS,
    JSON_MODE_REQUIRED_TASKS,
    ALL_TASK_TYPES,
    EffectiveModelPolicyResponse,
    ModelProfileResponse,
    ProfileSource,
    ProfileValidationIssue,
    ResolvedTaskProfile,
    TaskType,
    ValidateProfileRequest,
    ValidateProfileResponse,
)
from app.models.model_profile import OrgModelProfile, OrgModelProfileChangeLog

# ---------------------------------------------------------------------------
# Env-level defaults per task type
# ---------------------------------------------------------------------------

_CHAT_TASKS = {
    TaskType.chat,
    TaskType.summarization,
    TaskType.comparison,
    TaskType.evaluations,
    TaskType.agentic,
}


def _env_default_for_task(task_type: TaskType) -> ResolvedTaskProfile:
    if task_type in _CHAT_TASKS:
        provider = getattr(app_settings, "llm_default_provider", "openai")
        model = getattr(app_settings, "openai_llm_model", "gpt-4o")
        if provider == "local":
            model = getattr(app_settings, "local_llm_model", "") or model
        json_mode = task_type in JSON_MODE_REQUIRED_TASKS
        return ResolvedTaskProfile(
            task_type=task_type,
            provider_type=provider,
            base_model=model,
            max_tokens=None,
            temperature=None,
            json_mode=json_mode,
            streaming=True,
            fallback_provider_key=None,
            source=ProfileSource.env_default,
            version=0,
        )
    # embeddings
    provider = getattr(app_settings, "embedding_default_provider", "openai")
    model = getattr(app_settings, "openai_embedding_model", "text-embedding-3-small")
    if provider == "local":
        model = getattr(app_settings, "local_embedding_model", "") or model
    return ResolvedTaskProfile(
        task_type=task_type,
        provider_type=provider,
        base_model=model,
        max_tokens=None,
        temperature=None,
        json_mode=False,
        streaming=False,
        fallback_provider_key=None,
        source=ProfileSource.env_default,
        version=0,
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_profile(
    db: AsyncSession,
    *,
    organization_id: UUID,
    task_type: TaskType,
) -> OrgModelProfile | None:
    result = await db.execute(
        select(OrgModelProfile).where(
            OrgModelProfile.organization_id == organization_id,
            OrgModelProfile.task_type == task_type.value,
        )
    )
    return result.scalar_one_or_none()


async def list_profiles(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> list[OrgModelProfile]:
    result = await db.execute(
        select(OrgModelProfile)
        .where(OrgModelProfile.organization_id == organization_id)
        .order_by(OrgModelProfile.task_type)
    )
    return list(result.scalars().all())


async def upsert_profile(
    db: AsyncSession,
    *,
    organization_id: UUID,
    task_type: TaskType,
    profile_name: str,
    provider_type: str,
    base_model: str,
    context_window: int | None,
    max_tokens: int | None,
    temperature: float | None,
    json_mode: bool,
    streaming: bool,
    fallback_provider_key: str | None,
    is_experimental: bool,
    cost_metadata: dict,
    updated_by_id: UUID | None,
    change_note: str | None,
) -> OrgModelProfile:
    existing = await get_profile(db, organization_id=organization_id, task_type=task_type)
    if existing is None:
        profile = OrgModelProfile(
            organization_id=organization_id,
            task_type=task_type.value,
            profile_name=profile_name,
            provider_type=provider_type,
            base_model=base_model,
            context_window=context_window,
            max_tokens=max_tokens,
            temperature=Decimal(str(temperature)) if temperature is not None else None,
            json_mode=json_mode,
            streaming=streaming,
            fallback_provider_key=fallback_provider_key,
            is_experimental=is_experimental,
            cost_metadata=cost_metadata,
            version=1,
            updated_by_id=updated_by_id,
        )
        db.add(profile)
        await db.flush()
    else:
        existing.profile_name = profile_name
        existing.provider_type = provider_type
        existing.base_model = base_model
        existing.context_window = context_window
        existing.max_tokens = max_tokens
        existing.temperature = (
            Decimal(str(temperature)) if temperature is not None else None
        )
        existing.json_mode = json_mode
        existing.streaming = streaming
        existing.fallback_provider_key = fallback_provider_key
        existing.is_experimental = is_experimental
        existing.cost_metadata = cost_metadata
        existing.version = existing.version + 1
        existing.updated_by_id = updated_by_id
        profile = existing

    log_entry = OrgModelProfileChangeLog(
        organization_id=organization_id,
        org_model_profile_id=profile.id,
        task_type=task_type.value,
        version_number=profile.version,
        profile_snapshot=_profile_snapshot(profile),
        change_note=change_note,
        changed_by_id=updated_by_id,
    )
    db.add(log_entry)
    return profile


async def delete_profile(
    db: AsyncSession,
    *,
    organization_id: UUID,
    task_type: TaskType,
    deleted_by_id: UUID | None,
    change_note: str | None,
) -> bool:
    profile = await get_profile(db, organization_id=organization_id, task_type=task_type)
    if profile is None:
        return False

    log_entry = OrgModelProfileChangeLog(
        organization_id=organization_id,
        org_model_profile_id=profile.id,
        task_type=task_type.value,
        version_number=profile.version + 1,
        profile_snapshot={**_profile_snapshot(profile), "_action": "deleted"},
        change_note=change_note or "Profile removed — reverted to env default",
        changed_by_id=deleted_by_id,
    )
    db.add(log_entry)
    await db.delete(profile)
    return True


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _profile_to_resolved(profile: OrgModelProfile) -> ResolvedTaskProfile:
    temp = float(profile.temperature) if profile.temperature is not None else None
    return ResolvedTaskProfile(
        task_type=TaskType(profile.task_type),
        provider_type=profile.provider_type,
        base_model=profile.base_model,
        max_tokens=profile.max_tokens,
        temperature=temp,
        json_mode=profile.json_mode,
        streaming=profile.streaming,
        fallback_provider_key=profile.fallback_provider_key,
        source=ProfileSource.org_profile,
        version=profile.version,
    )


async def resolve_effective_policy(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> EffectiveModelPolicyResponse:
    org_profiles = await list_profiles(db, organization_id=organization_id)
    profile_map: dict[str, OrgModelProfile] = {p.task_type: p for p in org_profiles}

    resolved: list[ResolvedTaskProfile] = []
    for task_type in ALL_TASK_TYPES:
        if task_type.value in profile_map:
            resolved.append(_profile_to_resolved(profile_map[task_type.value]))
        else:
            resolved.append(_env_default_for_task(task_type))

    return EffectiveModelPolicyResponse(
        organization_id=str(organization_id),
        profiles=resolved,
        feature_local_llm_enabled=app_settings.feature_enable_local_llm_profiles,
        feature_local_embeddings_enabled=app_settings.feature_enable_local_embedding_profiles,
        feature_fallback_enabled=app_settings.feature_enable_provider_fallback,
        feature_request_override_enabled=app_settings.feature_allow_request_model_override,
    )


# ---------------------------------------------------------------------------
# Policy validation
# ---------------------------------------------------------------------------


def validate_profile(request: ValidateProfileRequest) -> ValidateProfileResponse:
    issues: list[ProfileValidationIssue] = []

    # Feature flag guard: local provider types
    if request.provider_type == "local":
        if request.task_type in EMBEDDING_TASKS:
            if not app_settings.feature_enable_local_embedding_profiles:
                issues.append(
                    ProfileValidationIssue(
                        field="provider_type",
                        code="local_embeddings_disabled",
                        message=(
                            "Local embedding profiles are disabled. "
                            "Enable FEATURE_ENABLE_LOCAL_EMBEDDING_PROFILES."
                        ),
                    )
                )
        else:
            if not app_settings.feature_enable_local_llm_profiles:
                issues.append(
                    ProfileValidationIssue(
                        field="provider_type",
                        code="local_llm_disabled",
                        message=(
                            "Local LLM profiles are disabled. "
                            "Enable FEATURE_ENABLE_LOCAL_LLM_PROFILES."
                        ),
                    )
                )

    # JSON mode guard
    if request.task_type in JSON_MODE_REQUIRED_TASKS and not request.json_mode:
        issues.append(
            ProfileValidationIssue(
                field="json_mode",
                code="json_mode_required",
                message=(
                    f"Task type '{request.task_type.value}' requires json_mode=true "
                    "to produce structured outputs."
                ),
            )
        )

    # Embedding task guards
    if request.task_type in EMBEDDING_TASKS and request.json_mode:
        issues.append(
            ProfileValidationIssue(
                field="json_mode",
                code="json_mode_invalid_for_embeddings",
                message="json_mode is not applicable to embedding task types.",
            )
        )

    # Experimental profile guard
    if request.is_experimental:
        if request.task_type not in {TaskType.evaluations}:
            issues.append(
                ProfileValidationIssue(
                    field="is_experimental",
                    code="experimental_task_type_restricted",
                    message=(
                        "Experimental profiles are only permitted for the "
                        "'evaluations' task type."
                    ),
                )
            )
        if not app_settings.feature_enable_experimental_profiles:
            issues.append(
                ProfileValidationIssue(
                    field="is_experimental",
                    code="experimental_profiles_disabled",
                    message=(
                        "Experimental profiles are disabled. "
                        "Enable FEATURE_ENABLE_EXPERIMENTAL_PROFILES."
                    ),
                )
            )

    # Fallback guard
    if (
        request.fallback_provider_key is not None
        and not app_settings.feature_enable_provider_fallback
    ):
        issues.append(
            ProfileValidationIssue(
                field="fallback_provider_key",
                code="fallback_disabled",
                message=(
                    "Provider fallback is disabled. "
                    "Enable FEATURE_ENABLE_PROVIDER_FALLBACK."
                ),
            )
        )

    return ValidateProfileResponse(valid=len(issues) == 0, issues=issues)


# ---------------------------------------------------------------------------
# Model → response serialization
# ---------------------------------------------------------------------------


def profile_to_response(profile: OrgModelProfile) -> ModelProfileResponse:
    temp = float(profile.temperature) if profile.temperature is not None else None
    return ModelProfileResponse(
        profile_id=str(profile.id),
        organization_id=str(profile.organization_id),
        profile_name=profile.profile_name,
        task_type=TaskType(profile.task_type),
        provider_type=profile.provider_type,
        base_model=profile.base_model,
        context_window=profile.context_window,
        max_tokens=profile.max_tokens,
        temperature=temp,
        json_mode=profile.json_mode,
        streaming=profile.streaming,
        fallback_provider_key=profile.fallback_provider_key,
        is_active=profile.is_active,
        is_experimental=profile.is_experimental,
        cost_metadata=dict(profile.cost_metadata or {}),
        version=profile.version,
        updated_by_id=str(profile.updated_by_id) if profile.updated_by_id else None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _profile_snapshot(profile: OrgModelProfile) -> dict:
    return {
        "profile_name": profile.profile_name,
        "task_type": profile.task_type,
        "provider_type": profile.provider_type,
        "base_model": profile.base_model,
        "context_window": profile.context_window,
        "max_tokens": profile.max_tokens,
        "temperature": str(profile.temperature) if profile.temperature is not None else None,
        "json_mode": profile.json_mode,
        "streaming": profile.streaming,
        "fallback_provider_key": profile.fallback_provider_key,
        "is_experimental": profile.is_experimental,
    }
