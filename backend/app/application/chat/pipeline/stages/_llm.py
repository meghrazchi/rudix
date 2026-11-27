"""Shared bookkeeping for the answer-generation call (R05-01) and its stream (R05-03)."""

from time import perf_counter

from fastapi import status

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import (
    generation_delta_event,
    generation_replace_event,
    generation_started_event,
)
from app.application.chat.pipeline.stream_state import STREAMING_TRANSPORTS, StreamMode
from app.core.metrics import CHAT_TTFT_SECONDS
from app.domains.chat.services.llm_service import (
    LLMAnswerResult,
    LLMServiceError,
    ProviderBusyLLMServiceError,
)


async def start_drafting(ctx: ChatContext, mode: StreamMode) -> None:
    """Emit ``generation.started`` (with the stream mode) and the running drafting step once
    per run (tree search and the single grounded call share them; a tree-search fallback
    does not repeat them, and keeps the buffered mode)."""
    gen = ctx.generation
    if gen.drafting_started:
        return
    gen.drafting_started = True
    ctx.stream.mode = mode
    await ctx.emit(generation_started_event(mode))
    await ctx.emit_step("drafting_answer", "Drafting answer", "running")


def observe_ttft(ctx: ChatContext) -> None:
    """Record time to first answer text once per answer, for streaming transports."""
    stream = ctx.stream
    if stream.ttft_observed:
        return
    stream.ttft_observed = True
    transport = ctx.request.transport
    if transport in STREAMING_TRANSPORTS:
        CHAT_TTFT_SECONDS.labels(transport=transport).observe(perf_counter() - stream.started_at)


async def emit_delta(ctx: ChatContext, text: str) -> None:
    """Send provisional answer text (no citations) and remember what the client has seen."""
    if not text:
        return
    ctx.stream.streamed.append(text)
    observe_ttft(ctx)
    await ctx.emit(generation_delta_event(text))


async def emit_replace(ctx: ChatContext, text: str, reason: str) -> None:
    """Tell the client to replace every streamed character with ``text``."""
    ctx.stream.streamed = [text] if text else []
    await ctx.emit(generation_replace_event(text, reason, str(ctx.ids.assistant_message_id)))


async def stream_llm_answer(ctx: ChatContext, prompt: str) -> LLMAnswerResult:
    """Generate the answer through ``LLMService.stream_answer``. In live mode the decoded
    ``answer`` text goes out as ``generation.delta`` while the model writes it, and a retry
    or provider fallback after streamed text sends ``generation.replace`` with ``""``. In
    buffered mode nothing is sent here (the final stage sends the verified text)."""
    live = ctx.stream.mode == "live"

    async def on_text(text: str) -> None:
        if live:
            await emit_delta(ctx, text)

    async def on_reset(reason: str) -> None:
        if live:
            await emit_replace(ctx, "", reason)

    return await ctx.deps.llm_service.stream_answer(
        prompt=prompt,
        resolved_profile=ctx.config.chat_profile,
        on_text=on_text,
        on_reset=on_reset,
        progress=ctx.stream.progress,
    )


def apply_llm_result(ctx: ChatContext, llm_result: LLMAnswerResult, *, stage: str) -> None:
    """Copy the call metadata onto the context and record it in the token ledger.

    Runs once per chat run: for the guidance answer, the single grounded call, or the
    selected (or rejected) tree-search candidate, exactly where ``query_chat`` set them.
    """
    gen = ctx.generation
    gen.llm_latency_ms = llm_result.latency_ms
    gen.llm_model = llm_result.model_name
    gen.llm_provider = llm_result.provider_key
    gen.llm_fallback_used = llm_result.fallback_used
    gen.llm_fallback_from = llm_result.fallback_from
    gen.llm_fallback_to = llm_result.fallback_to
    gen.llm_fallback_reason = llm_result.fallback_reason
    gen.llm_retry_count = llm_result.retry_count
    gen.llm_prompt_tokens = llm_result.prompt_tokens
    gen.llm_completion_tokens = llm_result.completion_tokens
    gen.llm_cost_usd = llm_result.approximate_cost_usd
    ctx.ledger.record(
        stage,
        llm_result.provider_key,
        llm_result.model_name,
        llm_result.prompt_tokens,
        llm_result.completion_tokens,
        cached_tokens=llm_result.cached_prompt_tokens,
        cost_usd=llm_result.approximate_cost_usd,
        estimated=llm_result.usage_estimated,
    )


def generation_error(exc: LLMServiceError) -> ChatPipelineError:
    """The safe refusal for a failed answer generation: ``provider_busy`` (HTTP 429) when
    the organisation's LLM concurrency limit stayed reached (R05-06), otherwise
    ``generation_failed`` (HTTP 503), an open circuit breaker without fallback included."""
    if isinstance(exc, ProviderBusyLLMServiceError):
        return ChatPipelineError(
            code="provider_busy",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message="The AI provider is busy for this organisation; try again shortly",
        )
    return ChatPipelineError(
        code="generation_failed",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        message="Answer generation is unavailable",
    )
