"""Stage 3 (runs before stage 2, as ``query_chat`` did): prompt-injection check (R05-01).

A blocked question is answered with the not-found text by ``direct_answers``; nothing from
the question reaches retrieval or a model prompt. The log carries the reason codes only.
"""

from fastapi import status

from app.application.chat.pipeline.context import ChatContext
from app.core.logging import log_query_event


class GuardStage:
    name = "guard"
    runs_when_terminal = True
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        injection_check = ctx.deps.injection_guard.evaluate_request(
            objective="",
            question=ctx.request.payload.question,
            document_query=None,
        )
        ctx.config.injection_check = injection_check
        if injection_check.blocked:
            log_query_event(
                event="query.rejected.question_injection_detected",
                organization_id=ctx.request.principal.organization_id,
                user_id=ctx.request.principal.user_id,
                job_id=ctx.job_id,
                status_code=status.HTTP_200_OK,
                reasons=injection_check.reasons,
            )
