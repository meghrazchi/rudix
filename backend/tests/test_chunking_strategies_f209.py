"""Unit tests for structure-aware chunking strategies (F209):
page_aware and heading_aware.
Also tests the blocks.py parser and SectionTracker in isolation.
"""

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

from app.domains.documents.chunking.registry import get_registry
from app.domains.documents.chunking.strategies.blocks import (
    BLOCK_CODE,
    BLOCK_HEADING,
    BLOCK_LIST,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    SectionTracker,
    parse_blocks,
)
from app.domains.documents.chunking.strategies.heading_aware import HeadingAwareStrategy
from app.domains.documents.chunking.strategies.page_aware import PageAwareStrategy
from app.domains.documents.services.text_extraction import ExtractedSection

MODEL = "text-embedding-3-small"
IDX = "v-test"


def _pages(*texts: str) -> list[ExtractedSection]:
    return [
        ExtractedSection(page_number=i + 1, text=t, char_count=len(t)) for i, t in enumerate(texts)
    ]


def _page_aware(size: int = 100, overlap: int = 20) -> PageAwareStrategy:
    return PageAwareStrategy(
        chunk_size_tokens=size,
        chunk_overlap_tokens=overlap,
        embedding_model=MODEL,
        index_version=IDX,
    )


def _heading(size: int = 150, overlap: int = 25) -> HeadingAwareStrategy:
    return HeadingAwareStrategy(
        chunk_size_tokens=size,
        chunk_overlap_tokens=overlap,
        embedding_model=MODEL,
        index_version=IDX,
    )


def _common(chunks, *, name: str, max_tokens: int) -> None:
    assert chunks, "no chunks produced"
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert 0 < c.token_count <= max_tokens, (
            f"chunk {i} has {c.token_count} tokens (max {max_tokens})"
        )
        assert c.text.strip()
        assert c.strategy_name == name
        assert c.strategy_version == "1.0"


# ===========================================================================
# SectionTracker
# ===========================================================================


def test_section_tracker_builds_path() -> None:
    t = SectionTracker()
    t.update(1, "Policy")
    assert t.path == "Policy"
    t.update(2, "Leave")
    assert t.path == "Policy > Leave"
    t.update(3, "Annual Leave")
    assert t.path == "Policy > Leave > Annual Leave"


def test_section_tracker_demotes_on_same_level() -> None:
    t = SectionTracker()
    t.update(1, "Chapter 1")
    t.update(2, "Section A")
    t.update(2, "Section B")  # same level replaces
    assert t.path == "Chapter 1 > Section B"


def test_section_tracker_handles_top_level_reset() -> None:
    t = SectionTracker()
    t.update(1, "Part One")
    t.update(2, "Sub")
    t.update(1, "Part Two")  # top-level resets everything
    assert t.path == "Part Two"


def test_section_tracker_empty_path() -> None:
    t = SectionTracker()
    assert t.path == ""
    assert t.empty


def test_section_tracker_reset() -> None:
    t = SectionTracker()
    t.update(1, "Ch")
    t.reset()
    assert t.empty


# ===========================================================================
# parse_blocks
# ===========================================================================


def test_parse_blocks_empty_text() -> None:
    assert parse_blocks(1, "") == []
    assert parse_blocks(1, "   \n\n  ") == []


def test_parse_blocks_plain_paragraph() -> None:
    blocks = parse_blocks(1, "Hello world.\nThis is a test.")
    assert len(blocks) == 1
    assert blocks[0].block_type == BLOCK_PARAGRAPH
    assert "Hello" in blocks[0].text


def test_parse_blocks_atx_headings() -> None:
    text = "# Title\n\nSome paragraph.\n\n## Sub-heading\n\nMore content."
    blocks = parse_blocks(1, text)
    types = [b.block_type for b in blocks]
    assert BLOCK_HEADING in types
    h1 = next(b for b in blocks if b.block_type == BLOCK_HEADING and b.heading_level == 1)
    assert h1.text == "Title"
    h2 = next(b for b in blocks if b.block_type == BLOCK_HEADING and b.heading_level == 2)
    assert h2.text == "Sub-heading"


def test_parse_blocks_fenced_code() -> None:
    text = "Before.\n\n```python\ndef hello():\n    pass\n```\n\nAfter."
    blocks = parse_blocks(1, text)
    code = [b for b in blocks if b.block_type == BLOCK_CODE]
    assert code, "no code block detected"
    assert "def hello" in code[0].text


def test_parse_blocks_table() -> None:
    text = "Name | Age | Role\n---\nAlice | 30 | Engineer\nBob | 25 | Designer"
    blocks = parse_blocks(1, text)
    tables = [b for b in blocks if b.block_type == BLOCK_TABLE]
    assert tables, "no table block detected"
    assert "Alice" in tables[0].text


