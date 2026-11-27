"""Chat query and WebSocket routes, and the compatibility surface of the chat module.

Since R05-01 (S3) both transports run the staged pipeline in ``app.application.chat``:
``query_chat`` delegates to ``transports/http.py`` and ``_run_ws_chat_pipeline`` to
``transports/ws.py``. The other chat routes live in sibling modules (``chat_sessions``,
``chat_trust``, ``chat_shares``, ``chat_feedback``, ``chat_answer_shares``); ``router``
includes them in the original registration order, so path matching and the OpenAPI
document are unchanged. This module keeps the names of contract 4.2.2 (pipeline
singletons, rebindable globals, re-exported helpers) and re-exports the moved routes.
"""

import asyncio
import secrets
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.controls import (  # noqa: F401 (re-export)
    _resolve_planner_critic_controls,
    _resolve_query_rewrite_preview_enabled,
)
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.errors import _safe_http_error  # noqa: F401 (re-export)
from app.application.chat.pipeline.provider_proxies import (  # noqa: F401 (re-export)
    _ChatCompletionProviderProxy,
    _EmbeddingProviderProxy,
    bind_openai_client_proxies,
)
from app.application.chat.pipeline.request_helpers import _request_id_from_request
from app.application.chat.quota import ensure_chat_quota
from app.application.chat.transports import ws as ws_runs
from app.application.chat.transports.http import run_http_query
from app.application.chat.transports.sse import open_sse_query
from app.application.chat.transports.ws import WsSequence, as_ws_sequence, run_ws_query
from app.application.chat.transports.ws_resume import start_ws_resume
from app.application.chat.ws_auth import authenticate_ws_handshake
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_query_event
from app.db.session import SessionLocal, get_db_session
from app.domains.chat.schemas.chat import ChatQueryRequest, ChatQueryResponse
from app.domains.chat.schemas.chat_ws import ChatWSInboundMessage, ChatWSOutboundEvent
from app.domains.chat.services.chat_values import _parse_uuid_or_none  # noqa: F401
from app.domains.chat.services.citation_enrichment import (  # noqa: F401 (re-export)
    _build_conflict_context,
    _with_conflict_status,
    _with_extraction_quality,
    _with_table_metadata,
)
from app.domains.chat.services.confidence_calibration import (  # noqa: F401 (re-export)
    _EXTRACTION_CONFIDENCE_WARN_THRESHOLD,
    _EXTRACTION_WARNING_PROFILES,
    _PROCESSING_INCOMPLETE_STATUSES,
    _TABLE_CONFIDENCE_LOW_THRESHOLD,
    _TABLE_CONFIDENCE_VERY_LOW_THRESHOLD,
    _build_evidence_quality_inputs,
    _build_evidence_quality_record,
    _compute_conflict_multiplier,
    _compute_extraction_quality_multiplier,
    _compute_freshness_multiplier,
    _compute_ocr_quality_multiplier,
    _compute_table_quality_multiplier,
    _confidence_category_from_score,
    _to_confidence_signals,
)
from app.domains.chat.services.graph_retrieval_service import (  # noqa: F401 (re-export)
    GraphRetrievalResult,
    GraphRetrievalService,
    GraphRetrievedChunk,
)
from app.domains.chat.services.trust_records import (  # noqa: F401 (re-export)
    _build_planner_critic_record,
    _build_retrieval_method_record,
    _build_tool_orchestration_record,
)
from app.interfaces.http import (
    chat_answer_shares,
    chat_feedback,
    chat_sessions,
    chat_shares,
    chat_trust,
)
from app.interfaces.http.chat_answer_shares import (  # noqa: F401 (re-export)
    answer_share_repository,
    create_answer_share,
    get_shared_answer,
    list_answer_shares,
    revoke_answer_share,
)
from app.interfaces.http.chat_feedback import (  # noqa: F401 (re-export)
    delete_message_feedback,
    feedback_repository,
    list_session_feedback,
    submit_message_feedback,
)
from app.interfaces.http.chat_sessions import (  # noqa: F401 (re-export)
    create_chat_message,
    create_chat_session,
    delete_chat_session,
    get_chat_session,
    get_chat_stats,
    list_chat_session_messages,
    list_chat_sessions,
    update_chat_session,
)
from app.interfaces.http.chat_shares import (  # noqa: F401 (re-export)
    create_chat_share,
    get_shared_session,
    list_chat_shares,
    revoke_chat_share,
    share_repository,
)
from app.interfaces.http.chat_trust import get_message_trust_metadata  # noqa: F401
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.rate_limit.counter import RateLimitDecision, consume_rate_limit

