"""The staged chat pipeline (R05-01).

``ChatPipeline(deps).run(...)`` runs the stages in the order ``query_chat`` ran them and
returns the finished ``ChatContext``. Refusals raise ``ChatPipelineError`` with a safe code;
a quota refusal re-raises the quota ``HTTPException`` unchanged.
"""

from collections.abc import Sequence

from app.application.chat.pipeline.context import ChatContext, RequestState
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
from app.application.chat.pipeline.stages.rerank_pack import RerankPackStage
from app.application.chat.pipeline.stages.resolve_config import ResolveConfigStage
from app.application.chat.pipeline.stages.retrieve import RetrieveStage
from app.application.chat.pipeline.stages.rewrite import RewriteStage
from app.application.chat.pipeline.stages.shortcut import ShortcutStage
from app.application.chat.pipeline.stages.verify import VerifyStage
from app.auth.models import AuthenticatedPrincipal
from app.domains.chat.schemas.chat import ChatQueryRequest


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
        self._runner = runner or StageRunner(stages if stages is not None else default_stages())

    async def run(
        self,
        request: ChatQueryRequest,
        principal: AuthenticatedPrincipal,
        transport: str,
        emitter: Emitter,
        scope: ChatSessionScope,
        request_id: str | None,
    ) -> ChatContext:
        user_id, organization_id = _principal_user_and_org(principal)
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
        )
        return await self._runner.run(ctx)
