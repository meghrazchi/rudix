from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization_service import AuthorizationService
from app.auth.dependencies import get_current_principal, require_permission, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.auth.policy_engine import Action
from app.auth.resource_context_builder import build_collection_resource_context
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.collections.repositories.collections import CollectionRepository
from app.domains.collections.schemas.collections import (
    AddDocumentToCollectionRequest,
    AddDocumentToCollectionResponse,
    CollectionAccessGrantItem,
    CollectionDetailResponse,
    CollectionDocumentItem,
    CollectionDocumentsResponse,
    CollectionListItemResponse,
    CollectionListResponse,
    CollectionPolicyResponse,
    CollectionRulesResponse,
    CreateCollectionRequest,
    DeleteCollectionResponse,
    DocumentCollectionsResponse,
    DynamicRuleSet,
    PreviewRulesDocumentItem,
    PreviewRulesRequest,
    PreviewRulesResponse,
    RefreshRulesResponse,
    SetCollectionRulesRequest,
    SetDocumentCollectionsRequest,
    UpdateCollectionPolicyRequest,
    UpdateCollectionRequest,
)
from app.domains.collections.services.dynamic_rule_service import (
    DynamicRuleService,
    DynamicRuleValidationError,
)
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.collection import Collection
from app.models.document import Document
from app.models.enums import DocumentReviewStatus, OrganizationRole
from app.models.permissions import PermissionType
from app.models.user import User

router = APIRouter(prefix="/collections", tags=["collections"])

_collection_repo = CollectionRepository()
_document_repo = DocumentRepository()
_audit_service = AuditLogService()
_dynamic_rule_service = DynamicRuleService()
_authorization_service = AuthorizationService()
_logger = get_logger("events.collections")

_ADMIN_ROLES = frozenset({OrganizationRole.owner.value, OrganizationRole.admin.value})


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


async def _resolve_reviewer_id(
    db: AsyncSession,
    *,
    organization_id: UUID,
    reviewer_id: str | None,
) -> UUID | None:
    if reviewer_id is None:
        return None
    try:
        parsed = UUID(reviewer_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid review_owner_id format",
        ) from exc
    result = await db.execute(
        select(User.id).where(
            User.id == parsed,
            User.organization_id == organization_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="review_owner_id must reference a user in the active organization",
        )
    return parsed


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _is_admin(principal: AuthenticatedPrincipal) -> bool:
    return bool(_ADMIN_ROLES.intersection(principal.roles))


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
        is_dynamic=collection.is_dynamic,
        last_rule_evaluated_at=collection.last_rule_evaluated_at,
        review_status=collection.review_status,
        review_owner_id=str(collection.review_owner_id)
        if collection.review_owner_id is not None
        else None,
        review_due_date=collection.review_due_date,
        expiry_date=collection.expiry_date,
        trust_level=collection.trust_level,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def _collection_to_detail(
    collection: Collection,
    document_count: int,
    indexed_count: int,
) -> CollectionDetailResponse:
    owner = collection.owner
    rule_schema: DynamicRuleSet | None = None
    if collection.rule_schema:
        try:
            rule_schema = DynamicRuleSet.model_validate(collection.rule_schema)
        except Exception:
            rule_schema = None
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
        is_dynamic=collection.is_dynamic,
        last_rule_evaluated_at=collection.last_rule_evaluated_at,
        review_status=collection.review_status,
        review_owner_id=str(collection.review_owner_id)
        if collection.review_owner_id is not None
        else None,
        review_due_date=collection.review_due_date,
        expiry_date=collection.expiry_date,
        trust_level=collection.trust_level,
        rule_schema=rule_schema,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def _doc_to_item(doc: Document) -> CollectionDocumentItem:
    return CollectionDocumentItem(
        document_id=str(doc.id),
        filename=doc.filename,
        file_type=doc.file_type,
        status=doc.status,
        review_status=doc.review_status,
        review_owner_id=str(doc.review_owner_id) if doc.review_owner_id is not None else None,
        review_due_date=doc.review_due_date,
        expiry_date=doc.expiry_date,
        trust_level=doc.trust_level,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=CollectionListResponse)
async def list_collections(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    name_query: Annotated[str | None, Query(max_length=120)] = None,
    freshness_filter: Annotated[DocumentReviewStatus | None, Query(alias="freshness")] = None,
) -> CollectionListResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    collections = await _collection_repo.list(
        db,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
        name_query=name_query,
        review_status=freshness_filter.value if freshness_filter is not None else None,
        limit=limit,
        offset=offset,
    )
    total = await _collection_repo.count(
        db,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
        name_query=name_query,
        review_status=freshness_filter.value if freshness_filter is not None else None,
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
    return CollectionListResponse(items=items, total=total, freshness=freshness_filter)


@router.post("", response_model=CollectionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    request: Request,
    payload: CreateCollectionRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.collections_create)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionDetailResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)

    rule_schema_dict: dict | None = None
    if payload.is_dynamic and payload.rule_schema is not None:
        try:
            _dynamic_rule_service.validate(payload.rule_schema.model_dump())
        except DynamicRuleValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        rule_schema_dict = payload.rule_schema.model_dump()

    collection = await _collection_repo.create(
        db,
        organization_id=organization_id,
        owner_id=user_id,
        name=payload.name.strip(),
        description=payload.description,
        access_policy=payload.access_policy,
        is_dynamic=payload.is_dynamic,
        rule_schema=rule_schema_dict,
    )

    matched_count = 0
    if collection.is_dynamic and collection.rule_schema:
        matched_count = await _dynamic_rule_service.refresh_membership(db, collection=collection)

    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.created",
        resource_type="collection",
        resource_id=collection.id,
        request_id=rid,
        metadata={
            "name": collection.name,
            "access_policy": collection.access_policy,
            "is_dynamic": collection.is_dynamic,
        },
    )
    await db.commit()
    await db.refresh(collection)
    await db.refresh(collection, ["owner"])

    _logger.info(
        "collection.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        collection_id=str(collection.id),
        is_dynamic=collection.is_dynamic,
    )
    return _collection_to_detail(collection, matched_count, 0)


