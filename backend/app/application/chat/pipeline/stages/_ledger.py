"""Token-ledger bookkeeping for the auxiliary provider calls of a chat run (R05-07).

Stage labels: ``rewrite``, ``retrieve`` (query embeddings, one entry per retrieval query,
sub-queries included), ``rerank`` (one entry per batch), ``conflict``, ``generate`` (answer,
guidance, and every tree-search candidate), ``verifier``, and ``refiner``. Entries carry
counts, provider keys, and model names only, never prompt or document text.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.ledger import LedgerEntry, TokenLedger
from app.domains.chat.services.aux_llm import AuxCallUsage
from app.domains.chat.services.llm_service import LLMAnswerResult
from app.domains.chat.services.rerank_service import RerankDiagnostics


def record_aux_usage(ctx: ChatContext, stage: str, usage: AuxCallUsage | None) -> None:
    """Record one auxiliary call; ``None`` means no provider call completed."""
    if usage is None:
        return
    ctx.ledger.record(
        stage,
        usage.provider_key,
        usage.model_name,
        usage.prompt_tokens,
        usage.completion_tokens,
        cached_tokens=usage.cached_tokens,
        cost_usd=usage.cost_usd,
    )


def record_rerank_usage(ctx: ChatContext, diagnostics: RerankDiagnostics | None) -> None:
    if diagnostics is None:
        return
    for usage in diagnostics.batch_usages:
        record_aux_usage(ctx, "rerank", usage)


def record_llm_results(
    ctx: ChatContext,
    results: Iterable[LLMAnswerResult],
    *,
    stage: str = "generate",
) -> None:
    for result in results:
        ctx.ledger.record(
            stage,
            result.provider_key,
            result.model_name,
            result.prompt_tokens,
            result.completion_tokens,
            cost_usd=result.approximate_cost_usd,
        )


def ledger_metadata(ledger: TokenLedger) -> list[dict[str, Any]]:
    """The per-call breakdown stored in ``usage_events.metadata_json.token_ledger``."""
    return [_entry_metadata(entry) for entry in ledger.entries]


def _entry_metadata(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "stage": entry.stage,
        "provider": entry.provider_key,
        "model": entry.model,
        "prompt_tokens": entry.prompt_tokens,
        "completion_tokens": entry.completion_tokens,
        "cached_tokens": entry.cached_tokens,
        "cost_usd": float(entry.cost_usd) if entry.cost_usd is not None else None,
        "estimated": entry.estimated,
    }