def test_parse_blocks_bullet_list() -> None:
    text = "Items:\n\n- First item\n- Second item\n- Third item"
    blocks = parse_blocks(1, text)
    lists = [b for b in blocks if b.block_type == BLOCK_LIST]
    assert lists, "no list block detected"
    assert "First" in lists[0].text


def test_parse_blocks_numbered_list() -> None:
    text = "Steps:\n\n1. Do this\n2. Then this\n3. Finally this"
    blocks = parse_blocks(1, text)
    lists = [b for b in blocks if b.block_type == BLOCK_LIST]
    assert lists, "no numbered list detected"


def test_parse_blocks_page_number_preserved() -> None:
    blocks = parse_blocks(42, "Some text on page 42.")
    assert all(b.page_number == 42 for b in blocks)


def test_parse_blocks_setext_heading() -> None:
    text = "Main Title\n==========\n\nContent here."
    blocks = parse_blocks(1, text)
    h = [b for b in blocks if b.block_type == BLOCK_HEADING]
    assert h, "setext H1 not detected"
    assert h[0].heading_level == 1
    assert "Main Title" in h[0].text


def test_parse_blocks_caps_heading() -> None:
    # Short ALL-CAPS lines should be treated as headings.
    text = "LEAVE POLICY\n\nEmployees may take annual leave."
    blocks = parse_blocks(1, text)
    headings = [b for b in blocks if b.block_type == BLOCK_HEADING]
    assert headings, "ALL-CAPS heading not detected"
    assert "LEAVE POLICY" in headings[0].text


def test_parse_blocks_multiple_sections() -> None:
    text = (
        "# Introduction\n\nIntro text.\n\n"
        "## Background\n\nBackground text.\n\n"
        "# Conclusion\n\nConclusion text."
    )
    blocks = parse_blocks(1, text)
    headings = [b for b in blocks if b.block_type == BLOCK_HEADING]
    assert len(headings) == 3


def test_parse_blocks_multilingual_no_crash() -> None:
    text = "Hello world.\n\nBonjour le monde.\n\nこんにちは世界。"
    blocks = parse_blocks(1, text)
    assert blocks  # doesn't crash


# ===========================================================================
# Registry
# ===========================================================================


def test_registry_knows_page_aware() -> None:
    assert "page_aware" in get_registry().known_strategies()


def test_registry_knows_heading_aware() -> None:
    assert "heading_aware" in get_registry().known_strategies()


# ===========================================================================
# PageAwareStrategy
# ===========================================================================


@pytest.mark.asyncio
async def test_page_aware_empty_pages() -> None:
    assert await _page_aware().chunk(document_id=uuid4(), pages=[]) == []


@pytest.mark.asyncio
async def test_page_aware_blank_page_skipped() -> None:
    chunks = await _page_aware().chunk(document_id=uuid4(), pages=_pages("   "))
    assert chunks == []


@pytest.mark.asyncio
async def test_page_aware_single_short_page() -> None:
    chunks = await _page_aware(size=200, overlap=20).chunk(
        document_id=uuid4(), pages=_pages("Hello world, this is page one.")
    )
    _common(chunks, name="page_aware", max_tokens=200)
    assert len(chunks) == 1
    assert chunks[0].page_number == 1


@pytest.mark.asyncio
async def test_page_aware_never_crosses_page_boundary() -> None:
    p1 = " ".join(["alpha"] * 60)
    p2 = " ".join(["beta"] * 60)
    chunks = await _page_aware(size=50, overlap=10).chunk(document_id=uuid4(), pages=_pages(p1, p2))
    _common(chunks, name="page_aware", max_tokens=50)
    # Every chunk must belong to exactly one page — no merging across pages.
    for c in chunks:
        assert c.page_number in {1, 2}
    page1_chunks = [c for c in chunks if c.page_number == 1]
    page2_chunks = [c for c in chunks if c.page_number == 2]
    assert page1_chunks, "no chunks from page 1"
    assert page2_chunks, "no chunks from page 2"
    # page 1 text must not appear in page 2 chunks and vice versa.
    for c in page1_chunks:
        assert "beta" not in c.text, "page-boundary leak: beta found in page 1 chunk"
    for c in page2_chunks:
        assert "alpha" not in c.text, "page-boundary leak: alpha found in page 2 chunk"


@pytest.mark.asyncio
async def test_page_aware_long_page_split_within() -> None:
    long_text = " ".join(f"word{i}" for i in range(300))
    chunks = await _page_aware(size=50, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(long_text)
    )
    _common(chunks, name="page_aware", max_tokens=50)
    assert len(chunks) > 1
    assert all(c.page_number == 1 for c in chunks)


