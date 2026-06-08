"""Tests for F245: connector attachment and file ingestion bridge through document lifecycle."""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Minimal env config required before importing app modules.
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

from app.domains.connectors.services.ingestion_bridge import (
    ConnectorIngestionBridge,
    IngestionResult,
    _safe_filename,
    _build_storage_key,
)
from app.domains.documents.services.malware_scan import MalwareScanResult, MalwareScanService
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceDocument, SourceReference
from app.models.document import Document
from app.models.enums import (
    ConnectorAuthType,
    ConnectorConnectionStatus,
    DocumentIngestionSource,
    DocumentStatus,
    ExternalItemType,
    ExternalItemVisibility,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Byte fixtures for common file types
# ---------------------------------------------------------------------------

_PDF_BYTES = b"%PDF-1.7\n%%EOF"
_DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 30 + b"word/document.xml"
_TXT_BYTES = b"Hello connector world!"
_INFECTED_PDF = b"%PDF-1.7\nEICARVIRUS"  # magic bytes OK but flagged by mock scanner
_ENCRYPTED_PDF = b"%PDF-1.7\n/Encrypt <<>>\n%%EOF"


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------


@dataclass
class BridgeContext:
    org_id: UUID
    user_id: UUID
    connection: ConnectorConnection
    external_item: ExternalItem


async def _make_bridge_context(db_session: AsyncSession) -> BridgeContext:
    org = Organization(name=f"BridgeOrg {uuid4()}", slug=f"bridge-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"bridge-user-{uuid4()}",
        email=f"bridge-{uuid4().hex[:8]}@example.test",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="admin"))
    await db_session.flush()

    provider = ConnectorProvider(
        key=f"test_{uuid4().hex[:6]}",
        display_name="Test Provider",
        auth_type=ConnectorAuthType.api_token.value,
        capabilities_json=[],
        config_schema_json={},
        rate_limits_json=[],
        export_formats_json=[],
        is_enabled=True,
    )
    db_session.add(provider)
    await db_session.flush()

    connection = ConnectorConnection(
        organization_id=org.id,
        provider_id=provider.id,
        display_name="Bridge Test Connection",
        status=ConnectorConnectionStatus.active.value,
        config_json={},
        created_by_user_id=user.id,
    )
    db_session.add(connection)
    await db_session.flush()

    ext_item = ExternalItem(
        organization_id=org.id,
        connection_id=connection.id,
        provider_item_id=f"file-{uuid4().hex[:8]}",
        item_type=ExternalItemType.cloud_file.value,
        title="Test File",
        source_url="https://drive.example.com/file/test",
        content_hash="a" * 64,
        source_updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        sync_version=1,
        visibility=ExternalItemVisibility.org_wide.value,
        metadata_json={},
        permissions_json={},
    )
    db_session.add(ext_item)
    await db_session.flush()

    return BridgeContext(
        org_id=org.id,
        user_id=user.id,
        connection=connection,
        external_item=ext_item,
    )


def _clean_scan() -> MalwareScanResult:
    return MalwareScanResult(status="clean", scanner="clamav", duration_ms=1)


def _infected_scan() -> MalwareScanResult:
    return MalwareScanResult(status="infected", scanner="clamav", signature="EICAR.TEST")


def _skipped_scan() -> MalwareScanResult:
    return MalwareScanResult(status="skipped")


def _bridge(scan_result: MalwareScanResult | None = None) -> ConnectorIngestionBridge:
    svc = MagicMock(spec=MalwareScanService)
    svc.scan_bytes = AsyncMock(return_value=scan_result or _clean_scan())
    return ConnectorIngestionBridge(malware_scan_service=svc, duplicate_action="warn")


async def _ingest(
    db_session: AsyncSession,
    ctx: BridgeContext,
    bridge: ConnectorIngestionBridge,
    *,
    content: bytes = _PDF_BYTES,
    filename: str = "report.pdf",
    mime_type: str = "application/pdf",
) -> IngestionResult:
    with patch(
        "app.domains.connectors.services.ingestion_bridge._upload_to_storage",
        new=AsyncMock(),
    ):
        return await bridge.ingest_item(
            db_session,
            external_item_id=ctx.external_item.id,
            organization_id=ctx.org_id,
            collection_id=None,
            sync_run_id=None,
            uploader_user_id=ctx.user_id,
            content=content,
            filename=filename,
            mime_type=mime_type,
            source_url=ctx.external_item.source_url,
            title=ctx.external_item.title,
            metadata={},
            sync_version=1,
        )


# ---------------------------------------------------------------------------
# Status / enum tests (pure unit)
# ---------------------------------------------------------------------------


