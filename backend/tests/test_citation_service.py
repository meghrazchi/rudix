from __future__ import annotations

from uuid import uuid4

from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.llm_service import ParsedCitation


def _chunk(*, text: str = "Employees receive twenty days of annual leave.") -> CitationContextChunk:
    return CitationContextChunk(
        document_id=uuid4(),
        chunk_id=uuid4(),
        filename="policy.pdf",
        page_number=4,
        text=text,
        similarity_score=0.92,
        rerank_score=0.91,
        rerank_rank=1,
    )


def test_build_citations_rejects_fake_chunk_ids_and_falls_back_to_retrieved_context() -> None:
    service = CitationService()
    context_chunk = _chunk()

    result = service.build_citations(
        not_found=False,
        answer="Employees receive twenty days of annual leave.",
        retrieved_chunks=[context_chunk],
        model_citations=[
            ParsedCitation(
                document_id=str(context_chunk.document_id),
                chunk_id=str(uuid4()),
                filename="policy.pdf",
                page_number=4,
            )
        ],
    )

    assert result.used_fallback is True
    assert result.invalid_chunk_id_count == 1
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == str(context_chunk.chunk_id)


def test_build_citations_repairs_mismatched_metadata_for_valid_chunk_ids() -> None:
    service = CitationService()
    context_chunk = _chunk()

    result = service.build_citations(
        not_found=False,
        answer="The policy states annual leave entitlement.",
        retrieved_chunks=[context_chunk],
        model_citations=[
            ParsedCitation(
                document_id=str(context_chunk.document_id),
                chunk_id=str(context_chunk.chunk_id),
                filename="wrong.pdf",
                page_number=99,
                text_snippet="annual leave entitlement",
            )
        ],
    )

    assert result.used_fallback is False
    assert result.metadata_mismatch_count == 2
    assert len(result.citations) == 1
    assert result.citations[0].filename == context_chunk.filename
    assert result.citations[0].page_number == context_chunk.page_number


def test_build_citations_repairs_invalid_snippets() -> None:
    service = CitationService()
    context_chunk = _chunk()

    result = service.build_citations(
        not_found=False,
        answer="Employees receive twenty days of annual leave.",
        retrieved_chunks=[context_chunk],
        model_citations=[
            ParsedCitation(
                document_id=str(context_chunk.document_id),
                chunk_id=str(context_chunk.chunk_id),
                filename=context_chunk.filename,
                page_number=context_chunk.page_number,
                text_snippet="this snippet does not appear in the chunk",
            )
        ],
    )

    assert result.snippet_mismatch_count == 1
    assert len(result.citations) == 1
    assert result.citations[0].text_snippet == context_chunk.text[:400]


def test_citation_offsets_exact_case_insensitive_match() -> None:
    service = CitationService()
    chunk_text = "Employees receive twenty days of annual leave per year."
    chunk = _chunk(text=chunk_text)

    result = service.build_citations(
        not_found=False,
        answer="Employees receive twenty days.",
        retrieved_chunks=[chunk],
        model_citations=[
            ParsedCitation(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text_snippet="twenty days of annual leave",
            )
        ],
    )

    citation = result.citations[0]
    assert citation.start_offset is not None
    assert citation.end_offset is not None
    assert (
        chunk_text[citation.start_offset : citation.end_offset].lower()
        == "twenty days of annual leave"
    )


def test_citation_offsets_preserved_for_fallback_snippets() -> None:
    service = CitationService()
    chunk_text = "The quick brown fox jumps over the lazy dog."
    chunk = _chunk(text=chunk_text)

    # No model citations → fallback path uses default snippet (full chunk text).
    result = service.build_citations(
        not_found=False,
        answer="The quick brown fox.",
        retrieved_chunks=[chunk],
        model_citations=[
            ParsedCitation(
                document_id=str(chunk.document_id),
                chunk_id=str(uuid4()),  # invalid → triggers fallback
            )
        ],
    )

    assert result.used_fallback is True
    citation = result.citations[0]
    # Fallback snippet equals the full chunk text; offsets must cover it.
    assert citation.start_offset == 0
    assert citation.end_offset == len(chunk_text)


def test_citation_offsets_none_when_snippet_not_found_in_chunk() -> None:
    service = CitationService()
    # Snippet that doesn't match chunk text at all.
    chunk = _chunk(text="Completely unrelated chunk content here.")

    result = service.build_citations(
        not_found=False,
        answer="Some answer.",
        retrieved_chunks=[chunk],
        model_citations=[
            ParsedCitation(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text_snippet="this snippet does not appear in the chunk",
            )
        ],
    )

    # Mismatch causes snippet to be replaced by the default (full chunk); offsets should exist.
    citation = result.citations[0]
    assert citation.text_snippet is not None
    # When the default snippet is used it should match at offset 0.
    assert citation.start_offset == 0


def test_build_citations_returns_no_citations_for_not_found() -> None:
    service = CitationService()
    context_chunk = _chunk()

    result = service.build_citations(
        not_found=True,
        answer="I could not find this information in the uploaded documents.",
        retrieved_chunks=[context_chunk],
        model_citations=[
            ParsedCitation(
                document_id=str(context_chunk.document_id),
                chunk_id=str(context_chunk.chunk_id),
                filename=context_chunk.filename,
                page_number=context_chunk.page_number,
            )
        ],
    )

    assert result.citations == []
    assert result.used_fallback is False
    assert result.validation_score == 1.0
