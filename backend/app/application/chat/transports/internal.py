"""In-process adapter of the chat pipeline for callers without an HTTP request (R05-01).

The Slack/Teams bot service answers inbound events through it. The inbound route is not
authenticated with a Rudix token, so nothing has bound a tenant yet: the run binds the
principal's organisation (the bot installation's) to the caller's session with
``bind_pipeline_session`` before the pipeline runs, exactly as an authenticated request
would. The pipeline then binds every phase session again, so ``strict`` RLS applies.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.deps import ChatPipelineDeps, EnsureQuota, default_deps
from app.application.chat.quota import ensure_chat_quota
from app.application.chat.transports.http import run_http_query
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_query_event
from app.db.tenant_context import bind_pipeline_session
from app.domains.chat.schemas.chat import ChatQueryRequest, ChatQueryResponse


async def run_internal_query(
    principal: AuthenticatedPrincipal,
    payload: ChatQueryRequest,
    db_session: AsyncSession,
    request_id: str | None,
    *,
    ensure_quota: EnsureQuota = ensure_chat_quota,
    deps: ChatPipelineDeps = default_deps,
) -> ChatQueryResponse:
    """Answer one question for ``principal`` on ``db_session`` and return the HTTP response.

    Refusals raise the same safe ``HTTPException`` payloads as ``POST /chat``; usage is
    recorded with the HTTP transport label, as before the split.
    """
    await bind_pipeline_session(db_session, principal.organization_id)
    log_query_event(
        event="chat.internal.started",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        auth_provider=principal.auth_provider,
    )
    return await run_http_query(
        payload=payload,
        principal=principal,
        db_session=db_session,
        request_id=request_id,
        ensure_quota=ensure_quota,
        deps=deps,
    )
