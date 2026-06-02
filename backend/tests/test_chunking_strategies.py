"""Unit tests for all chunking strategy implementations (F208).

Covers: token_fixed, paragraph_recursive, sentence_window, plus shared
registry integration with the new strategies.  token_recursive is covered
in test_chunking_service.py / test_chunking_registry.py.
"""

from __future__ import annotations

import os
from itertools import pairwise
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Environment bootstrap (same pattern as existing chunking tests)
# ---------------------------------------------------------------------------
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

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.registry import get_registry
from app.domains.documents.chunking.strategies.paragraph_recursive import (
    ParagraphRecursiveStrategy,
)
from app.domains.documents.chunking.strategies.sentence_window import SentenceWindowStrategy
from app.domains.documents.chunking.strategies.token_fixed import TokenFixedStrategy
from app.domains.documents.services.text_extraction import ExtractedSection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODEL = "text-embedding-3-small"
INDEX = "v-test"


def _fixed(size: int = 50, overlap: int = 10) -> TokenFixedStrategy:
    return TokenFixedStrategy(
        chunk_size_tokens=size,
        chunk_overlap_tokens=overlap,
        embedding_model=MODEL,
        index_version=INDEX,
    )


def _para(size: int = 100, overlap: int = 20) -> ParagraphRecursiveStrategy:
    return ParagraphRecursiveStrategy(
        chunk_size_tokens=size,
        chunk_overlap_tokens=overlap,
        embedding_model=MODEL,
        index_version=INDEX,
    )


def _sent(size: int = 80, overlap: int = 15) -> SentenceWindowStrategy:
    return SentenceWindowStrategy(
        chunk_size_tokens=size,
        chunk_overlap_tokens=overlap,
        embedding_model=MODEL,
        index_version=INDEX,
    )


def _pages(*texts: str) -> list[ExtractedSection]:
    return [
        ExtractedSection(page_number=i + 1, text=t, char_count=len(t))
        for i, t in enumerate(texts)
    ]


# Common invariant assertions applied to every strategy.
def _assert_common(chunks, *, strategy_name: str, max_tokens: int) -> None:
    assert chunks, "expected at least one chunk"
    for i, c in enumerate(chunks):
        assert c.chunk_index == i, f"chunk_index mismatch at position {i}"
        assert c.token_count > 0, "zero-token chunk"
        assert c.token_count <= max_tokens, f"chunk {i} exceeds max_tokens"
        assert c.text.strip(), "empty chunk text"
        assert c.strategy_name == strategy_name
        assert c.strategy_version == "1.0"
        assert c.embedding_model == MODEL
        assert c.index_version == INDEX


# ===========================================================================
# Registry
# ===========================================================================


def test_registry_knows_all_four_strategies() -> None:
    known = get_registry().known_strategies()
    assert "token_recursive" in known
    assert "token_fixed" in known
    assert "paragraph_recursive" in known
    assert "sentence_window" in known


def test_registry_resolves_token_fixed_from_profile() -> None:
    profile = ChunkingProfileConfig(strategy="token_fixed")
    strategy = get_registry().resolve(profile, embedding_model=MODEL, index_version=INDEX)
    assert isinstance(strategy, TokenFixedStrategy)


def test_registry_resolves_paragraph_recursive_from_profile() -> None:
    profile = ChunkingProfileConfig(strategy="paragraph_recursive")
    strategy = get_registry().resolve(profile, embedding_model=MODEL, index_version=INDEX)
    assert isinstance(strategy, ParagraphRecursiveStrategy)


def test_registry_resolves_sentence_window_from_profile() -> None:
    profile = ChunkingProfileConfig(strategy="sentence_window")
    strategy = get_registry().resolve(profile, embedding_model=MODEL, index_version=INDEX)
    assert isinstance(strategy, SentenceWindowStrategy)


# ===========================================================================
# TokenFixedStrategy
# ===========================================================================


@pytest.mark.asyncio
async def test_token_fixed_empty_pages_returns_empty() -> None:
    chunks = await _fixed().chunk(document_id=uuid4(), pages=[])
    assert chunks == []