router = APIRouter(prefix="/chat", tags=["chat"])
# Separate router for WebSocket — must NOT be under protected_router because
# the browser WebSocket API cannot send an Authorization header during the HTTP
# upgrade, so FastAPI's router-level get_current_principal dependency would fail.
ws_router = APIRouter(prefix="/chat", tags=["chat"])
chat_repository = default_deps.chat_repository
usage_repository = default_deps.usage_repository
audit_log_service = default_deps.audit_log_service

# Legacy module names of the pipeline singletons (contract 4.2.2): the same objects as
# ``default_deps``, so patching an attribute through ``chat_api`` patches the pipeline.
_query_retrieval_service = default_deps.query_retrieval_service
_keyword_retrieval_service = default_deps.keyword_retrieval_service
_hybrid_retrieval_service = default_deps.hybrid_retrieval_service
_source_scope_service = default_deps.source_scope_service
_rerank_service = default_deps.rerank_service
_prompt_service = default_deps.prompt_service
_prompt_template_service = default_deps.prompt_template_service
_citation_service = default_deps.citation_service
_source_provenance_service = default_deps.source_provenance_service
_confidence_service = default_deps.confidence_service
_conflict_detection_service = default_deps.conflict_detection_service
_graph_retrieval_service = default_deps.graph_retrieval_service
_feature_flag_service = default_deps.feature_flag_service
# Rebindable: tests set it to a fake OpenAI client; the proxies read it on every call.
_openai_client: Any | None = None

_llm_service = default_deps.llm_service
_injection_guard = default_deps.injection_guard
_query_rewriting_service = default_deps.query_rewriting_service
_grounded_verifier = default_deps.grounded_verifier
_answer_mode_service = default_deps.answer_mode_service
_answer_planner = default_deps.answer_planner
_answer_critic = default_deps.answer_critic
_answer_refiner = default_deps.answer_refiner
_authorization_service = default_deps.authorization_service
_source_freshness_service = default_deps.source_freshness_service
_table_retrieval_service = default_deps.table_retrieval_service
_ocr_quality_service = default_deps.ocr_quality_service
_parent_context_expansion_service = default_deps.parent_context_expansion_service
_parallel_retrieval_optimizer = default_deps.parallel_retrieval_optimizer
_context_packer_service = default_deps.context_packer_service
_retrieval_strategy_router = default_deps.retrieval_strategy_router
_chat_tool_orchestrator = default_deps.chat_tool_orchestrator
_tree_search_service = default_deps.tree_search_service
_chat_tool_policy_repo = default_deps.chat_tool_policy_repo
_document_repository_for_trust = default_deps.document_repository_for_trust
_ai_policy_repo = default_deps.ai_policy_repo
_ai_policy_engine = default_deps.ai_policy_engine
bind_openai_client_proxies(
    llm_service=_llm_service,
    query_retrieval_service=_query_retrieval_service,
    client_getter=lambda: _openai_client,
)

# Registration order is the pre-split order: the session routes, POST /chat, the trust
# metadata route, then shares, feedback, and answer shares.
router.include_router(chat_sessions.router)


