"""Connector file ingestion bridge: routes connector files through the document lifecycle.

Every file fetched from a connector (Confluence attachment, Google Drive file, or any
future provider) enters Rudix through this bridge before touching the document pipeline.
The bridge enforces the same security controls as a manual upload:

  1. MIME / filename validation
  2. SHA-256 checksum + duplicate detection (new items) / existing-item update (re-syncs)
  3. ClamAV malware scan  →  status: infected
  4. Basic text extraction for DLP scan  →  status: blocked
  5. Object-storage upload (MinIO/S3)
  6. Document + SourceDocument record creation (or in-place update on re-sync)
  7. SourceReference records (document-level, chunk_id=None; chunk-level refs added later)

When a connector item is re-synced with changed content the bridge finds the existing
SourceDocument by external_item_id, updates the linked Document in-place (new storage key,
reset to pending_scan), and re-queues it for chunking/embedding — no duplicate Document is
created.

The bridge does NOT run chunking / embedding inline; instead it creates the Document in
``pending_scan`` → ``processing`` status and expects the existing document processing
pipeline to pick it up via the normal Celery task.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.documents.services.duplicate_detection import (
    DuplicateAction,
    check_for_duplicate,
)
from app.domains.documents.services.malware_scan import MalwareScanService
from app.models.connector_source import SourceDocument, SourceReference
from app.models.document import Document
from app.models.enums import DocumentIngestionSource, DocumentStatus

if TYPE_CHECKING:
    pass

_logger = get_logger("connectors.ingestion_bridge")

# MIME types the bridge will accept from connector providers.
# Superset of the manual-upload allowlist: we additionally permit CSV (plain-text) and
# JSON (Google Apps Script exports) because providers convert native formats to these.
_CONNECTOR_ALLOWED_MIME: dict[str, str] = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "txt",  # treated as plain text for extraction
    "application/json": "txt",  # e.g. Google Apps Script exports
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

# Magic bytes check: (offset, expected_prefix) per extension.
_MAGIC_BYTES: dict[str, tuple[int, bytes]] = {
    "pdf": (0, b"%PDF"),
    "docx": (0, b"PK\x03\x04"),
}

_PDF_ENCRYPT_MARKER = b"/Encrypt"
_PDF_HEADER_SCAN_BYTES = 8192
_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB hard cap for connector files


@dataclass
class IngestionResult:
    """Outcome of a single connector file ingestion attempt."""

    document_id: UUID | None
    source_document_id: UUID | None
    status: str
    checksum: str | None
    is_duplicate: bool
    duplicate_of_document_id: UUID | None
    error: str | None


class ConnectorIngestionBridge:
    """Routes connector file bytes through the full upload security + document lifecycle.

    Designed to be injected into ConnectorSyncEngine so that the sync task can call it
    after successfully upserting a file-type ExternalItem.
    """

    def __init__(
        self,
        *,
        malware_scan_service: MalwareScanService | None = None,
        duplicate_action: DuplicateAction = "warn",
    ) -> None:
        self._malware_scan = malware_scan_service or MalwareScanService()
        self._duplicate_action = duplicate_action

    async def ingest_item(
        self,
        session: AsyncSession,
        *,
        external_item_id: UUID,
        organization_id: UUID,
        collection_id: UUID | None,
        sync_run_id: UUID | None,
        uploader_user_id: UUID,
        content: bytes,
        filename: str,
        mime_type: str | None,
        source_url: str,
        title: str,
        metadata: dict,
        sync_version: int,
    ) -> IngestionResult:
        """Ingest one connector file through the full security + document pipeline.

        Parameters
        ----------
        session:
            Active async SQLAlchemy session (caller owns the transaction).
        external_item_id:
            UUID of the already-persisted ExternalItem row.
        organization_id:
            Owning organisation.
        collection_id:
            Optional collection to tag the SourceDocument with.
        sync_run_id:
            The sync run that triggered this ingestion (for lineage).
        uploader_user_id:
            User attributed as the uploader — typically the connection owner.
        content:
            Raw file bytes downloaded from the provider.
        filename:
            Provider-supplied filename (used for extension detection).
        mime_type:
            MIME type reported by the provider (may be a Google-native type that was
            already exported to a target MIME before calling this method).
        source_url:
            Canonical HTTP(S) URL back to the item in the provider UI.
        title:
            Human-readable title for SourceReference records.
        metadata:
            Provider-specific metadata dict to store on SourceReference.
        sync_version:
            Current sync run version (timestamp-based integer).
        """
        # ------------------------------------------------------------------
        # 0. Re-sync update path: if this ExternalItem was already ingested,
        #    update the existing Document in-place rather than creating a new one.
        # ------------------------------------------------------------------
        existing_src = await self._find_existing_source_document(session, external_item_id)
        if existing_src is not None:
            return await self._reingest_existing_item(
                session,
                existing_src=existing_src,
                external_item_id=external_item_id,
                organization_id=organization_id,
                collection_id=collection_id,
                sync_run_id=sync_run_id,
                uploader_user_id=uploader_user_id,
                content=content,
                filename=filename,
                mime_type=mime_type,
                source_url=source_url,
                title=title,
                metadata=metadata,
                sync_version=sync_version,
            )

        # ------------------------------------------------------------------
        # 1. MIME / filename / size validation
        # ------------------------------------------------------------------
        resolved_mime = (mime_type or "").strip().lower().split(";")[0].strip()
        extension = _CONNECTOR_ALLOWED_MIME.get(resolved_mime)
        if extension is None:
            # Fall back to extension from filename
            suffix = Path(filename).suffix.lower().lstrip(".")
            if suffix in {"pdf", "txt", "docx"}:
                extension = suffix
            else:
                _logger.info(
                    "connector.ingestion.unsupported",
                    external_item_id=str(external_item_id),
                    mime_type=resolved_mime,
                )
                return IngestionResult(
                    document_id=None,
                    source_document_id=None,
                    status=DocumentStatus.unsupported,
                    checksum=None,
                    is_duplicate=False,
                    duplicate_of_document_id=None,
                    error=f"unsupported mime type: {resolved_mime}",
                )

        if not content:
            return IngestionResult(
                document_id=None,
                source_document_id=None,
                status=DocumentStatus.unsupported,
                checksum=None,
                is_duplicate=False,
                duplicate_of_document_id=None,
                error="empty file content",
            )

        if len(content) > _MAX_FILE_SIZE_BYTES:
            return IngestionResult(
                document_id=None,
                source_document_id=None,
                status=DocumentStatus.unsupported,
                checksum=None,
                is_duplicate=False,
                duplicate_of_document_id=None,
                error=f"file size {len(content)} exceeds {_MAX_FILE_SIZE_BYTES} byte limit",
            )

        # Magic bytes guard (same as upload_validation for PDF / DOCX).
        if extension in _MAGIC_BYTES:
            offset, expected = _MAGIC_BYTES[extension]
            if (
                len(content) < offset + len(expected)
                or content[offset : offset + len(expected)] != expected
            ):
                return IngestionResult(
                    document_id=None,
                    source_document_id=None,
                    status=DocumentStatus.unsupported,
                    checksum=None,
                    is_duplicate=False,
                    duplicate_of_document_id=None,
                    error=f"magic bytes mismatch for extension .{extension}",
                )

        # Reject encrypted PDFs.
        if extension == "pdf":
            header = content[:_PDF_HEADER_SCAN_BYTES]
            if _PDF_ENCRYPT_MARKER in header or _PDF_ENCRYPT_MARKER.lower() in header.lower():
                return IngestionResult(
                    document_id=None,
                    source_document_id=None,
                    status=DocumentStatus.unsupported,
                    checksum=None,
                    is_duplicate=False,
                    duplicate_of_document_id=None,
                    error="encrypted/password-protected PDF not supported",
                )

        # ------------------------------------------------------------------
        # 2. Checksum + duplicate detection
        # ------------------------------------------------------------------
        checksum = hashlib.sha256(content).hexdigest()
        dup_result = await check_for_duplicate(
            session,
            checksum=checksum,
            organization_id=organization_id,
            action=self._duplicate_action,
        )

        if dup_result.is_duplicate and self._duplicate_action == "reject":
            _logger.info(
                "connector.ingestion.duplicate_rejected",
                external_item_id=str(external_item_id),
                existing_document_id=str(dup_result.existing_document_id),
            )
            return IngestionResult(
                document_id=dup_result.existing_document_id,
                source_document_id=None,
                status=DocumentStatus.skipped,
                checksum=checksum,
                is_duplicate=True,
                duplicate_of_document_id=dup_result.existing_document_id,
                error=None,
            )

        if dup_result.is_duplicate:
            # warn / allow: link the existing document to this connector item instead of
            # creating a new Document, so the connector item gets citation coverage.
            existing_doc_id = dup_result.existing_document_id
            src_doc = await self._upsert_source_document(
                session,
                external_item_id=external_item_id,
                document_id=existing_doc_id,  # type: ignore[arg-type]
                organization_id=organization_id,
                collection_id=collection_id,
                sync_run_id=sync_run_id,
                content_hash=checksum,
                sync_version=sync_version,
            )
            await self._upsert_source_reference(
                session,
                source_document_id=src_doc.id,
                external_item_id=external_item_id,
                document_id=existing_doc_id,  # type: ignore[arg-type]
                organization_id=organization_id,
                source_url=source_url,
                title=title,
                metadata=metadata,
            )
            _logger.info(
                "connector.ingestion.duplicate_linked",
                external_item_id=str(external_item_id),
                existing_document_id=str(existing_doc_id),
            )
            return IngestionResult(
                document_id=existing_doc_id,
                source_document_id=src_doc.id,
                status=DocumentStatus.skipped,
                checksum=checksum,
                is_duplicate=True,
                duplicate_of_document_id=existing_doc_id,
                error=None,
            )

        # ------------------------------------------------------------------
        # 3. Malware scan (ClamAV)
        # ------------------------------------------------------------------
        scan_result = await self._malware_scan.scan_bytes(content=content)
        scan_dict = {
            "scanner": scan_result.scanner,
            "status": scan_result.status,
            "signature": scan_result.signature,
            "duration_ms": scan_result.duration_ms,
            "error_type": scan_result.error_type,
        }

        if scan_result.status == "infected":
            doc = await self._create_document(
                session,
                organization_id=organization_id,
                uploader_user_id=uploader_user_id,
                filename=_safe_filename(filename, extension),
                extension=extension,
                checksum=checksum,
                size=len(content),
                status=DocumentStatus.infected,
                security_scan_result=scan_dict,
                external_item_id=external_item_id,
            )
            _logger.warning(
                "connector.ingestion.infected",
                external_item_id=str(external_item_id),
                signature=scan_result.signature,
                document_id=str(doc.id),
            )
            return IngestionResult(
                document_id=doc.id,
                source_document_id=None,
                status=DocumentStatus.infected,
                checksum=checksum,
                is_duplicate=False,
                duplicate_of_document_id=None,
                error=f"malware detected: {scan_result.signature}",
            )

        # ------------------------------------------------------------------
        # 4. DLP scan (on raw bytes interpreted as text where possible)
        # ------------------------------------------------------------------
        dlp_text = _extract_text_for_dlp(content, extension)
        dlp_result = _run_dlp(dlp_text)
        dlp_dict = dlp_result.to_dict()

        if dlp_result.action in {"quarantine", "reject"}:
            doc = await self._create_document(
                session,
                organization_id=organization_id,
                uploader_user_id=uploader_user_id,
                filename=_safe_filename(filename, extension),
                extension=extension,
                checksum=checksum,
                size=len(content),
                status=DocumentStatus.blocked,
                security_scan_result=scan_dict,
                dlp_scan_result=dlp_dict,
                external_item_id=external_item_id,
            )
            _logger.warning(
                "connector.ingestion.dlp_blocked",
                external_item_id=str(external_item_id),
                total_findings=dlp_result.total_findings,
                document_id=str(doc.id),
            )
            return IngestionResult(
                document_id=doc.id,
                source_document_id=None,
                status=DocumentStatus.blocked,
                checksum=checksum,
                is_duplicate=False,
                duplicate_of_document_id=None,
                error=f"DLP policy blocked: {dlp_result.total_findings} findings",
            )

        # ------------------------------------------------------------------
        # 5. Upload file to object storage
        # ------------------------------------------------------------------
        storage_key = _build_storage_key(organization_id, extension)
        storage_bucket = "documents"
        try:
            await _upload_to_storage(storage_bucket, storage_key, content, resolved_mime)
        except Exception as exc:
            _logger.error(
                "connector.ingestion.storage_upload_failed",
                external_item_id=str(external_item_id),
                error=str(exc),
            )
            return IngestionResult(
                document_id=None,
                source_document_id=None,
                status=DocumentStatus.failed,
                checksum=checksum,
                is_duplicate=False,
                duplicate_of_document_id=None,
                error=f"storage upload failed: {exc}",
            )

        # ------------------------------------------------------------------
        # 6. Create Document record (status=pending_scan, pipeline picks it up)
        # ------------------------------------------------------------------
        doc = await self._create_document(
            session,
            organization_id=organization_id,
            uploader_user_id=uploader_user_id,
            filename=_safe_filename(filename, extension),
            extension=extension,
            checksum=checksum,
            size=len(content),
            status=DocumentStatus.pending_scan,
            security_scan_result=scan_dict,
            dlp_scan_result=dlp_dict,
            external_item_id=external_item_id,
            storage_bucket=storage_bucket,
            storage_key=storage_key,
        )

        # ------------------------------------------------------------------
        # 7. Create SourceDocument + SourceReference
        # ------------------------------------------------------------------
        src_doc = await self._upsert_source_document(
            session,
            external_item_id=external_item_id,
            document_id=doc.id,
            organization_id=organization_id,
            collection_id=collection_id,
            sync_run_id=sync_run_id,
            content_hash=checksum,
            sync_version=sync_version,
        )
        await self._upsert_source_reference(
            session,
            source_document_id=src_doc.id,
            external_item_id=external_item_id,
            document_id=doc.id,
            organization_id=organization_id,
            source_url=source_url,
            title=title,
            metadata=metadata,
        )

        _logger.info(
            "connector.ingestion.queued",
            external_item_id=str(external_item_id),
            document_id=str(doc.id),
            extension=extension,
            size=len(content),
        )
        return IngestionResult(
            document_id=doc.id,
            source_document_id=src_doc.id,
            status=DocumentStatus.pending_scan,
            checksum=checksum,
            is_duplicate=False,
            duplicate_of_document_id=None,
            error=None,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _create_document(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        uploader_user_id: UUID,
        filename: str,
        extension: str,
        checksum: str,
        size: int,
        status: DocumentStatus,
        security_scan_result: dict | None = None,
        dlp_scan_result: dict | None = None,
        external_item_id: UUID | None = None,
        storage_bucket: str = "documents",
        storage_key: str = "",
    ) -> Document:
        doc = Document(
            organization_id=organization_id,
            uploaded_by_user_id=uploader_user_id,
            filename=filename,
            file_type=extension,
            storage_bucket=storage_bucket,
            storage_object_key=storage_key,
            status=status.value,
            checksum=checksum,
            security_scan_result=security_scan_result,
            dlp_scan_result=dlp_scan_result,
            ingestion_source=DocumentIngestionSource.connector.value,
            connector_external_item_id=external_item_id,
        )
        session.add(doc)
        await session.flush()
        await session.refresh(doc)
        return doc

    async def _upsert_source_document(
        self,
        session: AsyncSession,
        *,
        external_item_id: UUID,
        document_id: UUID,
        organization_id: UUID,
        collection_id: UUID | None,
        sync_run_id: UUID | None,
        content_hash: str,
        sync_version: int,
    ) -> SourceDocument:
        existing = await session.execute(
            select(SourceDocument).where(
                SourceDocument.external_item_id == external_item_id,
                SourceDocument.document_id == document_id,
            )
        )
        src_doc = existing.scalar_one_or_none()
        if src_doc is not None:
            src_doc.content_hash = content_hash
            src_doc.sync_version = sync_version
            await session.flush()
            return src_doc

        src_doc = SourceDocument(
            organization_id=organization_id,
            external_item_id=external_item_id,
            document_id=document_id,
            collection_id=collection_id,
            sync_run_id=sync_run_id,
            content_hash=content_hash,
            sync_version=sync_version,
            status="active",
        )
        session.add(src_doc)
        await session.flush()
        await session.refresh(src_doc)
        return src_doc

    async def _upsert_source_reference(
        self,
        session: AsyncSession,
        *,
        source_document_id: UUID,
        external_item_id: UUID,
        document_id: UUID,
        organization_id: UUID,
        source_url: str,
        title: str,
        metadata: dict,
        chunk_id: UUID | None = None,
    ) -> SourceReference:
        existing = await session.execute(
            select(SourceReference).where(
                SourceReference.source_document_id == source_document_id,
                SourceReference.reference_type == "connector_file",
                SourceReference.chunk_id.is_(None),
            )
        )
        ref = existing.scalar_one_or_none()
        if ref is not None:
            ref.source_url = source_url
            ref.title = title
            ref.metadata_json = metadata
            await session.flush()
            return ref

        ref = SourceReference(
            organization_id=organization_id,
            source_document_id=source_document_id,
            external_item_id=external_item_id,
            document_id=document_id,
            chunk_id=chunk_id,
            reference_type="connector_file",
            source_url=source_url,
            title=title,
            locator_json={},
            metadata_json=metadata,
        )
        session.add(ref)
        await session.flush()
        await session.refresh(ref)
        return ref

    async def _find_existing_source_document(
        self,
        session: AsyncSession,
        external_item_id: UUID,
    ) -> SourceDocument | None:
        result = await session.execute(
            select(SourceDocument)
            .where(SourceDocument.external_item_id == external_item_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _reingest_existing_item(
        self,
        session: AsyncSession,
        *,
        existing_src: SourceDocument,
        external_item_id: UUID,
        organization_id: UUID,
        collection_id: UUID | None,
        sync_run_id: UUID | None,
        uploader_user_id: UUID,
        content: bytes,
        filename: str,
        mime_type: str | None,
        source_url: str,
        title: str,
        metadata: dict,
        sync_version: int,
    ) -> IngestionResult:
        """Update an already-indexed connector item with new content.

        Re-runs security checks, uploads new bytes under a fresh storage key,
        updates the existing Document in-place (so no duplicate is created),
        and returns pending_scan so the caller re-queues it for processing.
        """
        resolved_mime = (mime_type or "").strip().lower().split(";")[0].strip()
        extension = _CONNECTOR_ALLOWED_MIME.get(resolved_mime)
        if extension is None:
            suffix = Path(filename).suffix.lower().lstrip(".")
            if suffix in {"pdf", "txt", "docx"}:
                extension = suffix
            else:
                _logger.info(
                    "connector.ingestion.update_unsupported",
                    external_item_id=str(external_item_id),
                    mime_type=resolved_mime,
                )
                return IngestionResult(
                    document_id=existing_src.document_id,
                    source_document_id=existing_src.id,
                    status=DocumentStatus.unsupported,
                    checksum=None,
                    is_duplicate=False,
                    duplicate_of_document_id=None,
                    error=f"unsupported mime type on update: {resolved_mime}",
                )

        if not content or len(content) > _MAX_FILE_SIZE_BYTES:
            return IngestionResult(
                document_id=existing_src.document_id,
                source_document_id=existing_src.id,
                status=DocumentStatus.unsupported,
                checksum=None,
                is_duplicate=False,
                duplicate_of_document_id=None,
                error="empty or oversized file on update",
            )

        if extension in _MAGIC_BYTES:
            offset, expected = _MAGIC_BYTES[extension]
            if (
                len(content) < offset + len(expected)
                or content[offset : offset + len(expected)] != expected
            ):
                return IngestionResult(
                    document_id=existing_src.document_id,
                    source_document_id=existing_src.id,
                    status=DocumentStatus.unsupported,
                    checksum=None,
                    is_duplicate=False,
                    duplicate_of_document_id=None,
                    error=f"magic bytes mismatch on update for extension .{extension}",
                )

        if extension == "pdf":
            header = content[:_PDF_HEADER_SCAN_BYTES]
            if _PDF_ENCRYPT_MARKER in header or _PDF_ENCRYPT_MARKER.lower() in header.lower():
                return IngestionResult(
                    document_id=existing_src.document_id,
                    source_document_id=existing_src.id,
                    status=DocumentStatus.unsupported,
                    checksum=None,
                    is_duplicate=False,
                    duplicate_of_document_id=None,
                    error="encrypted/password-protected PDF not supported on update",
                )

        checksum = hashlib.sha256(content).hexdigest()

        # Short-circuit: if the file bytes haven't changed, only bump lineage metadata.
        # The sync engine uses ExternalItem.content_hash (which covers title/version/etc.)
        # for change detection, so we can reach here even when the actual bytes are identical.
        if existing_src.content_hash == checksum:
            existing_src.sync_version = sync_version
            existing_src.sync_run_id = sync_run_id
            if collection_id is not None:
                existing_src.collection_id = collection_id
            await session.flush()
            await self._upsert_source_reference(
                session,
                source_document_id=existing_src.id,
                external_item_id=external_item_id,
                document_id=existing_src.document_id,
                organization_id=organization_id,
                source_url=source_url,
                title=title,
                metadata=metadata,
            )
            return IngestionResult(
                document_id=existing_src.document_id,
                source_document_id=existing_src.id,
                status=DocumentStatus.skipped,
                checksum=checksum,
                is_duplicate=True,
                duplicate_of_document_id=existing_src.document_id,
                error=None,
            )

        scan_result = await self._malware_scan.scan_bytes(content=content)
        scan_dict = {
            "scanner": scan_result.scanner,
            "status": scan_result.status,
            "signature": scan_result.signature,
            "duration_ms": scan_result.duration_ms,
            "error_type": scan_result.error_type,
        }

        dlp_text = _extract_text_for_dlp(content, extension)
        dlp_result = _run_dlp(dlp_text)
        dlp_dict = dlp_result.to_dict()

        # Determine final Document status before touching storage.
        if scan_result.status == "infected":
            new_doc_status = DocumentStatus.infected
        elif dlp_result.action in {"quarantine", "reject"}:
            new_doc_status = DocumentStatus.blocked
        else:
            new_doc_status = DocumentStatus.pending_scan

        # Upload new content only when the document is clean.
        storage_key: str | None = None
        if new_doc_status == DocumentStatus.pending_scan:
            storage_key = _build_storage_key(organization_id, extension)
            try:
                await _upload_to_storage("documents", storage_key, content, resolved_mime)
            except Exception as exc:
                _logger.error(
                    "connector.ingestion.update_storage_failed",
                    external_item_id=str(external_item_id),
                    error=str(exc),
                )
                return IngestionResult(
                    document_id=existing_src.document_id,
                    source_document_id=existing_src.id,
                    status=DocumentStatus.failed,
                    checksum=checksum,
                    is_duplicate=False,
                    duplicate_of_document_id=None,
                    error=f"storage upload failed on update: {exc}",
                )

        # Update the existing Document in-place.
        doc_result = await session.execute(
            select(Document).where(Document.id == existing_src.document_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc is None:
            # Linked Document was hard-deleted; create a fresh one.
            doc = await self._create_document(
                session,
                organization_id=organization_id,
                uploader_user_id=uploader_user_id,
                filename=_safe_filename(filename, extension),
                extension=extension,
                checksum=checksum,
                size=len(content),
                status=new_doc_status,
                security_scan_result=scan_dict,
                dlp_scan_result=dlp_dict,
                external_item_id=external_item_id,
                storage_bucket="documents" if storage_key else "",
                storage_key=storage_key or "",
            )
            existing_src.document_id = doc.id
        else:
            doc.checksum = checksum
            doc.file_type = extension
            doc.status = new_doc_status.value
            doc.security_scan_result = scan_dict
            doc.dlp_scan_result = dlp_dict
            if storage_key:
                doc.storage_bucket = "documents"
                doc.storage_object_key = storage_key
            await session.flush()
            await session.refresh(doc)

        # Update SourceDocument lineage.
        existing_src.content_hash = checksum
        existing_src.sync_version = sync_version
        existing_src.sync_run_id = sync_run_id
        if collection_id is not None:
            existing_src.collection_id = collection_id
        await session.flush()

        # Update SourceReference.
        await self._upsert_source_reference(
            session,
            source_document_id=existing_src.id,
            external_item_id=external_item_id,
            document_id=doc.id,
            organization_id=organization_id,
            source_url=source_url,
            title=title,
            metadata=metadata,
        )

        _logger.info(
            "connector.ingestion.updated",
            external_item_id=str(external_item_id),
            document_id=str(doc.id),
            status=new_doc_status.value,
            extension=extension,
            size=len(content),
        )
        return IngestionResult(
            document_id=doc.id,
            source_document_id=existing_src.id,
            status=new_doc_status,
            checksum=checksum,
            is_duplicate=False,
            duplicate_of_document_id=None,
            error=None,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _safe_filename(filename: str, extension: str) -> str:
    """Sanitize provider filename: strip path separators and null bytes."""
    cleaned = filename.strip().replace("/", "_").replace("\\", "_").replace("\x00", "")
    if not cleaned:
        return f"connector_file.{extension}"
    suffix = Path(cleaned).suffix.lower().lstrip(".")
    if suffix not in {"pdf", "txt", "docx", "csv", "json"}:
        cleaned = f"{cleaned}.{extension}"
    return cleaned[:512]


def _build_storage_key(organization_id: UUID, extension: str) -> str:
    return f"connectors/{organization_id}/{uuid.uuid4()}.{extension}"


def _extract_text_for_dlp(content: bytes, extension: str) -> str:
    """Return a best-effort plain-text representation for DLP scanning.

    We limit to 1 MB of text to avoid spending excessive time on large files.
    PDF binary content is excluded because the DLP regex patterns are designed for
    plain text; the PDF extraction pipeline will do a proper DLP pass later.
    """
    if extension in {"txt", "csv", "json"}:
        try:
            return content[:1_048_576].decode("utf-8", errors="replace")
        except Exception:
            return ""
    return ""


def _run_dlp(text: str) -> DlpScanResult:
    from app.domains.documents.services.dlp_service import scan_text_for_dlp

    return scan_text_for_dlp(text, enabled=bool(text), action="quarantine")


async def _upload_to_storage(bucket: str, key: str, content: bytes, mime_type: str) -> None:
    """Upload file bytes to object storage (MinIO/S3).

    Delegates to the same MinIO client used by the document upload API.
    Raises on any storage error so the caller can handle the failure.
    """
    from app.clients import minio_client as minio_module

    client = minio_module.get_minio_client()
    if client is None:
        raise RuntimeError("MinIO client is not configured")
    import asyncio

    await asyncio.to_thread(
        lambda: client.put_object(
            Bucket=bucket,
            Key=key,
            Body=io.BytesIO(content),
            ContentLength=len(content),
            ContentType=mime_type,
        )
    )


# Imported here to keep the type annotation above valid when TYPE_CHECKING is False.
from app.domains.documents.services.dlp_service import DlpScanResult  # noqa: E402
