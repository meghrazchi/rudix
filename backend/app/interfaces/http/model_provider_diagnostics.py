"""Admin HTTP endpoints for model provider diagnostics (F221).

Endpoints:
  GET  /admin/model-providers       — provider cards with config status, capabilities,
                                       and task assignments; no secrets returned.
  POST /admin/model-providers/test  — live connectivity probe for chat or embeddings
                                       provider; rate-limited; safe fields only.

Auth: owner/admin only.
Secrets never returned — API keys, base URLs with credentials, and prompt text are
never included in any response.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.audit_events import PROVIDER_TEST_CONNECTION
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.ai.providers.capability_registry import default_capability_registry
from app.domains.ai.providers.errors import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domains.ai.providers.factory import UnknownProviderError, default_provider_factory
from app.domains.ai.providers.protocols import ChatCompletionRequest, EmbeddingRequest
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/admin/model-providers", tags=["admin-model-providers"])
_audit = AuditLogService()

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)
_ALL_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
)

# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------


class CapabilitySummary(BaseModel):
    context_window: int | None = None
    supports_json_mode: bool = True
    supports_tool_calling: bool = False
    supports_streaming: bool = True
    is_embedding_model: bool = False
    embedding_dimension: int | None = None
    cost_behavior: str = "per_token"


class ProviderCard(BaseModel):
    provider_key: str
    provider_type: str
    model_name: str
    is_configured: bool
    task_assignments: list[str]
    capability: CapabilitySummary | None = None
    reindex_required: bool = False


class ModelProviderDiagnosticsResponse(BaseModel):
    providers: list[ProviderCard]


class TestProviderRequest(BaseModel):
    provider_key: Literal["chat", "embeddings"]


class TestProviderResponse(BaseModel):
    provider_key: str
    provider_type: str
    model_name: str
    status: str
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHAT_TASK_TYPES = ["chat", "summarization", "comparison", "evaluations", "agentic"]
_EMBEDDING_TASK_TYPES = ["embeddings"]

# Timeout in seconds for the live connectivity probe
_PROBE_TIMEOUT_SECONDS = 10.0


def _build_chat_card() -> ProviderCard:
    from app.core.config import settings

    provider_type = settings.llm_default_provider
    if provider_type == "openai":
        model_name = settings.openai_llm_model
        is_configured = settings.openai_api_key is not None
    elif provider_type == "local":
        model_name = settings.local_llm_model
        is_configured = (
            settings.local_llm_base_url is not None and bool(model_name.strip())
        )
    else:
        model_name = ""
        is_configured = False

    cap = default_capability_registry.get(provider_type, model_name)
    capability: CapabilitySummary | None = None
    if cap is not None:
        capability = CapabilitySummary(
            context_window=cap.context_window,
            supports_json_mode=cap.supports_json_mode,
            supports_tool_calling=cap.supports_tool_calling,
            supports_streaming=cap.supports_streaming,
            is_embedding_model=cap.is_embedding_model,
            embedding_dimension=cap.embedding_dimension,
            cost_behavior=cap.cost_behavior.value,
        )

    return ProviderCard(
        provider_key="chat",
        provider_type=provider_type,
        model_name=model_name,
        is_configured=is_configured,
        task_assignments=_CHAT_TASK_TYPES,
        capability=capability,
        reindex_required=False,
    )


def _build_embeddings_card() -> ProviderCard:
    from app.core.config import settings

    provider_type = settings.embedding_default_provider
    if provider_type == "openai":
        model_name = settings.openai_embedding_model
        is_configured = settings.openai_api_key is not None
    elif provider_type == "local":
        model_name = settings.local_embedding_model
        is_configured = (
            settings.local_embedding_base_url is not None and bool(model_name.strip())
        )
    else:
        model_name = ""
        is_configured = False

    cap = default_capability_registry.get(provider_type, model_name)
    capability: CapabilitySummary | None = None
    reindex_required = False
    if cap is not None:
        capability = CapabilitySummary(
            context_window=cap.context_window,
            supports_json_mode=cap.supports_json_mode,
            supports_tool_calling=cap.supports_tool_calling,
            supports_streaming=cap.supports_streaming,
            is_embedding_model=cap.is_embedding_model,
            embedding_dimension=cap.embedding_dimension,
            cost_behavior=cap.cost_behavior.value,
        )
        if (
            cap.embedding_dimension is not None
            and cap.embedding_dimension != settings.qdrant_vector_size
        ):
            reindex_required = True

    return ProviderCard(
        provider_key="embeddings",
        provider_type=provider_type,
        model_name=model_name,
        is_configured=is_configured,
        task_assignments=_EMBEDDING_TASK_TYPES,
        capability=capability,
        reindex_required=reindex_required,
    )


def _classify_probe_error(exc: Exception) -> tuple[str, str]:
    """Return (error_code, safe_message) for a probe exception.

    Never returns exception details that could contain secrets or internal paths.
    """
    if isinstance(exc, UnknownProviderError):
        return "unknown_provider", "Provider type is not recognised by the server."
    if isinstance(exc, ProviderUnavailableError):
        return "configuration_error", "Provider is not configured in the environment."
    if isinstance(exc, ProviderTimeoutError):
        return "timeout", "Provider did not respond within the probe timeout."
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout", "Connection timed out during the probe."

    name = type(exc).__name__.lower()
    if "connect" in name or "connection" in name or "network" in name:
        return "unreachable", "Could not reach the provider endpoint."

    # Generic fallback — never leak exception message
    return "error", "The provider returned an unexpected error during the probe."


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ModelProviderDiagnosticsResponse)
async def list_model_providers(
    _principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
) -> ModelProviderDiagnosticsResponse:
    """Return provider cards for chat and embeddings providers.

    Shows configuration status, model names, capability summary, and task
    assignments. Never returns API keys, base URLs, or prompt text.
    Auth: any org member.
    """
    return ModelProviderDiagnosticsResponse(
        providers=[
            _build_chat_card(),
            _build_embeddings_card(),
        ]
    )


@router.post("/test", response_model=TestProviderResponse)
async def test_provider_connection(
    payload: TestProviderRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TestProviderResponse:
    """Run a live connectivity probe against the specified provider.

    Uses a minimal request (1-token completion or single-text embed) with a
    short timeout so the probe is cheap and non-destructive.
    Returns only safe fields: status, latency, and a coded error — never secrets.
    Auth: owner or admin.
    Rate-limited to the admin bucket.
    """
    from app.core.config import settings
    from uuid import UUID

    def _org_id() -> UUID | None:
        try:
            return UUID(principal.organization_id) if principal.organization_id else None
        except ValueError:
            return None

    def _user_id() -> UUID | None:
        try:
            return UUID(principal.user_id)
        except (ValueError, AttributeError):
            return None

    request_id = getattr(request.state, "request_id", None) or request.headers.get("x-request-id")

    if payload.provider_key == "chat":
        provider_type = settings.llm_default_provider
        model_name = (
            settings.openai_llm_model
            if provider_type == "openai"
            else settings.local_llm_model
        )

        start = time.monotonic()
        try:
            provider = default_provider_factory.get_chat_provider()
            req = ChatCompletionRequest(
                prompt="Respond with OK.",
                model=model_name,
                temperature=0.0,
                json_mode=False,
                max_tokens=1,
                system_message="",
            )
            await asyncio.wait_for(provider.complete(req), timeout=_PROBE_TIMEOUT_SECONDS)
            latency_ms = int((time.monotonic() - start) * 1000)
            response = TestProviderResponse(
                provider_key="chat",
                provider_type=provider_type,
                model_name=model_name,
                status="ok",
                latency_ms=latency_ms,
            )
        except (ProviderError, UnknownProviderError, asyncio.TimeoutError, Exception) as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            error_code, error_message = _classify_probe_error(exc)
            response = TestProviderResponse(
                provider_key="chat",
                provider_type=provider_type,
                model_name=model_name,
                status=error_code,
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=error_message,
            )
    else:
        # embeddings
        provider_type = settings.embedding_default_provider
        model_name = (
            settings.openai_embedding_model
            if provider_type == "openai"
            else settings.local_embedding_model
        )

        start = time.monotonic()
        try:
            provider = default_provider_factory.get_embedding_provider()
            req = EmbeddingRequest(texts=["test"], model=model_name)
            await asyncio.wait_for(provider.embed(req), timeout=_PROBE_TIMEOUT_SECONDS)
            latency_ms = int((time.monotonic() - start) * 1000)
            response = TestProviderResponse(
                provider_key="embeddings",
                provider_type=provider_type,
                model_name=model_name,
                status="ok",
                latency_ms=latency_ms,
            )
        except (ProviderError, UnknownProviderError, asyncio.TimeoutError, Exception) as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            error_code, error_message = _classify_probe_error(exc)
            response = TestProviderResponse(
                provider_key="embeddings",
                provider_type=provider_type,
                model_name=model_name,
                status=error_code,
                latency_ms=latency_ms,
                error_code=error_code,
                error_message=error_message,
            )

    org_id = _org_id()
    if org_id is not None:
        await _audit.record(
            db_session,
            organization_id=org_id,
            user_id=_user_id(),
            action=PROVIDER_TEST_CONNECTION,
            resource_type="model_provider",
            request_id=request_id,
            metadata={
                "provider_key": payload.provider_key,
                "provider_type": provider_type,
                "status": response.status,
                "latency_ms": response.latency_ms,
                "error_code": response.error_code,
            },
        )
        await db_session.commit()

    return response