@router.get("/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection(
    collection_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.collections_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionDetailResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    resource_ctx = build_collection_resource_context(
        collection=collection, organization_id=organization_id
    )
    await _authorization_service.authorize_or_raise(
        principal,
        Action.view,
        resource_ctx,
        db,
        deny_status=status.HTTP_404_NOT_FOUND,
        deny_detail="Collection not found",
    )

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
        Depends(require_permission(PermissionType.collections_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionDetailResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_id = _parse_uuid(collection_id, "Collection")

    # Fetch without access filter so admins can update any collection
    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    is_admin = _is_admin(principal)
    if not is_admin and str(collection.owner_id) != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the collection owner or an admin may edit this collection",
        )

    review_owner_uuid = await _resolve_reviewer_id(
        db,
        organization_id=organization_id,
        reviewer_id=payload.review_owner_id,
    )

    collection = await _collection_repo.update(
        db,
        collection=collection,
        name=payload.name,
        description=payload.description,
        access_policy=payload.access_policy,
        review_status=payload.review_status.value if payload.review_status else None,
        review_owner_id=review_owner_uuid,
        review_due_date=payload.review_due_date,
        expiry_date=payload.expiry_date,
        trust_level=payload.trust_level,
    )
    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.updated",
        resource_type="collection",
        resource_id=parsed_id,
        request_id=rid,
        metadata={
            "name": collection.name,
            "review_status": collection.review_status,
            "review_owner_id": str(collection.review_owner_id)
            if collection.review_owner_id is not None
            else None,
            "review_due_date": collection.review_due_date.isoformat()
            if collection.review_due_date
            else None,
            "expiry_date": collection.expiry_date.isoformat() if collection.expiry_date else None,
            "trust_level": collection.trust_level,
        },
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
        Depends(require_permission(PermissionType.collections_delete)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeleteCollectionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_id = _parse_uuid(collection_id, "Collection")

    # Admins can delete any collection — no access filter needed
    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,  # admin roles bypass access filter automatically
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


# ── Access policy endpoints ────────────────────────────────────────────────────


@router.get("/{collection_id}/access-policy", response_model=CollectionPolicyResponse)
async def get_collection_access_policy(
    collection_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionPolicyResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    parsed_id = _parse_uuid(collection_id, "Collection")

    # Admins always see the collection regardless of policy
    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    grants = await _collection_repo.get_policy(db, collection_id=parsed_id)
    return CollectionPolicyResponse(
        collection_id=collection_id,
        access_policy=collection.access_policy,  # type: ignore[arg-type]
        grants=[
            CollectionAccessGrantItem(
                grantee_type=g.grantee_type,  # type: ignore[arg-type]
                grantee_value=g.grantee_value,
            )
            for g in grants
        ],
    )


@router.put("/{collection_id}/access-policy", response_model=CollectionPolicyResponse)
async def update_collection_access_policy(
    request: Request,
    collection_id: str,
    payload: UpdateCollectionPolicyRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionPolicyResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    old_policy = collection.access_policy
    grants_data = [
        {
            "grantee_type": g.grantee_type,
            "grantee_value": g.grantee_value,
            "granted_by_id": user_id,
        }
        for g in payload.grants
    ]
    new_grants = await _collection_repo.set_policy(
        db,
        collection=collection,
        access_policy=payload.access_policy,
        grants=grants_data,
    )
    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.policy.updated",
        resource_type="collection",
        resource_id=parsed_id,
        request_id=rid,
        metadata={
            "old_access_policy": old_policy,
            "new_access_policy": payload.access_policy,
            "grant_count": len(new_grants),
        },
    )
    await db.commit()

    _logger.info(
        "collection.policy.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        collection_id=collection_id,
        access_policy=payload.access_policy,
    )
    return CollectionPolicyResponse(
        collection_id=collection_id,
        access_policy=collection.access_policy,  # type: ignore[arg-type]
        grants=[
            CollectionAccessGrantItem(
                grantee_type=g.grantee_type,  # type: ignore[arg-type]
                grantee_value=g.grantee_value,
            )
            for g in new_grants
        ],
    )


# ── Document management endpoints ─────────────────────────────────────────────


@router.get("/{collection_id}/documents", response_model=CollectionDocumentsResponse)
async def list_collection_documents(
    collection_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    freshness_filter: Annotated[DocumentReviewStatus | None, Query(alias="freshness")] = None,
) -> CollectionDocumentsResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    docs = await _collection_repo.list_documents(
        db,
        collection_id=parsed_id,
        review_status=freshness_filter.value if freshness_filter is not None else None,
        limit=limit,
        offset=offset,
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
        Depends(require_permission(PermissionType.collections_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AddDocumentToCollectionResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_collection_id = _parse_uuid(collection_id, "Collection")
    parsed_document_id = _parse_uuid(payload.document_id, "Document")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_collection_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
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
        Depends(require_permission(PermissionType.collections_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_collection_id = _parse_uuid(collection_id, "Collection")
    parsed_document_id = _parse_uuid(document_id, "Document")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_collection_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
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


# ── Dynamic rule endpoints ─────────────────────────────────────────────────────


@router.put("/{collection_id}/rules", response_model=CollectionRulesResponse)
async def set_collection_rules(
    request: Request,
    collection_id: str,
    payload: SetCollectionRulesRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.collections_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionRulesResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    is_admin = _is_admin(principal)
    if not is_admin and str(collection.owner_id) != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the collection owner or an admin may set rules",
        )

    rule_dict = payload.rule_schema.model_dump()
    try:
        _dynamic_rule_service.validate(rule_dict)
    except DynamicRuleValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await _collection_repo.set_rules(db, collection=collection, rule_schema=rule_dict)
    matched_count = await _dynamic_rule_service.refresh_membership(db, collection=collection)

    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.rules.set",
        resource_type="collection",
        resource_id=parsed_id,
        request_id=rid,
        metadata={"matched_count": matched_count},
    )
    await db.commit()

    _logger.info(
        "collection.rules.set",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        collection_id=collection_id,
        matched_count=matched_count,
    )
    return CollectionRulesResponse(
        collection_id=collection_id,
        is_dynamic=collection.is_dynamic,
        rule_schema=payload.rule_schema,
        last_rule_evaluated_at=collection.last_rule_evaluated_at,
        matched_count=matched_count,
    )


@router.post("/{collection_id}/rules/preview", response_model=PreviewRulesResponse)
async def preview_collection_rules(
    collection_id: str,
    payload: PreviewRulesRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PreviewRulesResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    rule_dict = payload.rule_schema.model_dump()
    try:
        _dynamic_rule_service.validate(rule_dict)
    except DynamicRuleValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    docs, total = await _dynamic_rule_service.preview(
        db,
        organization_id=organization_id,
        rule_schema=rule_dict,
        limit=payload.limit,
    )
    return PreviewRulesResponse(
        total=total,
        items=[
            PreviewRulesDocumentItem(
                document_id=str(doc.id),
                filename=doc.filename,
                file_type=doc.file_type,
                language=doc.language,
                status=doc.status,
                review_status=doc.review_status,
                trust_status=doc.trust_status,
                tags=doc.tags,
                ingestion_source=doc.ingestion_source,
            )
            for doc in docs
        ],
    )


@router.post(
    "/{collection_id}/rules/refresh",
    response_model=RefreshRulesResponse,
)
async def refresh_collection_rules(
    request: Request,
    collection_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> RefreshRulesResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    rid = _request_id(request)
    parsed_id = _parse_uuid(collection_id, "Collection")

    collection = await _collection_repo.get(
        db,
        collection_id=parsed_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
    )
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    if not collection.is_dynamic or not collection.rule_schema:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Collection is not a dynamic collection or has no rule schema",
        )

    matched_count = await _dynamic_rule_service.refresh_membership(db, collection=collection)
    await _audit_service.record(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="collection.rules.refreshed",
        resource_type="collection",
        resource_id=parsed_id,
        request_id=rid,
        metadata={"matched_count": matched_count},
    )
    await db.commit()

    _logger.info(
        "collection.rules.refreshed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        collection_id=collection_id,
        matched_count=matched_count,
    )
    return RefreshRulesResponse(
        collection_id=collection_id,
        matched_count=matched_count,
        last_rule_evaluated_at=collection.last_rule_evaluated_at,
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
    user_id = _user_id(principal)
    parsed_doc_id = _parse_uuid(document_id, "Document")

    collections = await _collection_repo.get_document_collections(
        db,
        document_id=parsed_doc_id,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=principal.roles,
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