@pytest.mark.asyncio
async def test_page_aware_section_path_is_page_reference() -> None:
    chunks = await _page_aware().chunk(
        document_id=uuid4(), pages=_pages("First page.", "Second page.")
    )
    paths = {c.section_path for c in chunks}
    assert "page:1" in paths
    assert "page:2" in paths


@pytest.mark.asyncio
async def test_page_aware_is_deterministic() -> None:
    pages = _pages(" ".join(f"w{i}" for i in range(200)))
    doc_id = uuid4()
    a = await _page_aware().chunk(document_id=doc_id, pages=pages)
    b = await _page_aware().chunk(document_id=doc_id, pages=pages)
    assert [c.text for c in a] == [c.text for c in b]


@pytest.mark.asyncio
async def test_page_aware_chunk_indexes_sequential() -> None:
    pages = [
        ExtractedSection(
            page_number=i + 1, text=" ".join(f"w{j}" for j in range(80)), char_count=80
        )
        for i in range(4)
    ]
    chunks = await _page_aware(size=50, overlap=10).chunk(document_id=uuid4(), pages=pages)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_page_aware_multilingual_no_crash() -> None:
    text = "Hello world. 你好世界。مرحبا بالعالم."
    chunks = await _page_aware(size=30, overlap=5).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks


# ===========================================================================
# HeadingAwareStrategy
# ===========================================================================


@pytest.mark.asyncio
async def test_heading_aware_empty_pages() -> None:
    assert await _heading().chunk(document_id=uuid4(), pages=[]) == []


@pytest.mark.asyncio
async def test_heading_aware_blank_text_returns_empty() -> None:
    assert await _heading().chunk(document_id=uuid4(), pages=_pages("\n\n")) == []


@pytest.mark.asyncio
async def test_heading_aware_no_headings_plain_text() -> None:
    text = " ".join(f"word{i}" for i in range(50))
    chunks = await _heading(size=100, overlap=15).chunk(document_id=uuid4(), pages=_pages(text))
    _common(chunks, name="heading_aware", max_tokens=100)


@pytest.mark.asyncio
async def test_heading_aware_flushes_at_heading_boundary() -> None:
    text = (
        "# Introduction\n\n" + " ".join(["intro"] * 30) + "\n\n"
        "# Methods\n\n" + " ".join(["method"] * 30)
    )
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    _common(chunks, name="heading_aware", max_tokens=200)
    assert len(chunks) >= 2
    intro_chunk = next((c for c in chunks if "intro" in c.text), None)
    method_chunk = next((c for c in chunks if "method" in c.text), None)
    assert intro_chunk is not None
    assert method_chunk is not None
    # They must be separate chunks.
    assert intro_chunk.chunk_index != method_chunk.chunk_index


@pytest.mark.asyncio
async def test_heading_aware_section_path_in_metadata() -> None:
    text = (
        "# Policy\n\n"
        "General policy text.\n\n"
        "## Leave\n\n"
        "Leave rules here.\n\n"
        "### Annual Leave\n\n"
        "Annual leave details."
    )
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks
    # Chunks under ## Leave should carry at least "Policy > Leave" in path.
    leave_chunk = next((c for c in chunks if "Leave rules" in c.text), None)
    if leave_chunk:
        assert leave_chunk.section_path is not None
        assert "Leave" in leave_chunk.section_path


@pytest.mark.asyncio
async def test_heading_aware_table_kept_atomic() -> None:
    table = "Name | Score | Grade\nAlice | 95 | A\nBob | 82 | B\nCarol | 78 | C"
    text = "# Results\n\n" + table + "\n\nSome summary paragraph."
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks
    # The table rows should appear in a single chunk (not split across two).
    table_chunks = [c for c in chunks if "Alice" in c.text]
    assert len(table_chunks) == 1, "table was split across chunks"


@pytest.mark.asyncio
async def test_heading_aware_code_block_kept_atomic() -> None:
    text = (
        "# Example\n\n"
        "Description.\n\n"
        "```python\n"
        "def factorial(n):\n"
        "    return 1 if n <= 1 else n * factorial(n - 1)\n"
        "```\n\n"
        "More text follows."
    )
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks
    code_chunks = [c for c in chunks if "factorial" in c.text]
    assert len(code_chunks) == 1, "code block was split"


