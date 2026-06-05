from __future__ import annotations

from dataclasses import dataclass

from app.domains.prompt_templates.services.defaults import ANSWER_GENERATION_TEMPLATE
from app.domains.prompt_templates.services.rendering import render_prompt_template

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
}


@dataclass(frozen=True)
class PromptContextChunk:
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    text: str
    similarity_score: float | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None


def _language_instruction(answer_language: str | None) -> str:
    """Return a language instruction line or empty string."""
    if not answer_language:
        return ""
    language_name = _LANGUAGE_NAMES.get(answer_language, answer_language.upper())
    return (
        f"11. Write the answer in {language_name}. "
        "Citations must reference original source text exactly as written, regardless of language.\n"
    )


class PromptService:
    """Builds grounded prompts with strict source and injection rules."""

    def build_prompt(
        self,
        *,
        question: str,
        chunks: list[PromptContextChunk],
        not_found_answer: str,
        answer_language: str | None = None,
        template: str | None = None,
    ) -> str:
        allowed_chunk_ids = [chunk.chunk_id for chunk in chunks]
        allowed_chunk_ids_text = ", ".join(allowed_chunk_ids) if allowed_chunk_ids else "<none>"
        context_lines: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            context_lines.append(
                f"[{index}]\n"
                f"document_id={chunk.document_id}\n"
                f"chunk_id={chunk.chunk_id}\n"
                f"filename={chunk.filename}\n"
                f"page_number={chunk.page_number}\n"
                f"similarity_score={chunk.similarity_score}\n"
                f"rerank_score={chunk.rerank_score}\n"
                f"rerank_rank={chunk.rerank_rank}\n"
                f"text:\n{chunk.text}"
            )

        context_block = "\n\n".join(context_lines) if context_lines else "<none>"
        lang_rule = _language_instruction(answer_language)
        return render_prompt_template(
            template or ANSWER_GENERATION_TEMPLATE,
            {
                "question": question,
                "context_blocks": context_block,
                "allowed_chunk_ids": allowed_chunk_ids_text,
                "not_found_answer": not_found_answer,
                "answer_language_instruction": lang_rule,
            },
        )

    def build_general_prompt(
        self,
        *,
        question: str,
        answer_language: str | None = None,
    ) -> str:
        """Builds a prompt for general-knowledge (no-RAG) chat mode."""
        lang_rule = _language_instruction(answer_language)
        return (
            "You are a helpful assistant.\n"
            "Answer the user's question using your own knowledge.\n"
            "Follow these rules:\n"
            "1. Never invent citations or document references.\n"
            "2. Return compact JSON only; no markdown, no code fences, no extra keys.\n"
            f"{lang_rule}"
            "Return ONLY a valid JSON object with keys: answer, not_found, citations.\n"
            "JSON schema:\n"
            "{\n"
            '  "answer": "string",\n'
            '  "not_found": false,\n'
            '  "citations": []\n'
            "}\n\n"
            "User question:\n"
            "<<QUESTION_START>>\n"
            f"{question}\n"
            "<<QUESTION_END>>"
        )