@router.post("", response_model=ChatQueryResponse)
async def query_chat(
    request: Request,
    payload: ChatQueryRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatQueryResponse:
    # R05-01: the staged pipeline. ensure_chat_quota is read here so a rebinding of this
    # module's global reaches it.
    return await run_http_query(
        payload=payload,
        principal=principal,
        db_session=db_session,
        request_id=_request_id_from_request(request),
        ensure_quota=ensure_chat_quota,
    )


@router.post(
    "/query/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Server-Sent Events: `id`/`event`/`data` frames whose data is a chat event "
                "envelope (generation.delta, generation.final, chat.completed, chat.error)."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def query_chat_stream(
    request: Request,
    payload: ChatQueryRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    # R05-03: the pipeline with short sessions from SessionLocal (read here, like the
    # WebSocket), so the stream never holds the request session. That session served
    # authentication only (reads), and FastAPI closes it after the whole stream: end its
    # transaction now so it returns its connection to the pool before the stream starts.
    await db_session.commit()
    return await open_sse_query(
        payload=payload,
        principal=principal,
        request_id=_request_id_from_request(request) or secrets.token_hex(16),
        session_factory=SessionLocal,
        ensure_quota=ensure_chat_quota,
    )


router.include_router(chat_trust.router)
router.include_router(chat_shares.router)
router.include_router(chat_feedback.router)
router.include_router(chat_answer_shares.router)


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket chat transport (F277)
# ──────────────────────────────────────────────────────────────────────────────

# Per-user active connection counter (in-process; replace with Redis for multi-instance).
_ws_connection_counts: dict[str, int] = {}
_ws_connection_lock = asyncio.Lock()


async def _ws_send(websocket: WebSocket, event: ChatWSOutboundEvent) -> None:
    try:
        await websocket.send_text(event.to_json())
    except Exception:
        pass


async def _run_ws_chat_pipeline(
    websocket: WebSocket,
    payload: dict[str, Any],
    principal: AuthenticatedPrincipal,
    request_id: str,
    sequence_start: int | WsSequence,
) -> None:
    """Run the staged pipeline and stream its events over the WebSocket.

    ``sequence_start`` is the connection's ``WsSequence`` (``chat_websocket`` passes it) or,
    for compatibility, an integer start for a new counter. ``SessionLocal`` and
    ``ensure_chat_quota`` are read here so a rebinding of this module's globals reaches it.
    """
    await run_ws_query(
        websocket=websocket,
        payload=payload,
        principal=principal,
        request_id=request_id,
        sequence=as_ws_sequence(sequence_start),
        session_factory=SessionLocal,
        ensure_quota=ensure_chat_quota,
    )


@ws_router.websocket("/ws")
async def chat_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    ticket: str | None = Query(default=None),
) -> None:
    """WebSocket chat endpoint (F277). Feature-flagged via FEATURE_CHAT_WEBSOCKET_ENABLED.

    Handshake auth (R02-10): ``?ticket=`` from POST /chat/ws-ticket, then an
    ``Authorization`` header, then the deprecated ``?token=`` (off by default since 0.5.0).
    """
    if not settings.feature_chat_websocket_enabled:
        await websocket.close(code=4503, reason="WebSocket chat is not enabled")
        return

    # ── Auth ──────────────────────────────────────────────────────────────────
    async with SessionLocal() as auth_session:
        auth_result = await authenticate_ws_handshake(
            headers=websocket.headers,
            client=websocket.client,
            ticket=ticket,
            token=token,
            db_session=auth_session,
        )

    principal = auth_result.principal
    if principal is None:
        log_query_event(
            event="chat.ws.auth.rejected",
            method=auth_result.method,
            failure=auth_result.failure,
        )
        reason = (
            "Missing auth credentials"
            if auth_result.failure == "missing_credentials"
            else "Unauthorized"
        )
        await websocket.close(code=4401, reason=reason)
        return

    user_id = principal.user_id

    # ── Role check ────────────────────────────────────────────────────────────
    allowed_roles = {
        OrganizationRole.owner.value,
        OrganizationRole.admin.value,
        OrganizationRole.member.value,
        OrganizationRole.viewer.value,
    }
    principal_roles = {r.strip() for r in (principal.roles or [])}
    if allowed_roles and not principal_roles.intersection(allowed_roles):
        await websocket.close(code=4403, reason="Insufficient role")
        return

    # ── Connection count guard ────────────────────────────────────────────────
    async with _ws_connection_lock:
        current = _ws_connection_counts.get(user_id, 0)
        if current >= settings.ws_chat_max_connections_per_user:
            await websocket.close(code=4429, reason="Too many connections")
            return
        _ws_connection_counts[user_id] = current + 1

    await websocket.accept()
    log_query_event(
        event="ws_chat.connection.opened",
        organization_id=principal.organization_id,
        user_id=user_id,
    )

    # One counter for the connection and every run on it (R05-01): heartbeat, cancel, and
    # pipeline events never reuse a sequence number.
    sequence = WsSequence()

    async def send_event(
        event_type: str,
        payload: dict[str, Any] | None = None,
        safe_error_code: str | None = None,
    ) -> None:
        evt = ChatWSOutboundEvent(
            event=event_type,  # type: ignore[arg-type]
            sequence=sequence.next(),
            payload=payload,
            safe_error_code=safe_error_code,
        )
        await _ws_send(websocket, evt)

    active_task: asyncio.Task[None] | None = None
    active_run: ws_runs.WsRunHandle | None = None
    heartbeat_task: asyncio.Task[None] | None = None

    async def run_heartbeat() -> None:
        interval = settings.ws_chat_heartbeat_interval_seconds
        while True:
            await asyncio.sleep(interval)
            await send_event("heartbeat.ping")

    try:
        await send_event("connection.ready")
        heartbeat_task = asyncio.create_task(run_heartbeat())
        request_id = secrets.token_hex(16)

        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=float(settings.ws_chat_idle_timeout_seconds),
                )
            except TimeoutError:
                break

            try:
                msg = ChatWSInboundMessage.model_validate_json(raw)
            except Exception:
                await send_event("chat.error", safe_error_code="invalid_message")
                continue

            if msg.command == "heartbeat.pong":
                continue

            if msg.command == "chat.cancel":
                if active_task and not active_task.done():
                    await ws_runs.forward_ws_cancel(active_run)
                    active_task.cancel()
                    try:
                        await active_task
                    except asyncio.CancelledError:
                        pass
                    active_task = None
                    await send_event("chat.cancelled")
                continue

            if msg.command == "chat.resume":
                # R05-13: replay and follow a run of this principal (contract 4.2.7).
                if active_task and not active_task.done():
                    await send_event("chat.error", safe_error_code="already_running")
                    continue
                active_task, active_run = start_ws_resume(
                    websocket, msg.payload, principal, sequence, SessionLocal
                )
                continue

            if msg.command == "chat.start":
                if active_task and not active_task.done():
                    await send_event("chat.error", safe_error_code="already_running")
                    continue

                # Rate limit per chat.start command.
                outcome = await consume_rate_limit(
                    scope=RateLimitScope.chat, endpoint="/chat/ws", principal=principal
                )
                if outcome.decision == RateLimitDecision.limited:
                    await send_event("chat.error", safe_error_code="rate_limit_exceeded")
                    continue
                if outcome.decision == RateLimitDecision.unavailable:
                    await send_event("chat.error", safe_error_code="rate_limiter_unavailable")
                    continue

                request_id = msg.request_id or secrets.token_hex(16)
                payload_dict: dict[str, Any] = msg.payload or {}
                active_run = ws_runs.WsRunHandle()
                active_task = ws_runs.start_ws_run(
                    _run_ws_chat_pipeline(
                        websocket=websocket,
                        payload=payload_dict,
                        principal=principal,
                        request_id=request_id,
                        sequence_start=sequence,
                    ),
                    active_run,
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        if active_task and not active_task.done():
            ws_runs.handle_ws_drop(active_task, active_run)  # R05-13: resume grace window
        async with _ws_connection_lock:
            _ws_connection_counts[user_id] = max(0, _ws_connection_counts.get(user_id, 1) - 1)
        log_query_event(
            event="ws_chat.connection.closed",
            organization_id=principal.organization_id,
            user_id=user_id,
        )