def test_document_status_enum_has_new_connector_values() -> None:
    assert DocumentStatus.pending_scan == "pending_scan"
    assert DocumentStatus.infected == "infected"
    assert DocumentStatus.extraction_failed == "extraction_failed"
    assert DocumentStatus.ocr_applied == "ocr_applied"
    assert DocumentStatus.skipped == "skipped"
    assert DocumentStatus.unsupported == "unsupported"


def test_document_ingestion_source_enum_values() -> None:
    assert DocumentIngestionSource.upload == "upload"
    assert DocumentIngestionSource.connector == "connector"


# ---------------------------------------------------------------------------
# Filename / storage-key helpers (pure unit)
# ---------------------------------------------------------------------------


def test_safe_filename_strips_path_separators() -> None:
    assert "/" not in _safe_filename("../../etc/passwd.pdf", "pdf")
    assert "\\" not in _safe_filename("C:\\Windows\\system.txt", "txt")


def test_safe_filename_appends_extension_when_unknown_suffix() -> None:
    result = _safe_filename("attachment", "pdf")
    assert result.endswith(".pdf")


def test_safe_filename_preserves_known_extension() -> None:
    result = _safe_filename("report.pdf", "pdf")
    assert result == "report.pdf"


def test_safe_filename_replaces_null_bytes() -> None:
    result = _safe_filename("file\x00name.txt", "txt")
    assert "\x00" not in result


def test_build_storage_key_format() -> None:
    org_id = uuid4()
    key = _build_storage_key(org_id, "pdf")
    assert key.startswith(f"connectors/{org_id}/")
    assert key.endswith(".pdf")


# ---------------------------------------------------------------------------
# Validation: unsupported MIME / magic bytes / encrypted PDF (pure unit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_unsupported_mime_returns_unsupported(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(
        db_session, ctx, _bridge(), content=b"<html/>", mime_type="text/html", filename="page.html"
    )
    assert result.status == DocumentStatus.unsupported
    assert result.document_id is None