@pytest.mark.asyncio
async def test_heading_aware_bullet_list_grouped() -> None:
    text = "# Checklist\n\n- Item one\n- Item two\n- Item three\n\nConclusion."
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks
    list_chunks = [c for c in chunks if "Item one" in c.text]
    assert list_chunks, "list items not found"
    # All list items should be in one chunk.
    assert len(list_chunks) == 1 or "Item two" in list_chunks[0].text


@pytest.mark.asyncio
async def test_heading_aware_block_type_in_metadata() -> None:
    text = "# Code Section\n\n```\nsome code\n```"
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks
    code_chunk = next((c for c in chunks if "some code" in c.text), None)
    if code_chunk:
        assert code_chunk.block_type == BLOCK_CODE


@pytest.mark.asyncio
async def test_heading_aware_oversized_section_split() -> None:
    long_section = " ".join(f"word{i}" for i in range(300))
    text = f"# Big Section\n\n{long_section}"
    chunks = await _heading(size=80, overlap=15).chunk(document_id=uuid4(), pages=_pages(text))
    _common(chunks, name="heading_aware", max_tokens=80)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_heading_aware_docx_caps_heading_detected() -> None:
    # ALL-CAPS lines as in DOCX exports should be treated as headings.
    text = "LEAVE POLICY\n\nEmployees are entitled to 20 days.\n\nRETIREMENT POLICY\n\nAge 65 is standard."
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks
    # Should have at least two chunks (one per policy section).
    leave = next((c for c in chunks if "20 days" in c.text), None)
    retire = next((c for c in chunks if "Age 65" in c.text), None)
    assert leave is not None and retire is not None
    assert leave.chunk_index != retire.chunk_index


@pytest.mark.asyncio
async def test_heading_aware_is_deterministic() -> None:
    text = (
        "# Chapter 1\n\nContent for chapter one.\n\n"
        "# Chapter 2\n\nContent for chapter two.\n\n"
        "# Chapter 3\n\nContent for chapter three."
    )
    pages = _pages(text)
    doc_id = uuid4()
    a = await _heading().chunk(document_id=doc_id, pages=pages)
    b = await _heading().chunk(document_id=doc_id, pages=pages)
    assert [c.text for c in a] == [c.text for c in b]


@pytest.mark.asyncio
async def test_heading_aware_chunk_indexes_sequential() -> None:
    text = "\n\n".join(
        f"# Section {i}\n\n" + " ".join(f"w{j}" for j in range(40)) for i in range(5)
    )
    chunks = await _heading(size=80, overlap=15).chunk(document_id=uuid4(), pages=_pages(text))
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_heading_aware_multi_page() -> None:
    p1 = "# Introduction\n\nThis is the introduction page."
    p2 = "# Methodology\n\nThis is the methodology page."
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(p1, p2))
    assert chunks
    page_numbers = {c.page_number for c in chunks if c.page_number is not None}
    assert 1 in page_numbers and 2 in page_numbers


@pytest.mark.asyncio
async def test_heading_aware_multilingual_no_crash() -> None:
    text = "# Hello\n\nHello world.\n\n# Bonjour\n\nBonjour le monde.\n\n# こんにちは\n\nこんにちは世界。"
    chunks = await _heading(size=100, overlap=15).chunk(document_id=uuid4(), pages=_pages(text))
    assert chunks


@pytest.mark.asyncio
async def test_heading_aware_fallback_no_structure() -> None:
    # Plain text with no headings should still produce chunks.
    text = " ".join(f"word{i}" for i in range(200))
    chunks = await _heading(size=80, overlap=15).chunk(document_id=uuid4(), pages=_pages(text))
    _common(chunks, name="heading_aware", max_tokens=80)


# ===========================================================================
# ChunkPayload new fields
# ===========================================================================


def test_chunk_payload_section_path_defaults_none() -> None:
    from app.domains.documents.chunking.protocol import ChunkPayload

    c = ChunkPayload(
        document_id=uuid4(),
        page_number=1,
        chunk_index=0,
        text="hi",
        token_count=1,
        embedding_model="m",
        index_version="v1",
    )
    assert c.section_path is None
    assert c.block_type is None


@pytest.mark.asyncio
async def test_page_aware_chunk_payload_has_section_path() -> None:
    chunks = await _page_aware().chunk(document_id=uuid4(), pages=_pages("Hello world."))
    assert chunks[0].section_path == "page:1"


@pytest.mark.asyncio
async def test_heading_aware_chunk_has_section_path_when_heading_present() -> None:
    text = "# My Heading\n\nContent under heading."
    chunks = await _heading(size=200, overlap=20).chunk(document_id=uuid4(), pages=_pages(text))
    content_chunk = next((c for c in chunks if "Content" in c.text), None)
    if content_chunk:
        assert content_chunk.section_path == "My Heading"
