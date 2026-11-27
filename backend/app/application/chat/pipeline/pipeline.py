"""The staged chat pipeline (R05-01, R05-02).

``ChatPipeline(deps).run(...)`` runs the stages in the order ``query_chat`` ran them and
returns the finished ``ChatContext``. Refusals raise ``ChatPipelineError`` with a safe code;
a quota refusal re-raises the quota ``HTTPException`` unchanged.

R05-02: the run pre-assigns the assistant message id (and the chat session id for a new
session), binds the tenant context variable for its whole duration (tasks it starts, such as
parallel retrieval branches, inherit it), and ends the read phase of its session scope after
the shortcut stage, so no connection is held from rewriting onwards except inside a short
lookup or the final write.
"""

from collections.abc import Sequence
from uuid import uuid4

from app.application.chat.pipeline.context import ChatContext, RequestState, RunIds
from app.application.chat.pipeline.deps import ChatPipelineDeps
from app.application.chat.pipeline.events import ActivityStepEmitter, Emitter
from app.application.chat.pipeline.request_helpers import _principal_user_and_org
from app.application.chat.pipeline.runner import Stage, StageRunner
from app.application.chat.pipeline.sessions import ChatSessionScope
from app.application.chat.pipeline.stages.authorize import AuthorizeStage
from app.application.chat.pipeline.stages.direct_answers import DirectAnswersStage
from app.application.chat.pipeline.stages.generate import GenerateStage
from app.application.chat.pipeline.stages.guard import GuardStage
from app.application.chat.pipeline.stages.persist import PersistStage
from app.application.chat.pipeline.stages.policies import (
    record_runner_degradation,
    start_deadline,
)
from app.application.chat.pipeline.stages.rerank_pack import RerankPackStage
from app.application.chat.pipeline.stages.resolve_config import ResolveConfigStage
from app.application.chat.pipeline.stages.retrieve import RetrieveStage
from app.application.chat.pipeline.stages.rewrite import RewriteStage
from app.application.chat.pipeline.stages.shortcut import ShortcutStage
from app.application.chat.pipeline.stages.verify import VerifyStage
from app.auth.models import AuthenticatedPrincipal
from app.db.tenant_context import tenant_context_scope
from app.domains.chat.schemas.chat import ChatQueryRequest

# The read phase (stages 1, 2, and 4) ends after this stage.
READ_PHASE_LAST_STAGE = ShortcutStage.name


async def _end_read_phase(stage: Stage, ctx: ChatContext) -> None:
    if stage.name == READ_PHASE_LAST_STAGE:
        await ctx.sessions.end_read()


def default_stages() -> list[Stage]:
    """Stages in ``query_chat`` order: the injection guard ran before the policy and profile
    resolution, and query rewriting ran before the direct answers."""
    return [
        AuthorizeStage(),
        GuardStage(),
        ResolveConfigStage(),
        ShortcutStage(),
        RewriteStage(),
        DirectAnswersStage(),
        RetrieveStage(),
        RerankPackStage(),
        GenerateStage(),
        VerifyStage(),
        PersistStage(),
    ]


class ChatPipeline:
    def __init__(
        self,
        deps: ChatPipelineDeps,
        *,
        stages: Sequence[Stage] | None = None,
        runner: StageRunner | None = None,
    ) -> None:
        self._deps = deps
        self._runner = runner or StageRunner(
            stages if stages is not None else default_stages(),
            after_stage=_end_read_phase,
            degradation_hook=record_runner_degradation,
        )

    async def run(
        self,
        request: ChatQueryRequest,
        principal: AuthenticatedPrincipal,
        transport: str,
        emitter: Emitter,
        scope: ChatSessionScope,
        request_id: str | None,
        ids: RunIds | None = None,
    ) -> ChatContext:
        user_id, organization_id = _principal_user_and_org(principal)
        run_ids = ids or RunIds()
        if request.chat_session_id is None:
            run_ids.new_chat_session = True
            if run_ids.chat_session_id is None:
                run_ids.chat_session_id = uuid4()
        ctx = ChatContext(
            request=RequestState(
                payload=request,
                principal=principal,
                transport=transport,
                request_id=request_id,
                user_id=user_id,
                organization_id=organization_id,
                user_roles=list(principal.roles or []),
            ),
            deps=self._deps,
            emitter=emitter,
            sessions=scope,
            steps=ActivityStepEmitter(emitter),
            ids=run_ids,
        )
        # R05-04: the optional-stage deadline starts with the run (off when 0).
        start_deadline(ctx)
        with tenant_context_scope(organization_id):
            try:
                return await self._runner.run(ctx)
            finally:
                await scope.close()
