"""LLM judge for faithfulness and answer relevance of one evaluation answer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.domains.ai.profile.schemas import ResolvedTaskProfile
from app.domains.evaluations.services.evaluation_metrics_service import EvaluationJudgeScores
from app.workers.evaluation import facade
from app.workers.evaluation.config import _coerce_score

if TYPE_CHECKING:
    from app.workers.evaluation.question import RetrievedChunk


def _judge_prompt(
    *,
    question: str,
    expected_answer: str | None,
    generated_answer: str,
    retrieved_chunks: list[RetrievedChunk],
) -> str:
    context_lines: list[str] = []
    for index, chunk in enumerate(retrieved_chunks[:6], start=1):
        context_lines.append(
            f"[{index}] document_id={chunk.document_id} "
            f"chunk_id={chunk.chunk_id} filename={chunk.filename} page={chunk.page_number}\n"
            f"{chunk.text[:1200]}"
        )
    context_block = "\n\n".join(context_lines) if context_lines else "(no context)"
    expected_block = (
        expected_answer.strip()
        if isinstance(expected_answer, str) and expected_answer.strip()
        else "(none)"
    )
    return (
        "Score the assistant answer for a RAG evaluation.\n"
        "Return strict JSON with keys: faithfulness_score, answer_relevance_score.\n"
        "Scores must be floats between 0 and 1.\n\n"
        f"Question:\n{question}\n\n"
        f"Expected answer (optional):\n{expected_block}\n\n"
        f"Assistant answer:\n{generated_answer}\n\n"
        f"Retrieved context:\n{context_block}\n"
    )


async def _evaluate_with_llm_judge_async(
    *,
    model_name: str,
    question: str,
    expected_answer: str | None,
    generated_answer: str,
    retrieved_chunks: list[RetrievedChunk],
    resolved_profile: ResolvedTaskProfile | None = None,
) -> EvaluationJudgeScores:
    from app.domains.ai.providers.protocols import ChatCompletionRequest

    prompt = _judge_prompt(
        question=question,
        expected_answer=expected_answer,
        generated_answer=generated_answer,
        retrieved_chunks=retrieved_chunks,
    )
    # Read at call time so a rebinding of evaluation_tasks.default_provider_factory applies.
    provider_factory = facade().default_provider_factory
    if resolved_profile is not None:
        provider = provider_factory.get_chat_provider(resolved_profile.provider_type)
        judge_model = resolved_profile.base_model
    else:
        provider = provider_factory.get_chat_provider()
        judge_model = model_name
    response = await provider.complete(
        ChatCompletionRequest(
            prompt=prompt,
            model=judge_model,
            temperature=0.0,
            json_mode=True,
            system_message=(
                "You are an evaluation judge. Score only groundedness and relevance. "
                "Do not return any keys except faithfulness_score and answer_relevance_score."
            ),
        )
    )
    payload = json.loads(response.content)
    faithfulness_score = _coerce_score(payload.get("faithfulness_score"))
    answer_relevance_score = _coerce_score(payload.get("answer_relevance_score"))
    return EvaluationJudgeScores(
        faithfulness_score=faithfulness_score,
        answer_relevance_score=answer_relevance_score,
        provider=resolved_profile.provider_type if resolved_profile is not None else "llm_judge",
    )
