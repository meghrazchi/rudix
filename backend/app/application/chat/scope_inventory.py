"""Scope inventory answers: which documents are in the chat scope (R05-01)."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.citation_access import filter_chunks_by_cite_access
from app.application.chat.pipeline.deps import default_deps
from app.auth.models import AuthenticatedPrincipal
from app.auth.policy_engine import Action
from app.auth.resource_context_builder import (
    build_document_resource_contexts_batch,
    get_subject_accessible_collection_ids,
)
from app.core.config import settings
from app.domains.chat.schemas.chat import (
    ChatCitationResponse,
)
from app.domains.chat.services.citation_enrichment import _with_provenance
from app.domains.chat.services.retrieved_chunk import RetrievedChunk
from app.domains.chat.services.source_scope_service import (
    ResolvedSourceScope,
)
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus

_authorization_service = default_deps.authorization_service
_source_provenance_service = default_deps.source_provenance_service


_SCOPE_INVENTORY_MAX_LISTED_DOCUMENTS = 200


_SCOPE_INVENTORY_MAX_CITATIONS = 20


_SCOPE_INVENTORY_SNIPPET_CHARS = 400


@dataclass(frozen=True)
class ScopeInventoryDocument:
    document_id: UUID
    filename: str
    file_type: str
    page_count: int | None
    chunk_count: int | None


@dataclass(frozen=True)
class ScopeInventoryResult:
    total_count: int
    listed_documents: list[ScopeInventoryDocument]
    retrieved_chunks: list[RetrievedChunk]
    citations: list[ChatCitationResponse]


def _is_scope_inventory_question(question: str) -> bool:
    normalized = " ".join(question.lower().split())
    if not normalized:
        return False

    plural_source_terms = (
        "files",
        "documents",
        "docs",
        "sources",
        "source files",
        "indexed files",
    )
    singular_source_terms = ("file", "document", "doc", "source")
    has_plural_source_term = any(term in normalized for term in plural_source_terms)
    has_any_source_term = has_plural_source_term or any(
        term in normalized for term in singular_source_terms
    )
    if not has_any_source_term:
        return False

    if any(
        phrase in normalized
        for phrase in (
            "which files",
            "what files",
            "which documents",
            "what documents",
            "which docs",
            "what docs",
            "which sources",
            "what sources",
            "files are included",
            "documents are included",
            "docs are included",
            "sources are included",
            "files included",
            "documents included",
            "docs included",
            "sources included",
            "included files",
            "included documents",
            "selected files",
            "selected documents",
            "selected sources",
            "available files",
            "available documents",
            "available sources",
            "files in this collection",
            "documents in this collection",
            "files in this connector",
            "documents in this connector",
            "files in scope",
            "documents in scope",
            "sources in scope",
            "tell me about files",
            "tell me about the files",
            "explain about files",
            "explain about the files",
        )
    ):
        return True

    if has_plural_source_term and normalized.startswith(("list ", "show ")):
        return True

    return False


def _scope_inventory_snippet(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= _SCOPE_INVENTORY_SNIPPET_CHARS:
        return normalized
    return normalized[:_SCOPE_INVENTORY_SNIPPET_CHARS].rsplit(" ", 1)[0].strip()


async def _filter_authorized_documents_for_chat(
    db_session: AsyncSession,
    *,
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    user_id: UUID,
    user_roles: list[str],
    documents: list[Document],
) -> list[Document]:
    if not documents or frozenset({"owner", "admin"}).intersection(user_roles):
        return documents

    accessible_col_ids = await get_subject_accessible_collection_ids(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=user_roles,
    )
    resource_contexts = await build_document_resource_contexts_batch(
        db_session,
        documents=documents,
        organization_id=organization_id,
        subject_accessible_collection_ids=accessible_col_ids,
    )
    allowed_ids = {
        ctx.resource_id
        for ctx in await _authorization_service.filter_accessible_resources(
            principal, Action.chat, resource_contexts, db_session
        )
    }
    return [document for document in documents if str(document.id) in allowed_ids]


async def _filter_authorized_document_ids_for_chat(
    db_session: AsyncSession,
    *,
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    user_id: UUID,
    user_roles: list[str],
    document_ids: list[UUID] | None,
) -> list[UUID] | None:
    if document_ids is None or not document_ids:
        return document_ids
    if frozenset({"owner", "admin"}).intersection(user_roles):
        return document_ids

    result = await db_session.execute(
        select(Document).where(
            Document.organization_id == organization_id,
            Document.id.in_(document_ids),
        )
    )
    documents = list(result.scalars().all())
    allowed_documents = await _filter_authorized_documents_for_chat(
        db_session,
        principal=principal,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=user_roles,
        documents=documents,
    )
    allowed_ids = {document.id for document in allowed_documents}
    return [document_id for document_id in document_ids if document_id in allowed_ids]


async def _build_scope_inventory_result(
    db_session: AsyncSession,
    *,
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    user_id: UUID,
    user_roles: list[str],
    document_ids: list[UUID] | None,
) -> ScopeInventoryResult:
    statement = select(Document).where(
        Document.organization_id == organization_id,
        Document.status == DocumentStatus.indexed.value,
    )
    if document_ids is not None:
        if not document_ids:
            return ScopeInventoryResult(
                total_count=0,
                listed_documents=[],
                retrieved_chunks=[],
                citations=[],
            )
        statement = statement.where(Document.id.in_(document_ids))

    result = await db_session.execute(
        statement.order_by(Document.filename.asc(), Document.id.asc())
    )
    documents = list(result.scalars().all())
    if document_ids is not None:
        order_by_scope = {document_id: index for index, document_id in enumerate(document_ids)}
        documents.sort(key=lambda document: order_by_scope.get(document.id, len(order_by_scope)))

    documents = await _filter_authorized_documents_for_chat(
        db_session,
        principal=principal,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=user_roles,
        documents=documents,
    )
    listed_documents = [
        ScopeInventoryDocument(
            document_id=document.id,
            filename=document.filename,
            file_type=document.file_type,
            page_count=document.page_count,
            chunk_count=document.chunk_count,
        )
        for document in documents[:_SCOPE_INVENTORY_MAX_LISTED_DOCUMENTS]
    ]
    citation_document_ids = [
        document.document_id for document in listed_documents[:_SCOPE_INVENTORY_MAX_CITATIONS]
    ]
    if not citation_document_ids:
        return ScopeInventoryResult(
            total_count=len(documents),
            listed_documents=listed_documents,
            retrieved_chunks=[],
            citations=[],
        )

    chunks_result = await db_session.execute(
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id.in_(citation_document_ids),
            DocumentChunk.index_version.in_(settings.active_index_versions),
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
    )
    first_chunk_by_document_id: dict[UUID, DocumentChunk] = {}
    for chunk in chunks_result.scalars().all():
        if chunk.document_id not in first_chunk_by_document_id:
            first_chunk_by_document_id[chunk.document_id] = chunk
    # Listing needs read access; citing needs the cite permission as well.
    citable_chunks = await filter_chunks_by_cite_access(
        db_session,
        principal=principal,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=user_roles,
        chunks=list(first_chunk_by_document_id.values()),
    )
    first_chunk_by_document_id = {chunk.document_id: chunk for chunk in citable_chunks}

    provenance_by_chunk_id = await _source_provenance_service.load_citation_details(
        db_session,
        organization_id=organization_id,
        chunk_ids=[chunk.id for chunk in first_chunk_by_document_id.values()],
    )
    retrieved_chunks: list[RetrievedChunk] = []
    citations: list[ChatCitationResponse] = []
    for rank, document in enumerate(listed_documents, start=1):
        listed_chunk = first_chunk_by_document_id.get(document.document_id)
        if listed_chunk is None:
            continue
        retrieved_chunk = RetrievedChunk(
            document_id=document.document_id,
            chunk_id=listed_chunk.id,
            filename=document.filename,
            page_number=listed_chunk.page_number,
            text=listed_chunk.text,
            similarity_score=1.0,
            original_rank=rank,
            final_rank=rank,
            retrieval_source="scope_inventory",
            chunk_type=listed_chunk.chunk_type,
            chunk_level=listed_chunk.chunk_level or 0,
        )
        retrieved_chunks.append(retrieved_chunk)
        citation = ChatCitationResponse(
            document_id=str(document.document_id),
            chunk_id=str(listed_chunk.id),
            filename=document.filename,
            page_number=listed_chunk.page_number,
            score=1.0,
            similarity_score=1.0,
            original_rank=rank,
            final_rank=rank,
            text_snippet=_scope_inventory_snippet(listed_chunk.text),
            start_offset=listed_chunk.source_start_offset,
            end_offset=listed_chunk.source_end_offset,
        )
        citations.append(
            _with_provenance(
                citation,
                provenance_by_chunk_id.get(listed_chunk.id),
            )
        )

    return ScopeInventoryResult(
        total_count=len(documents),
        listed_documents=listed_documents,
        retrieved_chunks=retrieved_chunks,
        citations=citations,
    )


def _build_scope_inventory_answer(
    *,
    inventory: ScopeInventoryResult,
    source_scope_result: ResolvedSourceScope,
) -> str:
    scope_label = source_scope_result.label or "All indexed files"
    if inventory.total_count == 0:
        return f"No indexed files were found in the selected scope ({scope_label})."

    lines = [
        f"The selected scope ({scope_label}) includes {inventory.total_count} indexed file(s).",
        "",
        "Files included:",
    ]
    for document in inventory.listed_documents:
        details: list[str] = [document.file_type.upper()]
        if document.page_count is not None:
            page_label = "page" if document.page_count == 1 else "pages"
            details.append(f"{document.page_count} {page_label}")
        if document.chunk_count is not None:
            chunk_label = "chunk" if document.chunk_count == 1 else "chunks"
            details.append(f"{document.chunk_count} {chunk_label}")
        lines.append(f"- {document.filename} ({', '.join(details)})")

    if inventory.total_count > len(inventory.listed_documents):
        lines.append(
            f"- Showing first {len(inventory.listed_documents)} of "
            f"{inventory.total_count} indexed files."
        )
    if inventory.citations:
        lines.append("")
        lines.append("Citations reference the first indexed chunk for the listed files.")
    return "\n".join(lines)
