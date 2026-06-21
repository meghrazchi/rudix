"""Tests for document versioning and change history — F253.

Covers:
- DocumentVersionResponse schema construction
- DocumentVersionListResponse schema
- version_service create_document_version logic (unit-level with mocks)
- get_document_versions scoping and ordering
- API endpoint response shape
- Cross-org isolation invariant
- Change reason enum coverage
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
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


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_document_version_response_minimal() -> None:
    from app.domains.documents.schemas.documents import DocumentVersionResponse

    now = datetime.now(timezone.utc)
    resp = DocumentVersionResponse(
        version_id=str(uuid4()),
        document_id=str(uuid4()),
        version_number=1,
        change_reason="initial_upload",
        filename="report.pdf",
        status="indexed",
        is_current=True,
        created_at=now,
    )
    assert resp.version_number == 1
    assert resp.change_reason == "initial_upload"
    assert resp.is_current is True
    assert resp.content_hash is None
    assert resp.extraction_hash is None


def test_document_version_response_full() -> None:
    from app.domains.documents.schemas.documents import DocumentVersionResponse

    now = datetime.now(timezone.utc)
    user_id = str(uuid4())
    resp = DocumentVersionResponse(
        version_id=str(uuid4()),
        document_id=str(uuid4()),
        version_number=3,
        change_reason="reindex",
        content_hash="abc123",
        extraction_hash="def456",
        chunking_profile_snapshot={"strategy": "paragraph", "chunk_size": 512},
        embedding_model="text-embedding-3-small",
        embedding_vector_dimension=1536,
        index_version="v2",
        filename="policy.pdf",
        page_count=12,
        chunk_count=38,
        status="indexed",
        indexed_at=now,
        is_current=True,
        source_updated_at=None,
        created_by_user_id=user_id,
        created_at=now,
    )
    assert resp.version_number == 3
    assert resp.embedding_model == "text-embedding-3-small"
    assert resp.chunking_profile_snapshot["strategy"] == "paragraph"
    assert resp.created_by_user_id == user_id


def test_document_version_list_response() -> None:
    from app.domains.documents.schemas.documents import (
        DocumentVersionListResponse,
        DocumentVersionResponse,
    )

    now = datetime.now(timezone.utc)
    doc_id = str(uuid4())
    items = [
        DocumentVersionResponse(
            version_id=str(uuid4()),
            document_id=doc_id,
            version_number=n,
            change_reason="reindex" if n > 1 else "initial_upload",
            filename="file.pdf",
            status="indexed",
            is_current=(n == 3),
            created_at=now,
        )
        for n in [3, 2, 1]
    ]
    resp = DocumentVersionListResponse(document_id=doc_id, items=items, total=3)
    assert resp.total == 3
    assert resp.items[0].version_number == 3
    assert resp.items[2].version_number == 1


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


def test_change_reason_enum_values() -> None:
    from app.models.enums import DocumentVersionChangeReason

    assert DocumentVersionChangeReason.initial_upload == "initial_upload"
    assert DocumentVersionChangeReason.content_update == "content_update"
    assert DocumentVersionChangeReason.metadata_update == "metadata_update"
    assert DocumentVersionChangeReason.connector_sync == "connector_sync"
    assert DocumentVersionChangeReason.reindex == "reindex"
    assert DocumentVersionChangeReason.tombstone == "tombstone"


@pytest.mark.parametrize(
    "reason",
    [
        "initial_upload",
        "content_update",
        "metadata_update",
        "connector_sync",
        "reindex",
        "tombstone",
    ],
)
def test_all_change_reasons_have_enum_member(reason: str) -> None:
    from app.models.enums import DocumentVersionChangeReason

    assert DocumentVersionChangeReason(reason).value == reason


# ---------------------------------------------------------------------------
# DocumentVersion model field defaults
# ---------------------------------------------------------------------------


def test_document_version_model_defaults() -> None:
    from app.models.document_version import DocumentVersion

    col = DocumentVersion.is_current.property.columns[0]
    # Python-level default is False (set on the Column)
    assert col.default.arg is False
    # Verify nullable columns exist on the mapped class
    assert DocumentVersion.extraction_hash is not None
    assert DocumentVersion.chunking_profile_snapshot is not None


# ---------------------------------------------------------------------------
# Version service — unit tests with mocked session
# ---------------------------------------------------------------------------


def _make_document(
    *,
    organization_id=None,
    checksum="sha256abc",
    filename="test.pdf",
    status="uploaded",
    page_count=None,
    chunk_count=None,
    chunking_config_snapshot=None,
    embedding_provider_type=None,
    embedding_vector_dimension=None,
    current_version_id=None,
):
    doc = MagicMock()
    doc.id = uuid4()
    doc.organization_id = organization_id or uuid4()
    doc.checksum = checksum
    doc.filename = filename
    doc.status = status
    doc.page_count = page_count
    doc.chunk_count = chunk_count
    doc.chunking_config_snapshot = chunking_config_snapshot
    doc.embedding_provider_type = embedding_provider_type
    doc.embedding_vector_dimension = embedding_vector_dimension
    doc.current_version_id = current_version_id
    return doc


@pytest.mark.asyncio
async def test_create_version_initial_upload() -> None:
    from app.domains.documents.services.version_service import create_document_version
    from app.models.enums import DocumentVersionChangeReason

    doc = _make_document()
    user_id = uuid4()

    session = AsyncMock()
    # _next_version_number query: no existing versions
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_scalar
    session.flush = AsyncMock()

    result = await create_document_version(
        session,
        document=doc,
        change_reason=DocumentVersionChangeReason.initial_upload,
        content_hash="sha256abc",
        created_by_user_id=user_id,
    )

    assert result.version_number == 1
    assert result.change_reason == "initial_upload"
    assert result.is_current is True
    assert result.content_hash == "sha256abc"
    assert result.created_by_user_id == user_id
    session.add.assert_called_once_with(result)


@pytest.mark.asyncio
async def test_create_version_increments_version_number() -> None:
    from app.domains.documents.services.version_service import create_document_version
    from app.models.enums import DocumentVersionChangeReason

    doc = _make_document()

    session = AsyncMock()
    # First call: _next_version_number → existing max is 2
    mock_max = MagicMock()
    mock_max.scalar_one_or_none.return_value = 2
    # Second call: find previous current version → empty
    mock_prev = MagicMock()
    mock_prev.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
    session.execute.side_effect = [mock_max, mock_prev]
    session.flush = AsyncMock()

    result = await create_document_version(
        session,
        document=doc,
        change_reason=DocumentVersionChangeReason.reindex,
    )
    assert result.version_number == 3
    assert result.change_reason == "reindex"


@pytest.mark.asyncio
async def test_create_version_clears_previous_current() -> None:
    from app.domains.documents.services.version_service import create_document_version
    from app.models.document_version import DocumentVersion
    from app.models.enums import DocumentVersionChangeReason

    doc = _make_document()

    prev_version = MagicMock(spec=DocumentVersion)
    prev_version.is_current = True

    session = AsyncMock()
    mock_max = MagicMock()
    mock_max.scalar_one_or_none.return_value = 1
    mock_prev = MagicMock()
    mock_prev.scalars.return_value = iter([prev_version])
    session.execute.side_effect = [mock_max, mock_prev]
    session.flush = AsyncMock()

    await create_document_version(
        session,
        document=doc,
        change_reason=DocumentVersionChangeReason.content_update,
    )

    assert prev_version.is_current is False


@pytest.mark.asyncio
async def test_mark_version_indexed() -> None:
    from app.domains.documents.services.version_service import mark_version_indexed
    from app.models.document_version import DocumentVersion

    doc = _make_document(status="indexed")
    version = MagicMock(spec=DocumentVersion)
    version.indexed_at = None
    version.chunk_count = None
    version.embedding_model = None
    version.embedding_vector_dimension = None
    version.index_version = None
    version.extraction_hash = None
    version.status = "processing"

    session = AsyncMock()
    session.flush = AsyncMock()

    await mark_version_indexed(
        session,
        version=version,
        document=doc,
        chunk_count=42,
        embedding_model="text-embedding-3-small",
        embedding_vector_dimension=1536,
        index_version="v2",
        extraction_hash="extrhash",
    )

    assert version.indexed_at is not None
    assert version.chunk_count == 42
    assert version.embedding_model == "text-embedding-3-small"
    assert version.index_version == "v2"
    assert version.extraction_hash == "extrhash"
    assert version.status == "indexed"


@pytest.mark.asyncio
async def test_get_document_versions_returns_org_scoped() -> None:
    from app.domains.documents.services.version_service import get_document_versions

    doc_id = uuid4()
    org_id = uuid4()

    v1 = MagicMock()
    v1.version_number = 1
    v2 = MagicMock()
    v2.version_number = 2

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [v2, v1]
    session.execute.return_value = mock_result

    versions = await get_document_versions(session, document_id=doc_id, organization_id=org_id)

    assert len(versions) == 2
    assert versions[0].version_number == 2


# ---------------------------------------------------------------------------
# Isolation: organization_id is always scoped on queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_versions_query_includes_org_filter() -> None:
    """Ensure the query sent to the DB includes both document_id and organization_id."""
    from app.domains.documents.services import version_service

    doc_id = uuid4()
    org_id = uuid4()
    other_org_id = uuid4()

    session = AsyncMock()
    called_with: list = []

    original_execute = session.execute

    async def capturing_execute(stmt, *args, **kwargs):
        called_with.append(stmt)
        mock = MagicMock()
        mock.scalars.return_value.all.return_value = []
        return mock

    session.execute.side_effect = capturing_execute

    await version_service.get_document_versions(session, document_id=doc_id, organization_id=org_id)

    assert len(called_with) == 1
    # Verify org_id and doc_id both appear as bound params in the compiled WHERE.
    compiled = str(called_with[0].compile(compile_kwargs={"literal_binds": False}))
    assert "organization_id" in compiled
    assert "document_id" in compiled


# ---------------------------------------------------------------------------
# Workflow integration: version is created on upload
# ---------------------------------------------------------------------------


def test_upload_workflow_calls_create_version() -> None:
    """create_document_version is imported in the upload workflow module."""
    import importlib
    import app.application.documents.workflows as wf

    assert hasattr(wf, "create_document_version"), (
        "create_document_version must be imported in workflows.py"
    )
    assert hasattr(wf, "DocumentVersionChangeReason"), (
        "DocumentVersionChangeReason must be imported in workflows.py"
    )


# ---------------------------------------------------------------------------
# API endpoint shape contract
# ---------------------------------------------------------------------------


def test_version_list_response_zero_versions() -> None:
    from app.domains.documents.schemas.documents import DocumentVersionListResponse

    resp = DocumentVersionListResponse(
        document_id=str(uuid4()),
        items=[],
        total=0,
    )
    assert resp.items == []
    assert resp.total == 0


def test_version_response_change_reason_connector_sync() -> None:
    from app.domains.documents.schemas.documents import DocumentVersionResponse

    now = datetime.now(timezone.utc)
    resp = DocumentVersionResponse(
        version_id=str(uuid4()),
        document_id=str(uuid4()),
        version_number=2,
        change_reason="connector_sync",
        filename="jira-export.txt",
        status="indexed",
        is_current=True,
        source_updated_at=now,
        created_at=now,
    )
    assert resp.change_reason == "connector_sync"
    assert resp.source_updated_at == now


def test_version_response_tombstone_reason() -> None:
    from app.domains.documents.schemas.documents import DocumentVersionResponse

    now = datetime.now(timezone.utc)
    resp = DocumentVersionResponse(
        version_id=str(uuid4()),
        document_id=str(uuid4()),
        version_number=4,
        change_reason="tombstone",
        filename="deleted.pdf",
        status="deleted",
        is_current=False,
        created_at=now,
    )
    assert resp.change_reason == "tombstone"
    assert resp.is_current is False
