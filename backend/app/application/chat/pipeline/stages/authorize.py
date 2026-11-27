"""Stage 1: quota, explicit document access, source scope, chat session (R05-01).

Runs before anything reads document text: authorisation, the question quota, and document
access filtering stay ahead of retrieval and prompt building.
"""

from uuid import UUID

from fastapi import HTTPException, status

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.scope_inventory import _filter_authorized_document_ids_for_chat
from app.auth.dependencies import ensure_document_ids_access
from app.core.logging import log_query_event


def _session_not_found() -> ChatPipelineError:
    return ChatPipelineError(
        code="chat_session_not_found",
        status_code=status.HTTP_404_NOT_FOUND,
        message="Chat session not found",
    )


class AuthorizeStage:
    name = "authorize"
    runs_when_terminal = True
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        req = ctx.request
        deps = ctx.deps
        payload = req.payload
        principal = req.principal
        await ctx.emit_step("understanding_question", "Understanding your question", "running")
        async with ctx.sessions.read() as db_session:
            try:
                await deps.ensure_quota(
                    db_session, organization_id=req.organization_id, transport=req.transport
                )
            except HTTPException:
                await ctx.emit_step(
                    "understanding_question", "Understanding your question", "failed"
                )
                raise
            try:
                explicit_document_ids = await ensure_document_ids_access(
                    document_ids=payload.document_ids,
                    principal=principal,
                    db_session=db_session,
                )
            except HTTPException as exc:
                if exc.status_code != status.HTTP_404_NOT_FOUND:
                    raise
                log_query_event(
                    event="query.rejected.document_not_found",
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
                raise ChatPipelineError(
                    code="document_not_found",
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Document not found",
                ) from exc

            source_scope_result = await deps.source_scope_service.resolve_document_ids(
                db_session,
                organization_id=req.organization_id,
                user_id=req.user_id,
                user_roles=req.user_roles,
                source_scope=payload.source_scope,
                explicit_document_ids=explicit_document_ids,
            )
            document_ids = await _filter_authorized_document_ids_for_chat(
                db_session,
                principal=principal,
                organization_id=req.organization_id,
                user_id=req.user_id,
                user_roles=req.user_roles,
                document_ids=source_scope_result.document_ids,
            )
            ctx.scope.explicit_document_ids = explicit_document_ids
            ctx.scope.source_scope_result = source_scope_result
            ctx.scope.document_ids = document_ids

            if payload.chat_session_id is not None:
                try:
                    chat_session_id = UUID(payload.chat_session_id)
                except ValueError as exc:
                    self._log_session_not_found(ctx)
                    raise _session_not_found() from exc
                chat_session = await deps.chat_repository.get_chat_session(
                    db_session,
                    chat_session_id=chat_session_id,
                    organization_id=req.organization_id,
                    user_id=req.user_id,
                )
                if chat_session is None:
                    self._log_session_not_found(ctx)
                    raise _session_not_found()
            else:
                chat_session = await deps.chat_repository.create_chat_session(
                    db_session,
                    organization_id=req.organization_id,
                    user_id=req.user_id,
                    title=payload.question[:120],
                )
            ctx.scope.chat_session = chat_session

    @staticmethod
    def _log_session_not_found(ctx: ChatContext) -> None:
        log_query_event(
            event="query.rejected.chat_session_not_found",
            organization_id=ctx.request.principal.organization_id,
            user_id=ctx.request.principal.user_id,
            status_code=status.HTTP_404_NOT_FOUND,
        )
