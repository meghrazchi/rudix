"""Aggregation service for the admin source health dashboard (F352).

Rolls up existing indexing/OCR/trust/review/connector-sync/metadata signals
already tracked on Document, Collection, and connector models into health
metrics, charts, and an actionable source table. No new persisted state is
introduced — every field read here already exists from prior features
(F212 chunking, F245 connector ingestion, F256 metadata taxonomy, F297/F298
trust & freshness, F299 OCR quality, F240 connector sync).

Follows the fetch-then-aggregate-in-Python style used by
`admin_trust_analytics.py` rather than building one giant SQL query, so the
aggregation logic can be unit tested without a database (see
`test_source_health_service.py`).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.schemas.source_health import (
    ConnectorFreshness,
    IndexingFailurePoint,
    OcrQualityCount,
    ReviewNeedsByOwner,
    SourceHealthChartsResponse,
    SourceHealthErrorDetailResponse,
    SourceHealthListResponse,
    SourceHealthRow,
    SourceHealthSummaryResponse,
    SourceStatusCount,
    StaleByCollection,
    TableWarningItem,
)
from app.models.collection import Collection, CollectionDocument
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceDocument
from app.models.connector_sync import ConnectorSyncRun
from app.models.document import Document, DocumentChunk
from app.models.enums import (
    ConnectorSyncRunStatus,
    DocumentIngestionSource,
    DocumentQualityState,
    DocumentReviewStatus,
    DocumentStatus,
    DocumentTrustStatus,
    OcrQualityStatus,
)
from app.models.metadata import DocumentMetadata, MetadataField
from app.models.pipeline import PipelineRun
from app.models.user import User

_INDEXED_STATUSES = frozenset({DocumentStatus.indexed})
_FAILED_STATUSES = frozenset({DocumentStatus.failed, DocumentStatus.extraction_failed})
_PENDING_STATUSES = frozenset(
    {DocumentStatus.uploaded, DocumentStatus.processing, DocumentStatus.pending_scan}
)
_NON_REINDEXABLE_STATUSES = frozenset(
    {
        DocumentStatus.delete_requested,
        DocumentStatus.deleting,
        DocumentStatus.deleted,
        DocumentStatus.retained_by_policy,
    }
)
_OCR_LOW_STATUSES = frozenset({OcrQualityStatus.low, OcrQualityStatus.failed})
_PIPELINE_INDEX_TYPES = ("document.process", "document.reindex")
_MAX_DOCUMENTS_SCANNED = 10_000
_MAX_COLLECTIONS_SCANNED = 2_000
_INDEXING_FAILURE_TREND_DAYS = 30
_STALE_BY_COLLECTION_LIMIT = 10
_REVIEW_NEEDS_BY_OWNER_LIMIT = 15
_ERROR_MESSAGE_TRUNCATE = 500


@dataclass
class SourceHealthFilters:
    source_type: str | None = None
    status: str | None = None
    collection_id: str | None = None
    owner_id: str | None = None
    freshness: str | None = None
    review_status: str | None = None
    ocr_quality: str | None = None
    graph_indexed: str | None = None
    missing_metadata: bool | None = None
    q: str | None = None


@dataclass
class _CollectionRollup:
    total: int = 0
    failed: int = 0
    pending: int = 0


def _freshness(
    *,
    trust_status: str | None,
    review_status: str | None,
    expiry_date: date | None,
    today: date,
) -> str:
    if expiry_date is not None and expiry_date < today:
        return "expired"
    if (
        trust_status == DocumentTrustStatus.expired.value
        or review_status == DocumentReviewStatus.expired.value
    ):
        return "expired"
    if (
        trust_status == DocumentTrustStatus.stale.value
        or review_status == DocumentReviewStatus.stale.value
    ):
        return "stale"
    return "fresh"


def _needs_review(*, review_status: str | None, review_due_date: date | None, today: date) -> bool:
    if review_status == DocumentReviewStatus.needs_review.value:
        return True
    return review_due_date is not None and review_due_date < today


def _truncate(text: str | None, limit: int = _ERROR_MESSAGE_TRUNCATE) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


class SourceHealthService:
    async def get_summary(
        self, session: AsyncSession, *, organization_id: UUID
    ) -> SourceHealthSummaryResponse:
        today = datetime.now(tz=UTC).date()
        documents = await self._fetch_documents(session, organization_id)
        collections = await self._fetch_collections(session, organization_id)
        missing_metadata_ids = await self._missing_metadata_document_ids(session, organization_id)
        table_warning_ids = await self._table_warning_document_ids(session, organization_id)

        indexed = failed_indexing = pending = 0
        ocr_required = ocr_low_confidence = 0
        stale = deprecated = expired = unreviewed = needs_review = 0

        for doc in documents:
            if doc.status in _INDEXED_STATUSES:
                indexed += 1
            if doc.status in _FAILED_STATUSES:
                failed_indexing += 1
            if doc.status in _PENDING_STATUSES:
                pending += 1
            if (
                doc.ocr_quality_status
                and doc.ocr_quality_status != OcrQualityStatus.not_required.value
            ):
                ocr_required += 1
            if doc.ocr_quality_status in _OCR_LOW_STATUSES:
                ocr_low_confidence += 1

            fresh = _freshness(
                trust_status=doc.trust_status,
                review_status=doc.review_status,
                expiry_date=doc.expiry_date,
                today=today,
            )
            if fresh == "stale":
                stale += 1
            elif fresh == "expired":
                expired += 1
            if doc.trust_status == DocumentTrustStatus.deprecated.value or (
                doc.quality_state == DocumentQualityState.deprecated.value
            ):
                deprecated += 1
            if doc.quality_state == DocumentQualityState.unreviewed.value:
                unreviewed += 1
            if _needs_review(
                review_status=doc.review_status, review_due_date=doc.review_due_date, today=today
            ):
                needs_review += 1

        for col in collections:
            fresh = _freshness(
                trust_status=None,
                review_status=col.review_status,
                expiry_date=col.expiry_date,
                today=today,
            )
            if fresh == "stale":
                stale += 1
            elif fresh == "expired":
                expired += 1
            if _needs_review(
                review_status=col.review_status, review_due_date=col.review_due_date, today=today
            ):
                needs_review += 1

        return SourceHealthSummaryResponse(
            total_sources=len(documents) + len(collections),
            indexed=indexed,
            failed_indexing=failed_indexing,
            pending=pending,
            ocr_required=ocr_required,
            ocr_low_confidence=ocr_low_confidence,
            table_extraction_warnings=len(table_warning_ids),
            missing_metadata=len(missing_metadata_ids),
            stale=stale,
            deprecated=deprecated,
            expired=expired,
            unreviewed=unreviewed,
            needs_review=needs_review,
            generated_at=datetime.now(tz=UTC),
        )

    async def get_charts(
        self, session: AsyncSession, *, organization_id: UUID
    ) -> SourceHealthChartsResponse:
        today = datetime.now(tz=UTC).date()

        status_distribution = await self._status_distribution(session, organization_id)
        indexing_failures = await self._indexing_failures(session, organization_id, today)
        stale_by_collection = await self._stale_by_collection(session, organization_id, today)
        ocr_quality_distribution = await self._ocr_quality_distribution(session, organization_id)
        review_needs_by_owner = await self._review_needs_by_owner(session, organization_id, today)
        connector_freshness = await self._connector_freshness(session, organization_id, today)

        return SourceHealthChartsResponse(
            status_distribution=status_distribution,
            indexing_failures=indexing_failures,
            stale_by_collection=stale_by_collection,
            ocr_quality_distribution=ocr_quality_distribution,
            review_needs_by_owner=review_needs_by_owner,
            connector_freshness=connector_freshness,
            generated_at=datetime.now(tz=UTC),
        )

    async def list_sources(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: SourceHealthFilters,
        page: int = 1,
        page_size: int = 25,
    ) -> SourceHealthListResponse:
        rows = await self._build_rows(session, organization_id, filters)
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        return SourceHealthListResponse(rows=page_rows, total=total, page=page, page_size=page_size)

    async def build_export_csv(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: SourceHealthFilters,
    ) -> str:
        rows = await self._build_rows(session, organization_id, filters)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "source_type",
                "source_name",
                "collection",
                "owner",
                "status",
                "last_indexed_at",
                "last_updated_at",
                "freshness",
                "ocr_quality",
                "review_status",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.source_type,
                    row.source_name,
                    row.collection_name or "",
                    row.owner_name or "",
                    row.status,
                    row.last_indexed_at.isoformat() if row.last_indexed_at else "",
                    row.last_updated_at.isoformat() if row.last_updated_at else "",
                    row.freshness,
                    row.ocr_quality or "",
                    row.review_status or "",
                ]
            )
        return buffer.getvalue()

    async def get_error_detail(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
    ) -> SourceHealthErrorDetailResponse | None:
        if source_type == "collection":
            collection = await session.get(Collection, source_id)
            if collection is None or collection.organization_id != organization_id:
                return None
            return SourceHealthErrorDetailResponse(
                source_type="collection",
                source_id=str(collection.id),
                source_name=collection.name,
                status="archived" if collection.is_archived else "active",
            )

        document = await session.get(Document, source_id)
        if document is None or document.organization_id != organization_id:
            return None

        extraction_warnings: list[str] = []
        snapshot = document.extraction_snapshot
        if isinstance(snapshot, dict):
            warnings = snapshot.get("warnings")
            if isinstance(warnings, list):
                extraction_warnings = [str(w) for w in warnings]

        table_warnings = await self._table_warnings_for_document(session, document.id)

        return SourceHealthErrorDetailResponse(
            source_type="connector"
            if document.ingestion_source == DocumentIngestionSource.connector.value
            else "file",
            source_id=str(document.id),
            source_name=document.filename,
            status=document.status,
            error_message=document.error_message,
            extraction_warnings=extraction_warnings,
            ocr_quality_status=document.ocr_quality_status,
            ocr_avg_confidence=document.ocr_avg_confidence,
            table_warnings=table_warnings,
        )

    # -- internal: raw fetches -------------------------------------------------

    async def _fetch_documents(
        self, session: AsyncSession, organization_id: UUID
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.organization_id == organization_id)
            .order_by(Document.filename)
            .limit(_MAX_DOCUMENTS_SCANNED)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def _fetch_collections(
        self, session: AsyncSession, organization_id: UUID
    ) -> list[Collection]:
        stmt = (
            select(Collection)
            .where(Collection.organization_id == organization_id)
            .order_by(Collection.name)
            .limit(_MAX_COLLECTIONS_SCANNED)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def _last_indexed_map(
        self, session: AsyncSession, organization_id: UUID
    ) -> dict[UUID, datetime]:
        stmt = (
            select(PipelineRun.document_id, func.max(PipelineRun.completed_at))
            .where(
                PipelineRun.organization_id == organization_id,
                PipelineRun.pipeline_type.in_(_PIPELINE_INDEX_TYPES),
                PipelineRun.status == "completed",
                PipelineRun.document_id.is_not(None),
            )
            .group_by(PipelineRun.document_id)
        )
        result = await session.execute(stmt)
        return {doc_id: completed_at for doc_id, completed_at in result.all() if completed_at}

    async def _collection_membership_map(
        self, session: AsyncSession, organization_id: UUID
    ) -> dict[UUID, tuple[UUID, str]]:
        stmt = (
            select(CollectionDocument.document_id, Collection.id, Collection.name)
            .join(Collection, Collection.id == CollectionDocument.collection_id)
            .where(Collection.organization_id == organization_id)
        )
        result = await session.execute(stmt)
        mapping: dict[UUID, tuple[UUID, str]] = {}
        for document_id, collection_id, collection_name in result.all():
            mapping.setdefault(document_id, (collection_id, collection_name))
        return mapping

    async def _connector_info_map(
        self, session: AsyncSession, organization_id: UUID
    ) -> dict[UUID, tuple[str, str | None]]:
        stmt = (
            select(
                SourceDocument.document_id,
                ConnectorConnection.display_name,
                ConnectorConnection.id,
            )
            .join(ExternalItem, ExternalItem.id == SourceDocument.external_item_id)
            .join(ConnectorConnection, ConnectorConnection.id == ExternalItem.connection_id)
            .where(SourceDocument.organization_id == organization_id)
        )
        result = await session.execute(stmt)
        mapping: dict[UUID, tuple[str, str | None]] = {}
        for document_id, connector_name, connection_id in result.all():
            mapping.setdefault(document_id, (connector_name, str(connection_id)))
        return mapping

    async def _missing_metadata_document_ids(
        self, session: AsyncSession, organization_id: UUID
    ) -> set[UUID]:
        stmt = (
            select(Document.id)
            .select_from(Document)
            .join(
                MetadataField,
                (MetadataField.organization_id == Document.organization_id)
                & (MetadataField.is_required.is_(True))
                & (MetadataField.is_active.is_(True)),
            )
            .outerjoin(
                DocumentMetadata,
                (DocumentMetadata.document_id == Document.id)
                & (DocumentMetadata.field_id == MetadataField.id),
            )
            .where(
                Document.organization_id == organization_id,
                DocumentMetadata.id.is_(None),
            )
            .distinct()
        )
        result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    async def _table_warning_document_ids(
        self, session: AsyncSession, organization_id: UUID
    ) -> set[UUID]:
        # Filtered in Python rather than via a JSON operator in SQL: `table_metadata`
        # is a generic JSON column (not JSONB), and its shape is only guaranteed by
        # the writer (table_chunking_service.py), not a DB constraint.
        stmt = (
            select(DocumentChunk.document_id, DocumentChunk.table_metadata)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.organization_id == organization_id,
                DocumentChunk.chunk_type == "table",
            )
        )
        result = await session.execute(stmt)
        return {
            document_id
            for document_id, table_metadata in result.all()
            if isinstance(table_metadata, dict) and table_metadata.get("is_valid") is False
        }

    async def _table_warnings_for_document(
        self, session: AsyncSession, document_id: UUID
    ) -> list[TableWarningItem]:
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.chunk_type == "table",
        )
        result = await session.execute(stmt)
        items: list[TableWarningItem] = []
        for chunk in result.scalars().all():
            meta = chunk.table_metadata or {}
            if meta.get("is_valid") is False:
                items.append(
                    TableWarningItem(
                        chunk_id=str(chunk.id),
                        page_number=chunk.page_number,
                        confidence=meta.get("confidence"),
                        reason="Low-confidence or malformed table extraction",
                    )
                )
        return items

    async def _user_names(
        self, session: AsyncSession, organization_id: UUID, user_ids: set[UUID]
    ) -> dict[UUID, str]:
        if not user_ids:
            return {}
        stmt = select(User).where(User.id.in_(user_ids), User.organization_id == organization_id)
        result = await session.execute(stmt)
        return {user.id: (user.display_name or user.email) for user in result.scalars().all()}

    async def _collection_rollups(
        self, session: AsyncSession, organization_id: UUID
    ) -> dict[UUID, _CollectionRollup]:
        # Member document statuses are aggregated in Python (not via SQL boolean-sum)
        # to keep the counting logic dialect-independent and identical to the rest
        # of this service's style.
        stmt = (
            select(CollectionDocument.collection_id, Document.status)
            .join(Document, Document.id == CollectionDocument.document_id)
            .where(Document.organization_id == organization_id)
        )
        result = await session.execute(stmt)
        rollups: dict[UUID, _CollectionRollup] = defaultdict(_CollectionRollup)
        for collection_id, doc_status in result.all():
            rollup = rollups[collection_id]
            rollup.total += 1
            if doc_status in _FAILED_STATUSES:
                rollup.failed += 1
            if doc_status in _PENDING_STATUSES:
                rollup.pending += 1
        return dict(rollups)

    # -- internal: chart builders -----------------------------------------------

    async def _status_distribution(
        self, session: AsyncSession, organization_id: UUID
    ) -> list[SourceStatusCount]:
        stmt = (
            select(Document.status, func.count(Document.id))
            .where(Document.organization_id == organization_id)
            .group_by(Document.status)
            .order_by(func.count(Document.id).desc())
        )
        result = await session.execute(stmt)
        return [SourceStatusCount(status=status, count=count) for status, count in result.all()]

    async def _indexing_failures(
        self, session: AsyncSession, organization_id: UUID, today: date
    ) -> list[IndexingFailurePoint]:
        since = datetime.combine(
            today - timedelta(days=_INDEXING_FAILURE_TREND_DAYS - 1),
            datetime.min.time(),
            tzinfo=UTC,
        )
        stmt = select(PipelineRun.created_at).where(
            PipelineRun.organization_id == organization_id,
            PipelineRun.pipeline_type.in_(_PIPELINE_INDEX_TYPES),
            PipelineRun.status == "failed",
            PipelineRun.created_at >= since,
        )
        result = await session.execute(stmt)
        counts: dict[date, int] = defaultdict(int)
        for (created_at,) in result.all():
            counts[created_at.date()] += 1

        points: list[IndexingFailurePoint] = []
        current = today - timedelta(days=_INDEXING_FAILURE_TREND_DAYS - 1)
        while current <= today:
            points.append(
                IndexingFailurePoint(date=current.isoformat(), failed_count=counts.get(current, 0))
            )
            current += timedelta(days=1)
        return points

    async def _stale_by_collection(
        self, session: AsyncSession, organization_id: UUID, today: date
    ) -> list[StaleByCollection]:
        stmt = (
            select(
                Collection.id,
                Collection.name,
                Document.trust_status,
                Document.review_status,
                Document.expiry_date,
            )
            .select_from(CollectionDocument)
            .join(Collection, Collection.id == CollectionDocument.collection_id)
            .join(Document, Document.id == CollectionDocument.document_id)
            .where(Collection.organization_id == organization_id)
        )
        result = await session.execute(stmt)
        counts: dict[tuple[UUID, str], int] = defaultdict(int)
        for (
            collection_id,
            collection_name,
            trust_status,
            review_status,
            expiry_date,
        ) in result.all():
            if (
                _freshness(
                    trust_status=trust_status,
                    review_status=review_status,
                    expiry_date=expiry_date,
                    today=today,
                )
                == "stale"
            ):
                counts[(collection_id, collection_name)] += 1

        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [
            StaleByCollection(collection_id=str(cid), collection_name=name, stale_count=count)
            for (cid, name), count in ranked[:_STALE_BY_COLLECTION_LIMIT]
        ]

    async def _ocr_quality_distribution(
        self, session: AsyncSession, organization_id: UUID
    ) -> list[OcrQualityCount]:
        stmt = (
            select(Document.ocr_quality_status, func.count(Document.id))
            .where(
                Document.organization_id == organization_id,
                Document.ocr_quality_status.is_not(None),
            )
            .group_by(Document.ocr_quality_status)
        )
        result = await session.execute(stmt)
        return [
            OcrQualityCount(ocr_quality_status=status, count=count)
            for status, count in result.all()
        ]

    async def _review_needs_by_owner(
        self, session: AsyncSession, organization_id: UUID, today: date
    ) -> list[ReviewNeedsByOwner]:
        counts: dict[UUID | None, int] = defaultdict(int)

        doc_stmt = select(
            Document.review_owner_id, Document.review_status, Document.review_due_date
        ).where(Document.organization_id == organization_id)
        for owner_id, review_status, review_due_date in (await session.execute(doc_stmt)).all():
            if _needs_review(
                review_status=review_status, review_due_date=review_due_date, today=today
            ):
                counts[owner_id] += 1

        col_stmt = select(
            Collection.review_owner_id, Collection.review_status, Collection.review_due_date
        ).where(Collection.organization_id == organization_id)
        for owner_id, review_status, review_due_date in (await session.execute(col_stmt)).all():
            if _needs_review(
                review_status=review_status, review_due_date=review_due_date, today=today
            ):
                counts[owner_id] += 1

        owner_ids = {owner_id for owner_id in counts if owner_id is not None}
        names = await self._user_names(session, organization_id, owner_ids)

        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        results: list[ReviewNeedsByOwner] = []
        for owner_id, count in ranked[:_REVIEW_NEEDS_BY_OWNER_LIMIT]:
            results.append(
                ReviewNeedsByOwner(
                    owner_id=str(owner_id) if owner_id else None,
                    owner_name=names.get(owner_id, "Unassigned") if owner_id else "Unassigned",
                    needs_review_count=count,
                )
            )
        return results

    async def _connector_freshness(
        self, session: AsyncSession, organization_id: UUID, today: date
    ) -> list[ConnectorFreshness]:
        connections_stmt = (
            select(ConnectorConnection, ConnectorProvider.key)
            .join(ConnectorProvider, ConnectorProvider.id == ConnectorConnection.provider_id)
            .where(ConnectorConnection.organization_id == organization_id)
        )
        connections = (await session.execute(connections_stmt)).all()
        if not connections:
            return []

        sync_stmt = (
            select(ConnectorSyncRun.connection_id, func.max(ConnectorSyncRun.completed_at))
            .where(
                ConnectorSyncRun.organization_id == organization_id,
                ConnectorSyncRun.status == ConnectorSyncRunStatus.completed.value,
            )
            .group_by(ConnectorSyncRun.connection_id)
        )
        last_success: dict[UUID, datetime | None] = {
            connection_id: completed_at
            for connection_id, completed_at in (await session.execute(sync_stmt)).all()
        }

        results: list[ConnectorFreshness] = []
        for connection, provider_key in connections:
            last_sync = last_success.get(connection.id) or connection.last_sync_at
            days_since = (today - last_sync.date()).days if last_sync else None
            results.append(
                ConnectorFreshness(
                    connection_id=str(connection.id),
                    connector_name=connection.display_name,
                    provider_key=provider_key,
                    last_successful_sync_at=last_sync,
                    days_since_last_sync=days_since,
                    status=connection.status,
                )
            )
        return sorted(
            results,
            key=lambda c: (c.days_since_last_sync is None, c.days_since_last_sync or 0),
            reverse=True,
        )

    # -- internal: row builder ----------------------------------------------

    async def _build_rows(
        self, session: AsyncSession, organization_id: UUID, filters: SourceHealthFilters
    ) -> list[SourceHealthRow]:
        today = datetime.now(tz=UTC).date()
        want_documents = filters.source_type in (None, "file", "connector")
        want_collections = filters.source_type in (None, "collection")

        rows: list[SourceHealthRow] = []
        owner_ids: set[UUID] = set()

        documents: list[Document] = []
        if want_documents:
            documents = await self._fetch_documents(session, organization_id)

        collections: list[Collection] = []
        if want_collections:
            collections = await self._fetch_collections(session, organization_id)

        last_indexed = await self._last_indexed_map(session, organization_id) if documents else {}
        collection_membership = (
            await self._collection_membership_map(session, organization_id) if documents else {}
        )
        connector_info = (
            await self._connector_info_map(session, organization_id) if documents else {}
        )
        missing_metadata_ids = (
            await self._missing_metadata_document_ids(session, organization_id)
            if documents
            else set()
        )
        table_warning_ids = (
            await self._table_warning_document_ids(session, organization_id) if documents else set()
        )
        collection_rollups = (
            await self._collection_rollups(session, organization_id) if collections else {}
        )

        for doc in documents:
            owner_id = doc.review_owner_id or doc.uploaded_by_user_id
            if owner_id:
                owner_ids.add(owner_id)

        for col in collections:
            owner_id = col.review_owner_id or col.owner_id
            if owner_id:
                owner_ids.add(owner_id)

        names = await self._user_names(session, organization_id, owner_ids)

        for doc in documents:
            source_type = (
                "connector"
                if doc.ingestion_source == DocumentIngestionSource.connector.value
                else "file"
            )
            owner_id = doc.review_owner_id or doc.uploaded_by_user_id
            collection = collection_membership.get(doc.id)
            connector = connector_info.get(doc.id)
            fresh = _freshness(
                trust_status=doc.trust_status,
                review_status=doc.review_status,
                expiry_date=doc.expiry_date,
                today=today,
            )

            actions = ["assign_reviewer", "mark_verified", "mark_deprecated", "open_document"]
            if doc.status not in _NON_REINDEXABLE_STATUSES:
                actions.append("reindex")
            if doc.ocr_quality_status in _OCR_LOW_STATUSES:
                actions.append("ocr_retry")
            if doc.error_message or doc.id in table_warning_ids:
                actions.append("view_error")

            rows.append(
                SourceHealthRow(
                    source_type=source_type,
                    source_id=str(doc.id),
                    source_name=doc.filename,
                    connector_name=connector[0] if connector else None,
                    collection_id=str(collection[0]) if collection else None,
                    collection_name=collection[1] if collection else None,
                    owner_id=str(owner_id) if owner_id else None,
                    owner_name=names.get(owner_id) if owner_id else None,
                    status=doc.status,
                    last_indexed_at=last_indexed.get(doc.id),
                    last_updated_at=doc.updated_at,
                    freshness=fresh,
                    trust_status=doc.trust_status,
                    ocr_quality=doc.ocr_quality_status,
                    review_status=doc.review_status,
                    graph_indexed=doc.graph_extraction_status,
                    missing_metadata=doc.id in missing_metadata_ids,
                    error_message=_truncate(doc.error_message),
                    available_actions=actions,
                )
            )

        for col in collections:
            owner_id = col.review_owner_id or col.owner_id
            rollup = collection_rollups.get(col.id, _CollectionRollup())
            if col.is_archived:
                status = "archived"
            elif rollup.failed > 0:
                status = "degraded"
            elif rollup.pending > 0:
                status = "pending"
            else:
                status = "healthy"
            fresh = _freshness(
                trust_status=None,
                review_status=col.review_status,
                expiry_date=col.expiry_date,
                today=today,
            )

            rows.append(
                SourceHealthRow(
                    source_type="collection",
                    source_id=str(col.id),
                    source_name=col.name,
                    collection_id=str(col.id),
                    collection_name=col.name,
                    owner_id=str(owner_id) if owner_id else None,
                    owner_name=names.get(owner_id) if owner_id else None,
                    status=status,
                    last_indexed_at=None,
                    last_updated_at=col.updated_at,
                    freshness=fresh,
                    ocr_quality=None,
                    review_status=col.review_status,
                    graph_indexed=None,
                    error_message=None,
                    available_actions=[
                        "assign_reviewer",
                        "mark_verified",
                        "mark_deprecated",
                        "open_collection",
                    ],
                )
            )

        filtered = [row for row in rows if self._row_matches(row, filters)]
        filtered.sort(key=lambda r: r.source_name.lower())
        return filtered

    def _row_matches(self, row: SourceHealthRow, filters: SourceHealthFilters) -> bool:
        if filters.source_type and row.source_type != filters.source_type:
            return False
        if filters.status and row.status != filters.status:
            return False
        if filters.collection_id and row.collection_id != filters.collection_id:
            return False
        if filters.owner_id and row.owner_id != filters.owner_id:
            return False
        if filters.freshness and row.freshness != filters.freshness:
            return False
        if filters.review_status and row.review_status != filters.review_status:
            return False
        if filters.ocr_quality and row.ocr_quality != filters.ocr_quality:
            return False
        if (
            filters.missing_metadata is not None
            and row.missing_metadata != filters.missing_metadata
        ):
            return False
        if filters.graph_indexed:
            want = filters.graph_indexed
            if want == "yes" and row.graph_indexed != "completed":
                return False
            if want == "no" and row.graph_indexed not in (None, "pending", "skipped"):
                return False
            if want == "failed" and row.graph_indexed != "failed":
                return False
        if filters.q:
            needle = filters.q.strip().lower()
            if needle and needle not in row.source_name.lower():
                return False
        return True
