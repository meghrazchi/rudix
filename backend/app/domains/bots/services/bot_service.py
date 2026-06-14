from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.bots.repositories.bots import BotRepository
from app.domains.bots.schemas.bots import BotAskResponse
from app.domains.bots.services.adapters import BotAskEvent
from app.domains.bots.services.rate_limit import (
    BotRateLimitExceededError,
    BotRateLimitService,
    BotRateLimitUnavailableError,
)
from app.domains.bots.services.rendering import BotResponseRenderer
from app.domains.chat.schemas.chat import ChatQueryRequest, SourceScopeRequest
from app.models.bot import BotInstallation


class _InternalChatRequest:
    def __init__(self, *, request_id: str | None) -> None:
        self.state = SimpleNamespace(request_id=request_id)
        self.headers: dict[str, str] = {}


class BotAskService:
    def __init__(
        self,
        *,
        repository: BotRepository | None = None,
        rate_limiter: BotRateLimitService | None = None,
        renderer: BotResponseRenderer | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        self._repository = repository or BotRepository()
        self._rate_limiter = rate_limiter or BotRateLimitService()
        self._renderer = renderer or BotResponseRenderer()
        self._audit_service = audit_service or AuditLogService()

    async def handle_ask_event(
        self,
        session: AsyncSession,
        *,
        event: BotAskEvent,
        request_id: str | None = None,
    ) -> BotAskResponse:
        if not settings.feature_enable_collaboration_bots:
            return self._renderer.error_response(
                provider=event.provider,
                code="bots_disabled",
                message="Rudix bot access is disabled for this environment.",
                thread_id=event.thread_id,
            )

        if not event.question.strip():
            return self._renderer.error_response(
                provider=event.provider,
                code="empty_question",
                message="Ask a question after the command so Rudix can search your permitted sources.",
                thread_id=event.thread_id,
            )

        installation = await self._resolve_installation(session, event=event)
        if installation is None:
            return self._renderer.error_response(
                provider=event.provider,
                code="bot_not_installed",
                message="This Slack or Teams workspace is not connected to Rudix.",
                thread_id=event.thread_id,
            )

        organization_id = installation.organization_id
        audit_base = {
            "provider": event.provider,
            "external_workspace_id": event.external_workspace_id,
            "external_tenant_id": event.external_tenant_id,
            "external_team_id": event.external_team_id,
            "external_user_id": event.external_user_id,
            "channel_id": event.channel_id,
            "thread_id": event.thread_id,
            "event_id": event.event_id,
            "raw_event_type": event.raw_event_type,
        }

        if installation.status != "enabled":
            await self._record_outcome(
                session,
                organization_id=organization_id,
                user_id=None,
                installation_id=installation.id,
                action="bots.ask.rejected_disabled",
                request_id=request_id,
                metadata=audit_base,
            )
            await session.commit()
            return self._renderer.error_response(
                provider=event.provider,
                code="bot_disabled",
                message="Rudix bot access is disabled for this workspace.",
                thread_id=event.thread_id,
            )

        mapping = await self._repository.get_user_mapping(
            session,
            installation_id=installation.id,
            organization_id=organization_id,
            external_user_id=event.external_user_id,
        )
        if mapping is None or mapping.status != "active":
            await self._record_outcome(
                session,
                organization_id=organization_id,
                user_id=None,
                installation_id=installation.id,
                action="bots.ask.rejected_unmapped_user",
                request_id=request_id,
                metadata=audit_base,
            )
            await session.commit()
            return self._renderer.error_response(
                provider=event.provider,
                code="bot_user_not_mapped",
                message="Your Slack or Teams account is not mapped to a Rudix user.",
                thread_id=event.thread_id,
            )

        mapped_user = await self._repository.get_active_mapped_user(
            session,
            organization_id=organization_id,
            mapping=mapping,
        )
        if mapped_user is None:
            await self._record_outcome(
                session,
                organization_id=organization_id,
                user_id=mapping.rudix_user_id,
                installation_id=installation.id,
                action="bots.ask.rejected_inactive_user",
                request_id=request_id,
                metadata=audit_base,
            )
            await session.commit()
            return self._renderer.error_response(
                provider=event.provider,
                code="bot_user_not_authorized",
                message="Your mapped Rudix account is not active in this organization.",
                thread_id=event.thread_id,
            )

        user, roles = mapped_user
        mapped_user_id = user.id
        installation_id = installation.id
        try:
            await self._rate_limiter.consume(
                provider=event.provider,
                external_workspace_id=event.external_workspace_id,
                external_user_id=event.external_user_id,
            )
        except BotRateLimitExceededError as exc:
            await self._record_outcome(
                session,
                organization_id=organization_id,
                user_id=mapped_user_id,
                installation_id=installation_id,
                action="bots.ask.rejected_rate_limited",
                request_id=request_id,
                metadata={**audit_base, "retry_after_seconds": exc.retry_after_seconds},
            )
            await session.commit()
            return self._renderer.error_response(
                provider=event.provider,
                code="rate_limit_exceeded",
                message=(
                    "Rudix bot rate limit exceeded. "
                    f"Try again in {exc.retry_after_seconds} seconds."
                ),
                thread_id=event.thread_id,
            )
        except BotRateLimitUnavailableError:
            await self._record_outcome(
                session,
                organization_id=organization_id,
                user_id=mapped_user_id,
                installation_id=installation_id,
                action="bots.ask.failed",
                request_id=request_id,
                metadata={**audit_base, "error_code": "rate_limiter_unavailable"},
            )
            await session.commit()
            return self._renderer.error_response(
                provider=event.provider,
                code="rate_limiter_unavailable",
                message="Rudix rate limiting is temporarily unavailable.",
                thread_id=event.thread_id,
            )

        principal = AuthenticatedPrincipal(
            user_id=str(mapped_user_id),
            organization_id=str(organization_id),
            email=user.email,
            roles=roles,
            auth_provider=f"{event.provider}_bot",
        )
        source_scope = event.source_scope or self._default_source_scope(
            installation.default_source_scope_json
        )
        payload = ChatQueryRequest(
            question=event.question,
            document_ids=list(event.document_ids),
            source_scope=source_scope,
        )

        await self._record_outcome(
            session,
            organization_id=organization_id,
            user_id=mapped_user_id,
            installation_id=installation_id,
            action="bots.ask.requested",
            request_id=request_id,
            metadata={
                **audit_base,
                "source_scope_mode": source_scope.mode if source_scope is not None else "all",
                "document_count": len(event.document_ids),
            },
        )
        await session.commit()

        try:
            from app.interfaces.http import chat as chat_api

            chat_response = await chat_api.query_chat(
                request=_InternalChatRequest(request_id=request_id),  # type: ignore[arg-type]
                payload=payload,
                principal=principal,
                _=None,
                db_session=session,
            )
        except HTTPException as exc:
            await session.rollback()
            await self._record_outcome(
                session,
                organization_id=organization_id,
                user_id=mapped_user_id,
                installation_id=installation_id,
                action="bots.ask.failed",
                request_id=request_id,
                metadata={
                    **audit_base,
                    "status_code": exc.status_code,
                    "error_code": self._http_error_code(exc),
                },
            )
            await session.commit()
            return self._renderer.error_response(
                provider=event.provider,
                code=self._http_error_code(exc),
                message=self._safe_http_error_message(exc),
                thread_id=event.thread_id,
            )
        except Exception as exc:
            await session.rollback()
            await self._record_outcome(
                session,
                organization_id=organization_id,
                user_id=mapped_user_id,
                installation_id=installation_id,
                action="bots.ask.failed",
                request_id=request_id,
                metadata={
                    **audit_base,
                    "error_type": exc.__class__.__name__,
                },
            )
            await session.commit()
            return self._renderer.error_response(
                provider=event.provider,
                code="bot_query_failed",
                message="Rudix could not answer this request right now.",
                thread_id=event.thread_id,
            )

        await self._record_outcome(
            session,
            organization_id=organization_id,
            user_id=mapped_user_id,
            installation_id=installation_id,
            action="bots.ask.completed",
            request_id=request_id,
            metadata={
                **audit_base,
                "chat_session_id": chat_response.chat_session_id,
                "assistant_message_id": chat_response.message_id,
                "not_found": chat_response.not_found,
                "citation_count": len(chat_response.citations),
                "source_scope_mode": source_scope.mode if source_scope is not None else "all",
                "document_count": len(event.document_ids),
            },
        )
        await session.commit()
        return self._renderer.answer_response(
            provider=event.provider,
            thread_id=event.thread_id,
            chat_response=chat_response,
        )

    async def resolve_installation(
        self,
        session: AsyncSession,
        *,
        event: BotAskEvent,
    ) -> BotInstallation | None:
        return await self._resolve_installation(session, event=event)

    async def _resolve_installation(
        self,
        session: AsyncSession,
        *,
        event: BotAskEvent,
    ) -> BotInstallation | None:
        candidates = [
            (
                event.external_workspace_id,
                event.external_tenant_id,
                event.external_team_id,
            ),
            (event.external_workspace_id, event.external_tenant_id, ""),
            (event.external_workspace_id, "", ""),
        ]
        seen: set[tuple[str, str, str]] = set()
        for workspace_id, tenant_id, team_id in candidates:
            key = (workspace_id, tenant_id, team_id)
            if key in seen:
                continue
            seen.add(key)
            installation = await self._repository.get_installation_by_external_scope(
                session,
                provider=event.provider,
                external_workspace_id=workspace_id,
                external_tenant_id=tenant_id,
                external_team_id=team_id,
            )
            if installation is not None:
                return installation
        return None

    @staticmethod
    def _default_source_scope(raw_scope: dict[str, Any]) -> SourceScopeRequest | None:
        if not raw_scope:
            return None
        return SourceScopeRequest.model_validate(raw_scope)

    async def _record_outcome(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        installation_id: UUID,
        action: str,
        request_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        await self._audit_service.record(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type="bot_installation",
            resource_id=installation_id,
            request_id=request_id,
            metadata=metadata,
        )

    @staticmethod
    def _http_error_code(exc: HTTPException) -> str:
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code")
            if isinstance(code, str) and code.strip():
                return code
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return "permission_denied"
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return "not_found"
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            return "rate_limit_exceeded"
        return "bot_query_failed"

    @staticmethod
    def _safe_http_error_message(exc: HTTPException) -> str:
        detail = exc.detail
        if isinstance(detail, dict):
            message = detail.get("message")
            if isinstance(message, str) and message.strip():
                return message
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return "You do not have permission to ask against those sources."
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return "The requested Rudix source was not found or is not accessible."
        return "Rudix could not answer this request right now."