@pytest.mark.asyncio
async def test_ingest_empty_content_returns_unsupported(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(db_session, ctx, _bridge(), content=b"")
    assert result.status == DocumentStatus.unsupported


@pytest.mark.asyncio
async def test_ingest_pdf_with_bad_magic_bytes_returns_unsupported(
    db_session: AsyncSession,
) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(
        db_session,
        ctx,
        _bridge(),
        content=b"NOT_A_PDF",
        mime_type="application/pdf",
        filename="fake.pdf",
    )
    assert result.status == DocumentStatus.unsupported
    assert "magic bytes" in (result.error or "")


@pytest.mark.asyncio
async def test_ingest_encrypted_pdf_returns_unsupported(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(
        db_session,
        ctx,
        _bridge(),
        content=_ENCRYPTED_PDF,
        mime_type="application/pdf",
        filename="locked.pdf",
    )
    assert result.status == DocumentStatus.unsupported
    assert "encrypted" in (result.error or "")


# ---------------------------------------------------------------------------
# Clean file ingestion: success paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_clean_pdf_creates_document_and_source_document(
    db_session: AsyncSession,
) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(db_session, ctx, _bridge(), content=_PDF_BYTES)

    assert result.status == DocumentStatus.pending_scan
    assert result.document_id is not None
    assert result.source_document_id is not None
    assert result.checksum == hashlib.sha256(_PDF_BYTES).hexdigest()
    assert not result.is_duplicate

    doc = await db_session.get(Document, result.document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.pending_scan
    assert doc.ingestion_source == DocumentIngestionSource.connector
    assert doc.connector_external_item_id == ctx.external_item.id
    assert doc.checksum == result.checksum


@pytest.mark.asyncio
async def test_ingest_clean_pdf_creates_source_reference(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(db_session, ctx, _bridge(), content=_PDF_BYTES)

    refs = list(
        (
            await db_session.execute(
                select(SourceReference).where(
                    SourceReference.source_document_id == result.source_document_id
                )
            )
        ).scalars()
    )
    assert len(refs) == 1
    ref = refs[0]
    assert ref.reference_type == "connector_file"
    assert ref.source_url == ctx.external_item.source_url
    assert ref.chunk_id is None  # document-level reference; chunk refs added post-indexing


@pytest.mark.asyncio
async def test_ingest_clean_txt_creates_document(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(
        db_session,
        ctx,
        _bridge(),
        content=_TXT_BYTES,
        mime_type="text/plain",
        filename="notes.txt",
    )
    assert result.status == DocumentStatus.pending_scan
    assert result.document_id is not None

    doc = await db_session.get(Document, result.document_id)
    assert doc is not None
    assert doc.file_type == "txt"


@pytest.mark.asyncio
async def test_ingest_clean_docx_creates_document(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(
        db_session,
        ctx,
        _bridge(),
        content=_DOCX_BYTES,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="report.docx",
    )
    assert result.status == DocumentStatus.pending_scan
    doc = await db_session.get(Document, result.document_id)
    assert doc is not None
    assert doc.file_type == "docx"


# ---------------------------------------------------------------------------
# Malware scan: infected file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_infected_file_creates_document_with_infected_status(
    db_session: AsyncSession,
) -> None:
    ctx = await _make_bridge_context(db_session)
    bridge = _bridge(scan_result=_infected_scan())
    result = await _ingest(db_session, ctx, bridge, content=_INFECTED_PDF)

    assert result.status == DocumentStatus.infected
    assert result.document_id is not None
    assert result.source_document_id is None  # no SourceDocument for infected files

    doc = await db_session.get(Document, result.document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.infected
    assert doc.security_scan_result is not None
    assert doc.security_scan_result["status"] == "infected"
    assert doc.security_scan_result["signature"] == "EICAR.TEST"


# ---------------------------------------------------------------------------
# DLP scan: blocked file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_dlp_blocked_txt_creates_blocked_document(db_session: AsyncSession) -> None:
    # Fabricate a TXT file with many SSN-like patterns to trigger DLP.
    ssn_content = ("123-45-6789\n" * 20).encode()
    ctx = await _make_bridge_context(db_session)
    result = await _ingest(
        db_session,
        ctx,
        _bridge(),
        content=ssn_content,
        mime_type="text/plain",
        filename="ssns.txt",
    )

    assert result.status == DocumentStatus.blocked
    assert result.document_id is not None
    assert result.source_document_id is None

    doc = await db_session.get(Document, result.document_id)
    assert doc is not None
    assert doc.status == DocumentStatus.blocked
    assert doc.dlp_scan_result is not None
    assert doc.dlp_scan_result["total_findings"] > 0


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_duplicate_warn_links_existing_document(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    bridge = _bridge()

    # First ingestion creates the document.
    first = await _ingest(db_session, ctx, bridge, content=_TXT_BYTES)
    assert first.status == DocumentStatus.pending_scan

    # Second ingestion with same bytes → same checksum → duplicate.
    # For a second external item, create another ExternalItem.
    ext_item2 = ExternalItem(
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        provider_item_id=f"file-{uuid4().hex[:8]}",
        item_type=ExternalItemType.cloud_file.value,
        title="Duplicate File",
        source_url="https://drive.example.com/file/dup",
        content_hash="b" * 64,
        source_updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        sync_version=1,
        visibility=ExternalItemVisibility.org_wide.value,
        metadata_json={},
        permissions_json={},
    )
    db_session.add(ext_item2)
    await db_session.flush()

    with patch(
        "app.domains.connectors.services.ingestion_bridge._upload_to_storage",
        new=AsyncMock(),
    ):
        second = await bridge.ingest_item(
            db_session,
            external_item_id=ext_item2.id,
            organization_id=ctx.org_id,
            collection_id=None,
            sync_run_id=None,
            uploader_user_id=ctx.user_id,
            content=_TXT_BYTES,  # same bytes → duplicate checksum
            filename="notes.txt",
            mime_type="text/plain",
            source_url="https://drive.example.com/file/dup",
            title="Duplicate File",
            metadata={},
            sync_version=1,
        )

    assert second.is_duplicate is True
    assert second.status == DocumentStatus.skipped
    assert second.duplicate_of_document_id == first.document_id
    # SourceDocument should be created linking ext_item2 → existing document.
    assert second.source_document_id is not None


@pytest.mark.asyncio
async def test_ingest_duplicate_reject_skips_without_source_document(
    db_session: AsyncSession,
) -> None:
    ctx = await _make_bridge_context(db_session)

    # Create the first document normally.
    bridge_warn = _bridge()
    first = await _ingest(db_session, ctx, bridge_warn, content=_TXT_BYTES)
    assert first.status == DocumentStatus.pending_scan

    # Use a reject-policy bridge for the second ingestion.
    svc = MagicMock(spec=MalwareScanService)
    svc.scan_bytes = AsyncMock(return_value=_clean_scan())
    bridge_reject = ConnectorIngestionBridge(malware_scan_service=svc, duplicate_action="reject")

    ext_item2 = ExternalItem(
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        provider_item_id=f"file-{uuid4().hex[:8]}",
        item_type=ExternalItemType.attachment.value,
        title="Dup Attachment",
        source_url="https://confluence.example.com/attachments/1",
        content_hash="c" * 64,
        source_updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        sync_version=1,
        visibility=ExternalItemVisibility.org_wide.value,
        metadata_json={},
        permissions_json={},
        provider_parent_id="parent-issue-1",
    )
    db_session.add(ext_item2)
    await db_session.flush()

    with patch(
        "app.domains.connectors.services.ingestion_bridge._upload_to_storage",
        new=AsyncMock(),
    ):
        second = await bridge_reject.ingest_item(
            db_session,
            external_item_id=ext_item2.id,
            organization_id=ctx.org_id,
            collection_id=None,
            sync_run_id=None,
            uploader_user_id=ctx.user_id,
            content=_TXT_BYTES,
            filename="notes.txt",
            mime_type="text/plain",
            source_url="https://confluence.example.com/attachments/1",
            title="Dup Attachment",
            metadata={},
            sync_version=1,
        )

    assert second.is_duplicate is True
    assert second.status == DocumentStatus.skipped
    assert second.source_document_id is None  # reject → no SourceDocument created


# ---------------------------------------------------------------------------
# Storage failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_storage_failure_returns_failed_status(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    bridge = _bridge()

    with patch(
        "app.domains.connectors.services.ingestion_bridge._upload_to_storage",
        new=AsyncMock(side_effect=RuntimeError("MinIO unavailable")),
    ):
        result = await bridge.ingest_item(
            db_session,
            external_item_id=ctx.external_item.id,
            organization_id=ctx.org_id,
            collection_id=None,
            sync_run_id=None,
            uploader_user_id=ctx.user_id,
            content=_PDF_BYTES,
            filename="report.pdf",
            mime_type="application/pdf",
            source_url=ctx.external_item.source_url,
            title=ctx.external_item.title,
            metadata={},
            sync_version=1,
        )

    assert result.status == DocumentStatus.failed
    assert result.document_id is None
    assert "storage upload failed" in (result.error or "")


# ---------------------------------------------------------------------------
# CSV (Google Sheets export) treated as plain text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_csv_treated_as_txt(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    csv_content = b"name,age\nAlice,30\nBob,25\n"
    result = await _ingest(
        db_session,
        ctx,
        _bridge(),
        content=csv_content,
        mime_type="text/csv",
        filename="sheet.csv",
    )
    assert result.status == DocumentStatus.pending_scan
    doc = await db_session.get(Document, result.document_id)
    assert doc is not None
    assert doc.file_type == "txt"


# ---------------------------------------------------------------------------
# Idempotency: re-ingesting same item updates SourceDocument without duplicate docs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reingest_same_item_upserts_source_document(db_session: AsyncSession) -> None:
    ctx = await _make_bridge_context(db_session)
    bridge = _bridge()

    first = await _ingest(db_session, ctx, bridge, content=_TXT_BYTES)
    assert first.status == DocumentStatus.pending_scan

    # Ingest the same external_item_id again with same content → duplicate → skipped + upserted
    with patch(
        "app.domains.connectors.services.ingestion_bridge._upload_to_storage",
        new=AsyncMock(),
    ):
        second = await bridge.ingest_item(
            db_session,
            external_item_id=ctx.external_item.id,
            organization_id=ctx.org_id,
            collection_id=None,
            sync_run_id=None,
            uploader_user_id=ctx.user_id,
            content=_TXT_BYTES,
            filename="notes.txt",
            mime_type="text/plain",
            source_url=ctx.external_item.source_url,
            title=ctx.external_item.title,
            metadata={},
            sync_version=2,
        )

    # Same bytes → duplicate → skipped, but SourceDocument sync_version bumped.
    assert second.is_duplicate is True
    assert second.source_document_id is not None

    src_docs = list(
        (
            await db_session.execute(
                select(SourceDocument).where(
                    SourceDocument.external_item_id == ctx.external_item.id
                )
            )
        ).scalars()
    )
    assert len(src_docs) == 1  # no duplicate SourceDocument rows
    assert src_docs[0].sync_version == 2  # updated


# ---------------------------------------------------------------------------
# Google Drive download_file_content (unit, no HTTP)
# ---------------------------------------------------------------------------


def test_google_drive_download_returns_none_for_folder() -> None:
    from app.domains.connectors.providers.google_drive.adapter import GoogleDriveConnectorAdapter

    adapter = GoogleDriveConnectorAdapter()
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        adapter.download_file_content(
            provider_item_id="folder-123",
            mime_type="application/vnd.google-apps.folder",
            decrypted_credential={"access_token": "tok"},
        )
    )
    assert result is None


def test_google_drive_download_returns_none_for_unsupported_shortcut() -> None:
    from app.domains.connectors.providers.google_drive.adapter import GoogleDriveConnectorAdapter

    adapter = GoogleDriveConnectorAdapter()
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        adapter.download_file_content(
            provider_item_id="shortcut-abc",
            mime_type="application/vnd.google-apps.shortcut",
            decrypted_credential={"access_token": "tok"},
        )
    )
    assert result is None


def test_google_drive_download_returns_none_for_none_mime() -> None:
    from app.domains.connectors.providers.google_drive.adapter import GoogleDriveConnectorAdapter

    adapter = GoogleDriveConnectorAdapter()
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        adapter.download_file_content(
            provider_item_id="unknown-item",
            mime_type=None,
            decrypted_credential={"access_token": "tok"},
        )
    )
    assert result is None
