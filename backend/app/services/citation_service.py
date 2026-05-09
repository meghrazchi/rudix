from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID

from app.schemas.chat import ChatCitationResponse
from app.services.llm_service import ParsedCitation

_WHITESPACE_RE = re.compile(r"\s+")
_QUOTE_RE = re.compile(r"[\"“”'`]{1}([^\"“”'`]{8,400})[\"“”'`]{1}")


@dataclass(frozen=True)
class CitationContextChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    rerank_score: float | None = None
    rerank_rank: int | None = None


@dataclass(frozen=True)
class CitationBuildResult:
    citations: list[ChatCitationResponse]
    model_citation_count: int
    accepted_model_citation_count: int
    used_fallback: bool
    validation_score: float
    invalid_chunk_id_count: int
    metadata_mismatch_count: int
    snippet_mismatch_count: int


class CitationService:
    """Validates LLM citations against retrieved context and builds API-safe citations."""

    def __init__(
        self,
        *,
        max_text_snippet_chars: int = 400,
        fuzzy_match_threshold: float = 0.9,
    ) -> None:
        self.max_text_snippet_chars = max_text_snippet_chars
        self.fuzzy_match_threshold = fuzzy_match_threshold

    @staticmethod
    def _normalize_text(value: str) -> str:
        return _WHITESPACE_RE.sub(" ", value).strip().lower()

    def _snippet_matches_chunk(self, *, snippet: str, chunk_text: str) -> bool:
        normalized_snippet = self._normalize_text(snippet)
        normalized_chunk = self._normalize_text(chunk_text)
        if not normalized_snippet or not normalized_chunk:
            return False
        if normalized_snippet in normalized_chunk:
            return True
        matcher = SequenceMatcher(a=normalized_snippet, b=normalized_chunk)
        longest_match = matcher.find_longest_match(0, len(normalized_snippet), 0, len(normalized_chunk)).size
        return (longest_match / len(normalized_snippet)) >= self.fuzzy_match_threshold

    def _extract_answer_quotes(self, answer: str) -> list[str]:
        return [match.group(1).strip() for match in _QUOTE_RE.finditer(answer) if match.group(1).strip()]

    def _default_snippet(self, chunk: CitationContextChunk) -> str:
        return chunk.text[: self.max_text_snippet_chars].strip()

    def _build_response(self, *, chunk: CitationContextChunk, text_snippet: str) -> ChatCitationResponse:
        score = chunk.rerank_score if chunk.rerank_score is not None else chunk.similarity_score
        return ChatCitationResponse(
            document_id=str(chunk.document_id),
            chunk_id=str(chunk.chunk_id),
            filename=chunk.filename,
            page_number=chunk.page_number,
            score=score,
            similarity_score=chunk.similarity_score,
            rerank_score=chunk.rerank_score,
            rerank_rank=chunk.rerank_rank,
            text_snippet=text_snippet[: self.max_text_snippet_chars].strip() or self._default_snippet(chunk),
        )

    @staticmethod
    def _clamp_score(value: float) -> float:
        return max(0.0, min(1.0, round(value, 4)))

    def _compute_validation_score(
        self,
        *,
        model_citation_count: int,
        accepted_model_citation_count: int,
        metadata_mismatch_count: int,
        snippet_checks_count: int,
        snippet_valid_count: int,
        used_fallback: bool,
    ) -> float:
        if model_citation_count == 0:
            return 0.9 if used_fallback else 1.0

        id_ratio = accepted_model_citation_count / model_citation_count
        metadata_ratio = (
            1.0
            if accepted_model_citation_count == 0
            else max(0.0, 1 - (metadata_mismatch_count / accepted_model_citation_count))
        )
        snippet_ratio = (
            1.0 if snippet_checks_count == 0 else max(0.0, snippet_valid_count / snippet_checks_count)
        )
        score = (0.6 * id_ratio) + (0.2 * metadata_ratio) + (0.2 * snippet_ratio)
        if used_fallback:
            score = min(score, 0.9)
        return self._clamp_score(score)

    def build_citations(
        self,
        *,
        not_found: bool,
        answer: str,
        retrieved_chunks: list[CitationContextChunk],
        model_citations: Iterable[ParsedCitation],
    ) -> CitationBuildResult:
        if not_found or not retrieved_chunks:
            return CitationBuildResult(
                citations=[],
                model_citation_count=0,
                accepted_model_citation_count=0,
                used_fallback=False,
                validation_score=1.0,
                invalid_chunk_id_count=0,
                metadata_mismatch_count=0,
                snippet_mismatch_count=0,
            )

        citation_candidates = list(model_citations)
        model_citation_count = len(citation_candidates)
        allowed_by_chunk_id = {str(chunk.chunk_id): chunk for chunk in retrieved_chunks}
        answer_quotes = self._extract_answer_quotes(answer)

        built_citations: list[ChatCitationResponse] = []
        seen_chunk_ids: set[str] = set()
        accepted_model_citation_count = 0
        invalid_chunk_id_count = 0
        metadata_mismatch_count = 0
        snippet_mismatch_count = 0
        snippet_checks_count = 0
        snippet_valid_count = 0

        for model_citation in citation_candidates:
            chunk = allowed_by_chunk_id.get(model_citation.chunk_id)
            if chunk is None:
                invalid_chunk_id_count += 1
                continue
            if model_citation.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(model_citation.chunk_id)
            accepted_model_citation_count += 1

            if model_citation.filename and model_citation.filename != chunk.filename:
                metadata_mismatch_count += 1
            if model_citation.page_number is not None and model_citation.page_number != chunk.page_number:
                metadata_mismatch_count += 1

            snippet_candidate = (model_citation.text_snippet or "").strip()
            if not snippet_candidate:
                for quote in answer_quotes:
                    if self._snippet_matches_chunk(snippet=quote, chunk_text=chunk.text):
                        snippet_candidate = quote
                        break

            if snippet_candidate:
                snippet_checks_count += 1
                if self._snippet_matches_chunk(snippet=snippet_candidate, chunk_text=chunk.text):
                    snippet_valid_count += 1
                else:
                    snippet_mismatch_count += 1
                    snippet_candidate = self._default_snippet(chunk)
            else:
                snippet_candidate = self._default_snippet(chunk)

            built_citations.append(
                self._build_response(
                    chunk=chunk,
                    text_snippet=snippet_candidate,
                )
            )

        used_fallback = False
        if not built_citations:
            used_fallback = True
            built_citations = [
                self._build_response(chunk=chunk, text_snippet=self._default_snippet(chunk))
                for chunk in retrieved_chunks
            ]

        validation_score = self._compute_validation_score(
            model_citation_count=model_citation_count,
            accepted_model_citation_count=accepted_model_citation_count,
            metadata_mismatch_count=metadata_mismatch_count,
            snippet_checks_count=snippet_checks_count,
            snippet_valid_count=snippet_valid_count,
            used_fallback=used_fallback,
        )

        return CitationBuildResult(
            citations=built_citations,
            model_citation_count=model_citation_count,
            accepted_model_citation_count=accepted_model_citation_count,
            used_fallback=used_fallback,
            validation_score=validation_score,
            invalid_chunk_id_count=invalid_chunk_id_count,
            metadata_mismatch_count=metadata_mismatch_count,
            snippet_mismatch_count=snippet_mismatch_count,
        )
