"""Unit tests for hierarchical parent-child chunking strategy (F211).

Covers: parent/child structure, chunk_index sequencing, parent_chunk_index FK,
child_count accuracy, metadata propagation, validation errors, from_profile factory,
and registry registration.
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

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.registry import get_registry
from app.domains.documents.chunking.strategies.hierarchical import HierarchicalStrategy
from app.domains.documents.services.text_extraction import ExtractedSection

MODEL = "text-embedding-3-small"
IDX = "v-test"


def _pages(*texts: str) -> list[ExtractedSection]:
    return [
        ExtractedSection(page_number=i + 1, text=t, char_count=len(t))
        for i, t in enumerate(texts)
    ]


def _strategy(
    child_size: int = 100,
    child_overlap: int = 10,
    parent_size: int = 400,
    parent_overlap: int = 0,
) -> HierarchicalStrategy:
    return HierarchicalStrategy(
        chunk_size_tokens=child_size,
        chunk_overlap_tokens=child_overlap,
        parent_chunk_size_tokens=parent_size,
        parent_chunk_overlap_tokens=parent_overlap,
        embedding_model=MODEL,
        index_version=IDX,
    )


# ---------------------------------------------------------------------------
# Two-level structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hierarchical_produces_parent_and_child_chunks() -> None:
    text = " ".join(["word"] * 300)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    parents = [c for c in chunks if c.chunk_level == 0]
    children = [c for c in chunks if c.chunk_level == 1]

    assert parents, "should produce at least one parent chunk"
    assert children, "should produce at least one child chunk"
    assert len(chunks) == len(parents) + len(children)


@pytest.mark.asyncio
async def test_hierarchical_chunk_indices_are_sequential() -> None:
    text = " ".join(["word"] * 250)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_hierarchical_children_link_to_correct_parent() -> None:
    text = " ".join(["token"] * 300)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    parent_indices = {c.chunk_index for c in chunks if c.chunk_level == 0}
    for c in chunks:
        if c.chunk_level == 1:
            assert c.parent_chunk_index is not None
            assert c.parent_chunk_index in parent_indices, (
                f"child at index {c.chunk_index} has parent_chunk_index "
                f"{c.parent_chunk_index} which is not a known parent"
            )


@pytest.mark.asyncio
async def test_hierarchical_parent_child_count_matches_actual_children() -> None:
    text = " ".join(["text"] * 300)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    for parent in (c for c in chunks if c.chunk_level == 0):
        actual = sum(
            1 for c in chunks
            if c.chunk_level == 1 and c.parent_chunk_index == parent.chunk_index
        )
        assert parent.child_count == actual, (
            f"parent at index {parent.chunk_index} has child_count={parent.child_count} "
            f"but {actual} children reference it"
        )


@pytest.mark.asyncio
async def test_hierarchical_parents_have_no_parent_chunk_index() -> None:
    text = " ".join(["word"] * 200)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    for parent in (c for c in chunks if c.chunk_level == 0):
        assert parent.parent_chunk_index is None
        assert parent.child_count is not None and parent.child_count > 0


@pytest.mark.asyncio
async def test_hierarchical_children_have_no_child_count() -> None:
    text = " ".join(["word"] * 200)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    for child in (c for c in chunks if c.chunk_level == 1):
        assert child.child_count is None


# ---------------------------------------------------------------------------
# Metadata integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hierarchical_document_id_preserved_on_all_chunks() -> None:
    document_id = uuid4()
    text = " ".join(["word"] * 200)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=document_id, pages=_pages(text)
    )

    for c in chunks:
        assert c.document_id == document_id


@pytest.mark.asyncio
async def test_hierarchical_strategy_name_and_version_on_all_chunks() -> None:
    text = " ".join(["word"] * 200)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    for c in chunks:
        assert c.strategy_name == "hierarchical"
        assert c.strategy_version == "1.0"


@pytest.mark.asyncio
async def test_hierarchical_section_path_propagated_from_parent_to_children() -> None:
    text = " ".join(["content"] * 300)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    # Each child should carry the section_path of its parent.
    parent_by_index = {c.chunk_index: c for c in chunks if c.chunk_level == 0}
    for child in (c for c in chunks if c.chunk_level == 1):
        parent = parent_by_index.get(child.parent_chunk_index)
        if parent is not None:
            assert child.section_path == parent.section_path


@pytest.mark.asyncio
async def test_hierarchical_embedding_model_and_index_version_correct() -> None:
    text = " ".join(["word"] * 150)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    for c in chunks:
        assert c.embedding_model == MODEL
        assert c.index_version == IDX


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hierarchical_empty_pages_returns_empty_list() -> None:
    chunks = await _strategy().chunk(document_id=uuid4(), pages=[])
    assert chunks == []


@pytest.mark.asyncio
async def test_hierarchical_very_short_document_produces_single_parent() -> None:
    text = "Short document."
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(text)
    )

    parents = [c for c in chunks if c.chunk_level == 0]
    assert len(parents) == 1


@pytest.mark.asyncio
async def test_hierarchical_multiple_pages_processed() -> None:
    page1 = " ".join(["alpha"] * 150)
    page2 = " ".join(["beta"] * 150)
    chunks = await _strategy(child_size=50, parent_size=200).chunk(
        document_id=uuid4(), pages=_pages(page1, page2)
    )

    # Multiple pages should yield multiple parents and more children.
    parents = [c for c in chunks if c.chunk_level == 0]
    children = [c for c in chunks if c.chunk_level == 1]
    assert len(parents) >= 2
    assert len(children) >= 2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_hierarchical_raises_if_child_overlap_not_smaller_than_child_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap_tokens"):
        HierarchicalStrategy(
            chunk_size_tokens=100,
            chunk_overlap_tokens=100,
            parent_chunk_size_tokens=400,
            embedding_model=MODEL,
            index_version=IDX,
        )


def test_hierarchical_raises_if_parent_size_not_larger_than_child_size() -> None:
    with pytest.raises(ValueError, match="parent_chunk_size_tokens"):
        HierarchicalStrategy(
            chunk_size_tokens=300,
            chunk_overlap_tokens=20,
            parent_chunk_size_tokens=200,
            embedding_model=MODEL,
            index_version=IDX,
        )


def test_hierarchical_raises_if_parent_overlap_not_smaller_than_parent_size() -> None:
    with pytest.raises(ValueError, match="parent_chunk_overlap_tokens"):
        HierarchicalStrategy(
            chunk_size_tokens=100,
            chunk_overlap_tokens=10,
            parent_chunk_size_tokens=400,
            parent_chunk_overlap_tokens=500,
            embedding_model=MODEL,
            index_version=IDX,
        )


def test_hierarchical_raises_if_parent_size_equal_to_child_size() -> None:
    with pytest.raises(ValueError, match="parent_chunk_size_tokens"):
        HierarchicalStrategy(
            chunk_size_tokens=200,
            chunk_overlap_tokens=10,
            parent_chunk_size_tokens=200,
            embedding_model=MODEL,
            index_version=IDX,
        )


# ---------------------------------------------------------------------------
# from_profile factory
# ---------------------------------------------------------------------------


def test_hierarchical_from_profile_applies_default_size_multiplier() -> None:
    profile = ChunkingProfileConfig.model_construct(
        strategy="hierarchical",
        chunk_size_tokens=200,
        chunk_overlap_tokens=20,
        min_tokens=None,
        language=None,
        strategy_options={},
    )
    strategy = HierarchicalStrategy.from_profile(profile, embedding_model=MODEL, index_version=IDX)

    # Default multiplier is 3: min(200 x 3, 3000) = 600
    assert strategy.parent_chunk_size_tokens == 600
    assert strategy.parent_chunk_overlap_tokens == 0
    assert strategy.chunk_size_tokens == 200
    assert strategy.chunk_overlap_tokens == 20


def test_hierarchical_from_profile_caps_parent_size_at_3000() -> None:
    profile = ChunkingProfileConfig.model_construct(
        strategy="hierarchical",
        chunk_size_tokens=1200,
        chunk_overlap_tokens=100,
        min_tokens=None,
        language=None,
        strategy_options={},
    )
    strategy = HierarchicalStrategy.from_profile(profile, embedding_model=MODEL, index_version=IDX)

    # 1200 x 3 = 3600; capped at 3000
    assert strategy.parent_chunk_size_tokens == 3000


def test_hierarchical_from_profile_respects_explicit_parent_size_and_overlap() -> None:
    profile = ChunkingProfileConfig.model_construct(
        strategy="hierarchical",
        chunk_size_tokens=200,
        chunk_overlap_tokens=20,
        min_tokens=None,
        language=None,
        strategy_options={"parent_chunk_size_tokens": 900, "parent_chunk_overlap_tokens": 50},
    )
    strategy = HierarchicalStrategy.from_profile(profile, embedding_model=MODEL, index_version=IDX)

    assert strategy.parent_chunk_size_tokens == 900
    assert strategy.parent_chunk_overlap_tokens == 50


def test_hierarchical_from_profile_respects_custom_parent_strategy() -> None:
    profile = ChunkingProfileConfig.model_construct(
        strategy="hierarchical",
        chunk_size_tokens=200,
        chunk_overlap_tokens=20,
        min_tokens=None,
        language=None,
        strategy_options={"parent_strategy": "paragraph_recursive"},
    )
    strategy = HierarchicalStrategy.from_profile(profile, embedding_model=MODEL, index_version=IDX)

    assert strategy.parent_strategy_name == "paragraph_recursive"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_hierarchical_is_registered_in_strategy_registry() -> None:
    registry = get_registry()
    assert "hierarchical" in registry.known_strategies()


def test_hierarchical_can_be_resolved_from_registry() -> None:
    registry = get_registry()
    profile = ChunkingProfileConfig.model_construct(
        strategy="hierarchical",
        chunk_size_tokens=300,
        chunk_overlap_tokens=30,
        min_tokens=None,
        language=None,
        strategy_options={},
    )
    strategy = registry.resolve(profile, embedding_model=MODEL, index_version=IDX)
    assert isinstance(strategy, HierarchicalStrategy)
    assert strategy.chunk_size_tokens == 300
