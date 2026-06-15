"""Unit tests for table chunk citation metadata propagation — F298."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.domains.chat.schemas.chat import ChatCitationResponse


def _make_citation(chunk_id: str | None = None) -> ChatCitationResponse:
    return ChatCitationResponse(
        document_id=str(uuid4()),
        chunk_id=chunk_id or str(uuid4()),
        filename="report.pdf",
        page_number=2,
        score=0.85,
        similarity_score=0.85,
    )


# ---------------------------------------------------------------------------
# ChatCitationResponse defaults
# ---------------------------------------------------------------------------


def test_citation_default_not_table():
    c = _make_citation()
    assert c.is_table_chunk is False
    assert c.table_caption is None
    assert c.table_row_count is None
    assert c.table_col_count is None
    assert c.table_headers == []
    assert c.table_section_context is None


def test_citation_table_fields_set():
    chunk_id = str(uuid4())
    c = ChatCitationResponse(
        document_id=str(uuid4()),
        chunk_id=chunk_id,
        filename="financials.pdf",
        page_number=5,
        score=0.9,
        similarity_score=0.9,
        is_table_chunk=True,
        table_caption="Revenue Table",
        table_row_count=4,
        table_col_count=3,
        table_headers=["Quarter", "Revenue", "Growth"],
        table_section_context="Financial Summary",
    )
    assert c.is_table_chunk is True
    assert c.table_caption == "Revenue Table"
    assert c.table_row_count == 4
    assert c.table_col_count == 3
    assert c.table_headers == ["Quarter", "Revenue", "Growth"]
    assert c.table_section_context == "Financial Summary"


# ---------------------------------------------------------------------------
# _with_table_metadata helper
# ---------------------------------------------------------------------------


def test_with_table_metadata_annotates_table_chunk():
    from app.interfaces.http.chat import _with_table_metadata

    chunk_id = str(uuid4())
    citation = _make_citation(chunk_id=chunk_id)
    meta_map = {
        chunk_id: {
            "caption": "Q4 Results",
            "row_count": 5,
            "col_count": 4,
            "headers": ["Region", "Sales", "Target", "Delta"],
            "section_context": "Financial Review",
        }
    }
    result = _with_table_metadata(citation, meta_map)

    assert result.is_table_chunk is True
    assert result.table_caption == "Q4 Results"
    assert result.table_row_count == 5
    assert result.table_col_count == 4
    assert result.table_headers == ["Region", "Sales", "Target", "Delta"]
    assert result.table_section_context == "Financial Review"


def test_with_table_metadata_no_match_returns_unchanged():
    from app.interfaces.http.chat import _with_table_metadata

    chunk_id = str(uuid4())
    citation = _make_citation(chunk_id=chunk_id)
    result = _with_table_metadata(citation, {})

    assert result.is_table_chunk is False
    assert result.table_caption is None


def test_with_table_metadata_preserves_other_fields():
    from app.interfaces.http.chat import _with_table_metadata

    chunk_id = str(uuid4())
    doc_id = str(uuid4())
    citation = ChatCitationResponse(
        document_id=doc_id,
        chunk_id=chunk_id,
        filename="doc.pdf",
        page_number=3,
        score=0.75,
        similarity_score=0.75,
        original_rank=2,
        rerank_score=0.8,
    )
    meta_map = {
        chunk_id: {
            "caption": "Table 1",
            "row_count": 2,
            "col_count": 2,
            "headers": ["A", "B"],
            "section_context": None,
        }
    }
    result = _with_table_metadata(citation, meta_map)

    assert result.document_id == doc_id
    assert result.chunk_id == chunk_id
    assert result.filename == "doc.pdf"
    assert result.page_number == 3
    assert result.score == pytest.approx(0.75)
    assert result.similarity_score == pytest.approx(0.75)
    assert result.original_rank == 2
    assert result.rerank_score == pytest.approx(0.8)


def test_with_table_metadata_null_fields_in_metadata():
    from app.interfaces.http.chat import _with_table_metadata

    chunk_id = str(uuid4())
    citation = _make_citation(chunk_id=chunk_id)
    meta_map = {
        chunk_id: {
            "caption": None,
            "row_count": 3,
            "col_count": 2,
            "headers": [],
            "section_context": None,
        }
    }
    result = _with_table_metadata(citation, meta_map)

    assert result.is_table_chunk is True
    assert result.table_caption is None
    assert result.table_row_count == 3
    assert result.table_headers == []
    assert result.table_section_context is None


# ---------------------------------------------------------------------------
# ChatDebugResponse table fields
# ---------------------------------------------------------------------------


def test_debug_response_table_defaults():
    from app.domains.chat.schemas.chat import ChatDebugResponse

    debug = ChatDebugResponse(
        latencies_ms={},
        retrieval_count=0,
        selected_count=0,
        rerank_applied=False,
    )
    assert debug.table_boost_enabled is False
    assert debug.table_boost_applied is False
    assert debug.table_boost_count == 0
    assert debug.table_chunk_count == 0
    assert debug.table_query_detected is False


def test_debug_response_table_fields_set():
    from app.domains.chat.schemas.chat import ChatDebugResponse

    debug = ChatDebugResponse(
        latencies_ms={"total": 120},
        retrieval_count=10,
        selected_count=5,
        rerank_applied=True,
        table_boost_enabled=True,
        table_boost_applied=True,
        table_boost_count=2,
        table_chunk_count=3,
        table_query_detected=True,
    )
    assert debug.table_boost_enabled is True
    assert debug.table_boost_applied is True
    assert debug.table_boost_count == 2
    assert debug.table_chunk_count == 3
    assert debug.table_query_detected is True


# ---------------------------------------------------------------------------
# table_chunking_service integration: structured text contains expected parts
# ---------------------------------------------------------------------------


def test_table_chunk_text_has_table_header_and_data():
    from app.domains.documents.extraction.models import BoundingBox, TableBlock, TableCell
    from app.domains.documents.services.table_chunking_service import build_table_chunk

    cells = [
        TableCell(row=0, col=0, text="Month"),
        TableCell(row=0, col=1, text="Revenue"),
        TableCell(row=1, col=0, text="Jan"),
        TableCell(row=1, col=1, text="500K"),
        TableCell(row=2, col=0, text="Feb"),
        TableCell(row=2, col=1, text="620K"),
    ]
    table = TableBlock(
        page_number=4,
        table_index=0,
        row_count=3,
        col_count=2,
        cells=tuple(cells),
        markdown="",
        json_data=(("Month", "Revenue"), ("Jan", "500K"), ("Feb", "620K")),
        caption="Monthly Revenue",
        confidence=0.95,
        extraction_engine="pymupdf",
        bbox=BoundingBox(x0=0, y0=0, x1=200, y1=100),
    )
    result = build_table_chunk(table, section_context="Revenue Analysis")

    assert "Monthly Revenue" in result.text
    assert "Month" in result.text
    assert "Revenue" in result.text
    assert "Jan" in result.text
    assert "500K" in result.text
    assert result.table_metadata["headers"] == ["Month", "Revenue"]
    assert result.table_metadata["section_context"] == "Revenue Analysis"
