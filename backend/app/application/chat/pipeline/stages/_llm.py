"""Shared bookkeeping for the answer-generation call (R05-01)."""

from app.application.chat.pipeline.context import ChatContext
from app.domains.chat.services.llm_service import LLMAnswerResult


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
        cost_usd=llm_result.approximate_cost_usd,
    )