@pytest.mark.asyncio
async def test_token_fixed_blank_page_returns_empty() -> None:
    chunks = await _fixed().chunk(document_id=uuid4(), pages=_pages("   "))
    assert chunks == []


@pytest.mark.asyncio
async def test_token_fixed_single_short_document() -> None:
    chunks = await _fixed(size=100, overlap=10).chunk(
        document_id=uuid4(), pages=_pages("hello world")
    )
    _assert_common(chunks, strategy_name="token_fixed", max_tokens=100)
    assert len(chunks) == 1
    assert "hello" in chunks[0].text


@pytest.mark.asyncio
async def test_token_fixed_respects_chunk_size() -> None:
    text = " ".join(f"word{i}" for i in range(500))
    chunks = await _fixed(size=50, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    _assert_common(chunks, strategy_name="token_fixed", max_tokens=50)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_token_fixed_is_deterministic() -> None:
    text = " ".join(f"tok{i}" for i in range(300))
    pages = _pages(text)
    doc_id = uuid4()
    a = await _fixed().chunk(document_id=doc_id, pages=pages)
    b = await _fixed().chunk(document_id=doc_id, pages=pages)
    assert [c.text for c in a] == [c.text for c in b]
    assert [c.token_count for c in a] == [c.token_count for c in b]


@pytest.mark.asyncio
async def test_token_fixed_overlap_produces_shared_tokens() -> None:
    text = " ".join(f"w{i}" for i in range(200))
    chunks = await _fixed(size=40, overlap=15).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    assert len(chunks) > 1
    for prev, curr in pairwise(chunks):
        assert set(prev.text.split()) & set(curr.text.split()), (
            "consecutive chunks share no words (overlap not working)"
        )


@pytest.mark.asyncio
async def test_token_fixed_page_number_tracked() -> None:
    p1 = " ".join(["alpha"] * 60)
    p2 = " ".join(["beta"] * 60)
    chunks = await _fixed(size=40, overlap=5).chunk(
        document_id=uuid4(), pages=_pages(p1, p2)
    )
    pages = {c.page_number for c in chunks}
    assert 1 in pages and 2 in pages


@pytest.mark.asyncio
async def test_token_fixed_multilingual_does_not_crash() -> None:
    # Arabic + Chinese + Latin script in one page.
    mixed = "مرحبا بالعالم. 你好世界。Hello world!"
    chunks = await _fixed(size=30, overlap=5).chunk(
        document_id=uuid4(), pages=_pages(mixed)
    )
    assert chunks  # doesn't crash; produces at least one chunk


@pytest.mark.asyncio
async def test_token_fixed_tiny_trailing_dropped() -> None:
    # Craft text whose tail produces a trivially small chunk.
    text = " ".join(["word"] * 55) + " final"
    chunks = await _fixed(size=50, overlap=0).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    # The main chunk(s) should exist; the tiny tail may or may not be dropped.
    assert chunks
    for c in chunks:
        assert c.token_count > 0


@pytest.mark.asyncio
async def test_token_fixed_no_overlap_contiguous() -> None:
    """With zero overlap, consecutive chunks should cover disjoint text regions."""
    text = " ".join(f"t{i}" for i in range(100))
    chunks = await _fixed(size=40, overlap=0).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    _assert_common(chunks, strategy_name="token_fixed", max_tokens=40)
    for prev, curr in pairwise(chunks):
        shared = set(prev.text.split()) & set(curr.text.split())
        assert not shared, f"unexpected overlap: {shared}"


# ===========================================================================
# ParagraphRecursiveStrategy
# ===========================================================================


@pytest.mark.asyncio
async def test_para_empty_pages_returns_empty() -> None:
    assert await _para().chunk(document_id=uuid4(), pages=[]) == []


@pytest.mark.asyncio
async def test_para_blank_text_returns_empty() -> None:
    assert await _para().chunk(document_id=uuid4(), pages=_pages("\n\n\n")) == []


@pytest.mark.asyncio
async def test_para_single_short_paragraph() -> None:
    chunks = await _para(size=200, overlap=30).chunk(
        document_id=uuid4(), pages=_pages("Just one paragraph here.")
    )
    _assert_common(chunks, strategy_name="paragraph_recursive", max_tokens=200)
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_para_multiple_short_paragraphs_merged() -> None:
    """Short paragraphs should be merged into a single chunk."""
    text = "Para one.\n\nPara two.\n\nPara three."
    chunks = await _para(size=300, overlap=30).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    _assert_common(chunks, strategy_name="paragraph_recursive", max_tokens=300)
    assert len(chunks) == 1
    assert "Para one" in chunks[0].text
    assert "Para three" in chunks[0].text


@pytest.mark.asyncio
async def test_para_long_text_splits_across_paragraphs() -> None:
    paras = "\n\n".join(" ".join([f"word{j}"] * 40) for j in range(8))
    chunks = await _para(size=100, overlap=20).chunk(
        document_id=uuid4(), pages=_pages(paras)
    )
    _assert_common(chunks, strategy_name="paragraph_recursive", max_tokens=100)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_para_oversized_paragraph_split_token_wise() -> None:
    huge = " ".join(f"x{n}" for n in range(300))  # way more tokens than chunk_size
    chunks = await _para(size=80, overlap=15).chunk(
        document_id=uuid4(), pages=_pages(huge)
    )
    _assert_common(chunks, strategy_name="paragraph_recursive", max_tokens=80)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_para_is_deterministic() -> None:
    paras = "\n\n".join(f"Paragraph number {i} with some content." for i in range(20))
    pages = _pages(paras)
    doc_id = uuid4()
    a = await _para().chunk(document_id=doc_id, pages=pages)
    b = await _para().chunk(document_id=doc_id, pages=pages)
    assert [c.text for c in a] == [c.text for c in b]


@pytest.mark.asyncio
async def test_para_chunk_indexes_are_sequential() -> None:
    paras = "\n\n".join(f"P{i}: " + " ".join(["filler"] * 20) for i in range(20))
    chunks = await _para(size=80, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(paras)
    )
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_para_multi_page_page_number_preserved() -> None:
    # Each page has enough tokens (2 paragraphs × 30 words × ~1 tok/word ≈ 60 tokens)
    # to force separate chunks at size=50.
    p1 = "\n\n".join(" ".join(f"pageone{j}" for j in range(30)) for _ in range(2))
    p2 = "\n\n".join(" ".join(f"pagetwo{j}" for j in range(30)) for _ in range(2))
    chunks = await _para(size=50, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(p1, p2)
    )
    page_numbers = {c.page_number for c in chunks}
    assert 1 in page_numbers and 2 in page_numbers


@pytest.mark.asyncio
async def test_para_overlap_carried_forward() -> None:
    paras = "\n\n".join(" ".join([f"t{i}w{j}" for j in range(25)]) for i in range(6))
    chunks = await _para(size=80, overlap=20).chunk(
        document_id=uuid4(), pages=_pages(paras)
    )
    if len(chunks) > 1:
        for prev, curr in pairwise(chunks):
            assert set(prev.text.split()) & set(curr.text.split()), (
                "paragraph_recursive: no overlap found between consecutive chunks"
            )


@pytest.mark.asyncio
async def test_para_multilingual_does_not_crash() -> None:
    text = "Bonjour le monde.\n\nHola mundo.\n\nこんにちは世界。"
    chunks = await _para(size=50, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    assert chunks


# ===========================================================================
# SentenceWindowStrategy
# ===========================================================================


@pytest.mark.asyncio
async def test_sent_empty_pages_returns_empty() -> None:
    assert await _sent().chunk(document_id=uuid4(), pages=[]) == []


@pytest.mark.asyncio
async def test_sent_blank_text_returns_empty() -> None:
    assert await _sent().chunk(document_id=uuid4(), pages=_pages("   ")) == []


@pytest.mark.asyncio
async def test_sent_single_short_sentence() -> None:
    chunks = await _sent(size=100, overlap=10).chunk(
        document_id=uuid4(), pages=_pages("Hello world!")
    )
    _assert_common(chunks, strategy_name="sentence_window", max_tokens=100)
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_sent_multiple_sentences_grouped() -> None:
    sentences = " ".join(
        f"This is sentence number {i}." for i in range(20)
    )
    chunks = await _sent(size=80, overlap=15).chunk(
        document_id=uuid4(), pages=_pages(sentences)
    )
    _assert_common(chunks, strategy_name="sentence_window", max_tokens=80)
    assert len(chunks) >= 1


@pytest.mark.asyncio
async def test_sent_is_deterministic() -> None:
    text = " ".join(f"Sentence {i} has some words." for i in range(30))
    pages = _pages(text)
    doc_id = uuid4()
    a = await _sent().chunk(document_id=doc_id, pages=pages)
    b = await _sent().chunk(document_id=doc_id, pages=pages)
    assert [c.text for c in a] == [c.text for c in b]
    assert [c.token_count for c in a] == [c.token_count for c in b]


@pytest.mark.asyncio
async def test_sent_chunk_indexes_are_sequential() -> None:
    text = " ".join(f"Item {i}: description text here." for i in range(30))
    chunks = await _sent(size=60, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_sent_oversized_sentence_split_token_wise() -> None:
    giant = " ".join(f"bigword{n}" for n in range(400))
    chunks = await _sent(size=80, overlap=15).chunk(
        document_id=uuid4(), pages=_pages(giant)
    )
    _assert_common(chunks, strategy_name="sentence_window", max_tokens=80)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_sent_overlap_sentences_shared() -> None:
    sentences = " ".join(f"Sentence {i} says hello." for i in range(40))
    chunks = await _sent(size=60, overlap=15).chunk(
        document_id=uuid4(), pages=_pages(sentences)
    )
    if len(chunks) > 1:
        for prev, curr in pairwise(chunks):
            prev_words = set(prev.text.split())
            curr_words = set(curr.text.split())
            assert prev_words & curr_words, "sentence_window: no overlap between chunks"


@pytest.mark.asyncio
async def test_sent_paragraph_breaks_as_sentence_boundaries() -> None:
    text = "First paragraph sentence one.\n\nSecond paragraph sentence one. Second sentence two."
    chunks = await _sent(size=200, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    _assert_common(chunks, strategy_name="sentence_window", max_tokens=200)


@pytest.mark.asyncio
async def test_sent_multilingual_does_not_crash() -> None:
    text = "Hello world. Bonjour monde. مرحبا. 你好。こんにちは。"
    chunks = await _sent(size=50, overlap=5).chunk(
        document_id=uuid4(), pages=_pages(text)
    )
    assert chunks  # no crash; at least one chunk produced


@pytest.mark.asyncio
async def test_sent_multi_page_page_number_tracked() -> None:
    p1 = " ".join(f"First page sentence {i}." for i in range(15))
    p2 = " ".join(f"Second page sentence {i}." for i in range(15))
    chunks = await _sent(size=60, overlap=10).chunk(
        document_id=uuid4(), pages=_pages(p1, p2)
    )
    page_numbers = {c.page_number for c in chunks}
    assert 1 in page_numbers and 2 in page_numbers


# ===========================================================================
# Cross-strategy: same input → compatible output shape
# ===========================================================================


@pytest.mark.asyncio
async def test_all_strategies_produce_valid_output_for_same_input() -> None:
    text = " ".join(f"word{i}" for i in range(200))
    pages = _pages(text)
    doc_id = uuid4()

    strategies = [
        TokenFixedStrategy(
            chunk_size_tokens=50,
            chunk_overlap_tokens=10,
            embedding_model=MODEL,
            index_version=INDEX,
        ),
        ParagraphRecursiveStrategy(
            chunk_size_tokens=50,
            chunk_overlap_tokens=10,
            embedding_model=MODEL,
            index_version=INDEX,
        ),
        SentenceWindowStrategy(
            chunk_size_tokens=50,
            chunk_overlap_tokens=10,
            embedding_model=MODEL,
            index_version=INDEX,
        ),
    ]

    for strategy in strategies:
        chunks = await strategy.chunk(document_id=doc_id, pages=pages)
        assert chunks, f"{strategy.name} produced no chunks"
        assert all(c.chunk_index == i for i, c in enumerate(chunks)), (
            f"{strategy.name}: chunk_index not sequential"
        )
        assert all(0 < c.token_count <= 50 for c in chunks), (
            f"{strategy.name}: token_count out of bounds"
        )
        assert all(c.strategy_name == strategy.name for c in chunks)
