"""``generation.final`` and the post-stream text corrections (R05-03, contract 4.2.6).

Runs at the end of the verify stage, where answer, citations, and confidence are final:

- live mode: when the authoritative answer differs from the text the client has seen
  (normalisation, grounded verifier, refiner, AI-policy block or disclaimer), one
  ``generation.replace`` carries the full final text and the reason;
- buffered mode: the verified text is sent as ``generation.delta`` now;
- then ``generation.final`` with the answer, citations, and confidence.

Runs that never started a generation (a blocked question, no evidence) send the final
event only. ``chat.completed`` still follows after persistence and stays the source of truth.
"""

from typing import Any

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.events import generation_final_event
from app.application.chat.pipeline.stages._llm import emit_delta, emit_replace, observe_ttft
from app.application.chat.pipeline.stream_state import ReplaceReason


def _policy_changed_answer(ctx: ChatContext) -> bool:
    """Mirrors ``VerifyStage._policy_post_check``: a post-generation block, or a disclaimer
    applied by ``apply_disclaimer`` to an answer that is not blocked."""
    gen = ctx.generation
    result = ctx.verification.ai_policy_result
    policy = ctx.config.ai_effective_policy
    if result.blocked:
        return True
    return (
        not gen.not_found
        and policy is not None
        and policy.source != "none"
        and bool(result.disclaimer_text)
    )


def replace_reason(ctx: ChatContext) -> ReplaceReason:
    if _policy_changed_answer(ctx):
        return "policy"
    generated = ctx.stream.answer_after_generation
    if generated is not None and generated != ctx.generation.answer:
        return "verification"
    return "normalisation"


def final_payload(ctx: ChatContext) -> dict[str, Any]:
    gen = ctx.generation
    ver = ctx.verification
    citations = [] if gen.not_found else gen.citations
    return {
        "answer": gen.answer,
        "not_found": gen.not_found,
        "citations": [citation.model_dump(mode="json") for citation in citations],
        "confidence_score": ver.confidence_score,
        "confidence_category": ver.confidence_category,
        "citation_validation_failed": ver.citation_validation_failed,
    }


async def emit_final_events(ctx: ChatContext) -> None:
    stream = ctx.stream
    if stream.final_emitted:
        return
    stream.final_emitted = True
    final_text = ctx.generation.answer
    if ctx.generation.drafting_started:
        if stream.mode == "buffered" and not stream.streamed:
            await emit_delta(ctx, final_text)
        elif stream.streamed_text != final_text:
            await emit_replace(ctx, final_text, replace_reason(ctx))
    observe_ttft(ctx)
    await ctx.emit(generation_final_event(final_payload(ctx), str(ctx.ids.assistant_message_id)))
