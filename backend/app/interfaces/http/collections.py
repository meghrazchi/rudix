from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.collections.repositories.collections import CollectionRepository
from app.domains.collections.schemas.collections import (
    AddDocumentToCollectionRequest,
    AddDocumentToCollectionResponse,
    CollectionDetailResponse,
    CollectionDocumentItem,
    CollectionDocumentsResponse,
    CollectionListItemResponse,
    CollectionListResponse,
    CreateCollectionRequest,
    DeleteCollectionResponse,
    DocumentCollectionsResponse,
    SetDocumentCollectionsRequest,
    UpdateCollectionRequest,
)
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.collection import Collection
from app.models.document import Document
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/collections", tags=["collections"])

_collection_repo = CollectionRepository()
_document_repo = DocumentRepository()
_audit_service = AuditLogService()
_logger = get_logger("events.collections")


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user context",
        ) from exc


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} not found",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _collection_to_list_item(
    collection: Collection,
    document_count: int,
    indexed_count: int,
) -> CollectionListItemResponse:
    owner = collection.owner
    return CollectionListItemResponse(
        collection_id=str(collection.id),
        name=collection.name,
        description=collection.description,
        owner_id=str(collection.owner_id),
        owner_email=owner.email if owner is not None else None,
        document_count=document_count,
        indexed_count=indexed_count,
        access_policy=collection.access_policy,  # type: ignore[arg-type]
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def _collection_to_detail(
    collection: Collection,
    document_count: int,
    indexed_count: int,
) -> CollectionDetailResponse:
    owner = collection.owner
    return CollectionDetailResponse(
        collection_id=str(collection.id),
        name=collection.name,
        description=collection.description,
        owner_id=str(collection.owner_id),
        owner_email=owner.email if owner is not None else None,
        created_by_email=owner.email if owner is not None else None,
        document_count=document_count,
        indexed_count=indexed_count,
        access_policy=collection.access_policy,  # type: ignore[arg-type]
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def _doc_to_item(doc: Document) -> CollectionDocumentItem:
    return CollectionDocumentItem(
        document_id=str(doc.id),
        filename=doc.filename,
        file_type=doc.file_type,
        status=doc.status,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=CollectionListResponse)
async def list_collections(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    name_query: Annotated[str | None, Query(max_length=120)] = None,
) -> CollectionListResponse:
    organization_id = _org_id(principal)
    collections = await _collection_repo.list(
        db,
        organization_id=organization_id,
        name_query=name_query,
        limit=limit,
        offset=offset,
    )
    total = await _collection_repo.count(
        db, organization_id=organization_id, name_query=name_query
    )
    items = []
    for col in collections:
        doc_count = await _collection_repo.count_documents(db, collection_id=col.id)
        idx_count = await _collection_repo.count_indexed_documents(db, collection_id=col.id)
        items.append(_collection_to_list_item(col, doc_count, idx_count))

    _logger.info(
        "collections.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        total=total,
        returned=len(items),
    )
    return CollectionListResponse(items=items, total=total)


@router.post("", response_model=CollectionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    request: Request,
    payload: CreateCollectionRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionDetailResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)

    collection = await _collection_repo.create(
        db,
        organization_id=organization_id,
        owner_id=user_id,
        name=payload.name.strip(),
        description=payload.description,
        access_policy=payload.access_policy,
    )
    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.created",
        resource_type="collection",
        resource_id=collection.id,
        request_id=rid,
        metadata={"name": collection.name, "access_policy": collection.access_policy},
    )
    await db.commit()

    _logger.info(
        "collection.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        collection_id=str(collection.id),
    )
    return _collection_to_detail(collection, 0, 0)


@router.get("/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection(
    collection_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionDetailResponse:
    organization_id = _org_id(principal)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db, collection_id=parsed_id, organization_id=organization_id
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    doc_count = await _collection_repo.count_documents(db, collection_id=parsed_id)
    idx_count = await _collection_repo.count_indexed_documents(db, collection_id=parsed_id)
    return _collection_to_detail(collection, doc_count, idx_count)


@router.patch("/{collection_id}", response_model=CollectionDetailResponse)
async def update_collection(
    request: Request,
    collection_id: str,
    payload: UpdateCollectionRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionDetailResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db, collection_id=parsed_id, organization_id=organization_id
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    is_admin = principal.role in (OrganizationRole.owner.value, OrganizationRole.admin.value)
    if not is_admin and str(collection.owner_id) != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the collection owner or an admin may edit this collection",
        )

    collection = await _collection_repo.update(
        db,
        collection=collection,
        name=payload.name,
        description=payload.description,
        access_policy=payload.access_policy,
    )
    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.updated",
        resource_type="collection",
        resource_id=parsed_id,
        request_id=rid,
        metadata={"name": collection.name},
    )
    await db.commit()

    doc_count = await _collection_repo.count_documents(db, collection_id=parsed_id)
    idx_count = await _collection_repo.count_indexed_documents(db, collection_id=parsed_id)
    _logger.info(
        "collection.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        collection_id=collection_id,
    )
    return _collection_to_detail(collection, doc_count, idx_count)


@router.delete("/{collection_id}", response_model=DeleteCollectionResponse)
async def delete_collection(
    request: Request,
    collection_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeleteCollectionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db, collection_id=parsed_id, organization_id=organization_id
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    await _collection_repo.archive(db, collection=collection)
    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.deleted",
        resource_type="collection",
        resource_id=parsed_id,
        request_id=rid,
        metadata={"name": collection.name},
    )
    await db.commit()

    _logger.info(
        "collection.deleted",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        collection_id=collection_id,
    )
    return DeleteCollectionResponse(collection_id=collection_id, archived=True)


@router.get("/{collection_id}/documents", response_model=CollectionDocumentsResponse)
async def list_collection_documents(
    collection_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CollectionDocumentsResponse:
    organization_id = _org_id(principal)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db, collection_id=parsed_id, organization_id=organization_id
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    docs = await _collection_repo.list_documents(
        db, collection_id=parsed_id, limit=limit, offset=offset
    )
    total = await _collection_repo.count_documents(db, collection_id=parsed_id)
    return CollectionDocumentsResponse(
        items=[_doc_to_item(d) for d in docs],
        total=total,
    )


@router.post(
    "/{collection_id}/documents",
    response_model=AddDocumentToCollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_document_to_collection(
    request: Request,
    collection_id: str,
    payload: AddDocumentToCollectionRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AddDocumentToCollectionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_collection_id = _parse_uuid(collection_id, "Collection")
    parsed_document_id = _parse_uuid(payload.document_id, "Document")

    collection = await _collection_repo.get(
        db, collection_id=parsed_collection_id, organization_id=organization_id
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    document = await _document_repo.get_document(
        db, document_id=parsed_document_id, organization_id=organization_id
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    already_member = await _collection_repo.document_in_collection(
        db, collection_id=parsed_collection_id, document_id=parsed_document_id
    )
    if not already_member:
        await _collection_repo.add_document(
            db, collection_id=parsed_collection_id, document_id=parsed_document_id
        )
        await _audit_service.record(
            db,
            organization_id=organization_id,
            user_id=user_id,
            action="collection.document.added",
            resource_type="collection",
            resource_id=parsed_collection_id,
            request_id=rid,
            metadata={"document_id": payload.document_id},
        )
        await db.commit()

    _logger.info(
        "collection.document.added",
        organization_id=principal.organization_id,
        collection_id=collection_id,
        document_id=payload.document_id,
    )
    return AddDocumentToCollectionResponse(
        collection_id=collection_id,
        document_id=payload.document_id,
    )


@router.delete(
    "/{collection_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_document_from_collection(
    request: Request,
    collection_id: str,
    document_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_collection_id = _parse_uuid(collection_id, "Collection")
    parsed_document_id = _parse_uuid(document_id, "Document")

    collection = await _collection_repo.get(
        db, collection_id=parsed_collection_id, organization_id=organization_id
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    removed = await _collection_repo.remove_document(
        db, collection_id=parsed_collection_id, document_id=parsed_document_id
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document is not in this collection",
        )

    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.document.removed",
        resource_type="collection",
        resource_id=parsed_collection_id,
        request_id=rid,
        metadata={"document_id": document_id},
    )
    await db.commit()

    _logger.info(
        "collection.document.removed",
        organization_id=principal.organization_id,
        collection_id=collection_id,
        document_id=document_id,
    )


# ── Document-scoped endpoints ──────────────────────────────────────────────────

documents_router = APIRouter(prefix="/documents", tags=["collections"])


@documents_router.get(
    "/{document_id}/collections",
    response_model=DocumentCollectionsResponse,
)
async def get_document_collections(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentCollectionsResponse:
    organization_id = _org_id(principal)
    parsed_doc_id = _parse_uuid(document_id, "Document")

    collections = await _collection_repo.get_document_collections(
        db, document_id=parsed_doc_id, organization_id=organization_id
    )
    items = []
    for col in collections:
        doc_count = await _collection_repo.count_documents(db, collection_id=col.id)
        idx_count = await _collection_repo.count_indexed_documents(db, collection_id=col.id)
        items.append(_collection_to_list_item(col, doc_count, idx_count))
    return DocumentCollectionsResponse(items=items)


@documents_router.put(
    "/{document_id}/collections",
    response_model=DocumentCollectionsResponse,
)
async def set_document_collections(
    request: Request,
    document_id: str,
    payload: SetDocumentCollectionsRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentCollectionsResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_doc_id = _parse_uuid(document_id, "Document")

    document = await _document_repo.get_document(
        db, document_id=parsed_doc_id, organization_id=organization_id
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    parsed_collection_ids = [_parse_uuid(cid, "Collection") for cid in payload.collection_ids]
    collections = await _collection_repo.set_document_collections(
        db,
        document_id=parsed_doc_id,
        organization_id=organization_id,
        collection_ids=parsed_collection_ids,
    )
    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="document.collections.set",
        resource_type="document",
        resource_id=parsed_doc_id,
        request_id=rid,
        metadata={"collection_ids": payload.collection_ids},
    )
    await db.commit()

    items = []
    for col in collections:
        doc_count = await _collection_repo.count_documents(db, collection_id=col.id)
        idx_count = await _collection_repo.count_indexed_documents(db, collection_id=col.id)
        items.append(_collection_to_list_item(col, doc_count, idx_count))
    return DocumentCollectionsResponse(items=items)
