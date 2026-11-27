"""Sample dataset loading workflow (persistence + commit live here, not in the router)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.documents.repositories.document_lookups import DocumentLookupRepository
from app.models.document import Document
from app.models.enums import DocumentStatus

_lookups = DocumentLookupRepository()

_SAMPLE_DOCUMENTS: list[dict[str, Any]] = [
    {
        "filename": "Rudix Quick Start Guide.pdf",
        "file_type": "pdf",
        "source": "sample-dataset",
        "notes": "Sample document — demonstrates PDF ingestion and citation extraction.",
        "page_count": 8,
        "chunk_count": 24,
    },
    {
        "filename": "Enterprise RAG Best Practices.docx",
        "file_type": "docx",
        "source": "sample-dataset",
        "notes": "Sample document — covers retrieval-augmented generation patterns for enterprise teams.",
        "page_count": 12,
        "chunk_count": 38,
    },
    {
        "filename": "Data Governance Policy Template.txt",
        "file_type": "txt",
        "source": "sample-dataset",
        "notes": "Sample document — plain-text policy template for knowledge-base governance.",
        "page_count": None,
        "chunk_count": 14,
    },
]


@dataclass(frozen=True)
class SampleDatasetOutcome:
    created: int
    skipped: int
    document_ids: list[str]


async def load_sample_dataset_workflow(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> SampleDatasetOutcome:
    """Create pre-indexed sample documents; idempotent by (org, source, filename)."""
    if not await _lookups.sample_docs_enabled(db_session, organization_id=organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sample dataset is not enabled for this organization.",
        )

    existing_names = await _lookups.sample_document_filenames(
        db_session, organization_id=organization_id
    )

    created_ids: list[str] = []
    skipped = 0
    for spec in _SAMPLE_DOCUMENTS:
        if spec["filename"] in existing_names:
            skipped += 1
            continue
        doc = Document(
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename=spec["filename"],
            file_type=spec["file_type"],
            storage_bucket="sample",
            storage_object_key=f"sample/{organization_id}/{spec['filename']}",
            status=DocumentStatus.indexed.value,
            source=spec["source"],
            notes=spec["notes"],
            page_count=spec["page_count"],
            chunk_count=spec["chunk_count"],
            ingestion_source="upload",
        )
        db_session.add(doc)
        await db_session.flush()
        created_ids.append(str(doc.id))

    await db_session.commit()
    return SampleDatasetOutcome(created=len(created_ids), skipped=skipped, document_ids=created_ids)
