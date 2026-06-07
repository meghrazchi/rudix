"""Business logic for model provider settings management.

Handles upsert with change-log snapshotting and effective-policy resolution.
Secrets (API keys) are never stored here — only a boolean presence flag is
derived from the settings singleton at call time.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.domains.model_provider.repositories.model_provider import (
    ModelProviderRepository,
)
from app.models.model_provider_settings import OrgModelProviderSettings

_repo = ModelProviderRepository()

# System-level defaults applied when an org has no overrides
SYSTEM_DEFAULT_PROVIDER = "openai"
SYSTEM_DEFAULT_TIMEOUT_SECONDS = 30
SYSTEM_DEFAULT_MAX_RETRIES = 2


def _llm_key_configured() -> bool:
    """Return True when an LLM API key is present in the environment."""
    key = app_settings.openai_api_key
    if key is None:
        return False
    secret_val = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
    return bool(secret_val and secret_val.strip())


def _settings_to_snapshot(s: OrgModelProviderSettings) -> dict:
    return {
        "provider": s.provider,
        "llm_model": s.llm_model,
        "embedding_model": s.embedding_model,
        "max_tokens": s.max_tokens,
        "timeout_seconds": s.timeout_seconds,
        "max_retries": s.max_retries,
        "fallback_model": s.fallback_model,
        "disabled_models": list(s.disabled_models or []),
    }


async def upsert_settings_with_log(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    provider: str | None,
    llm_model: str | None,
    embedding_model: str | None,
    max_tokens: int | None,
    timeout_seconds: int | None,
    max_retries: int | None,
    fallback_model: str | None,
    disabled_models: list[str],
    updated_by_id: UUID | None,
    change_note: str | None,
) -> OrgModelProviderSettings:
    """Upsert org model provider settings and append a change-log entry."""
    settings = await _repo.upsert_settings(
        db_session,
        organization_id=organization_id,
        provider=provider,
        llm_model=llm_model,
        embedding_model=embedding_model,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        fallback_model=fallback_model,
        disabled_models=disabled_models,
        updated_by_id=updated_by_id,
        bump_version=True,
    )
    await _repo.create_change_log_entry(
        db_session,
        organization_id=organization_id,
        settings_id=settings.id,
        version_number=settings.version,
        settings_snapshot=_settings_to_snapshot(settings),
        change_note=change_note,
        changed_by_id=updated_by_id,
    )
    return settings


async def delete_settings_with_log(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    deleted_by_id: UUID | None,
    change_note: str | None,
) -> None:
    """Remove org override settings (resets org to system defaults)."""
    settings = await _repo.get_settings(db_session, organization_id=organization_id)
    if settings is None:
        return

    # Record a "reset" snapshot before deleting
    await _repo.create_change_log_entry(
        db_session,
        organization_id=organization_id,
        settings_id=settings.id,
        version_number=settings.version + 1,
        settings_snapshot={**_settings_to_snapshot(settings), "_action": "reset"},
        change_note=change_note or "Reset to system defaults",
        changed_by_id=deleted_by_id,
    )
    await _repo.delete_settings(db_session, settings)


def build_effective_policy(
    settings: OrgModelProviderSettings | None,
    organization_id: str,
) -> dict:
    """Merge org settings over system defaults; never expose secrets."""
    llm_key_ok = _llm_key_configured()
    sys_llm_model = getattr(app_settings, "openai_llm_model", "gpt-4o")
    sys_embedding_model = getattr(app_settings, "openai_embedding_model", "text-embedding-3-small")

    if settings is None:
        return {
            "organization_id": organization_id,
            "provider": SYSTEM_DEFAULT_PROVIDER,
            "llm_model": sys_llm_model,
            "embedding_model": sys_embedding_model,
            "max_tokens": None,
            "timeout_seconds": SYSTEM_DEFAULT_TIMEOUT_SECONDS,
            "max_retries": SYSTEM_DEFAULT_MAX_RETRIES,
            "fallback_model": None,
            "disabled_models": [],
            "llm_key_configured": llm_key_ok,
            "source": "system_default",
            "version": 0,
        }

    return {
        "organization_id": organization_id,
        "provider": settings.provider or SYSTEM_DEFAULT_PROVIDER,
        "llm_model": settings.llm_model or sys_llm_model,
        "embedding_model": settings.embedding_model or sys_embedding_model,
        "max_tokens": settings.max_tokens,
        "timeout_seconds": settings.timeout_seconds or SYSTEM_DEFAULT_TIMEOUT_SECONDS,
        "max_retries": settings.max_retries
        if settings.max_retries is not None
        else SYSTEM_DEFAULT_MAX_RETRIES,
        "fallback_model": settings.fallback_model,
        "disabled_models": list(settings.disabled_models or []),
        "llm_key_configured": llm_key_ok,
        "source": "org_override",
        "version": settings.version,
    }
