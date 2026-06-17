from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.collection import Collection, CollectionAccessGrant, CollectionDocument
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.user import User

_ADMIN_ROLES: frozenset[str] = frozenset(
    {OrganizationRole.owner.value, OrganizationRole.admin.value}
)


class CollectionRepository:
    # ── Access filter ──────────────────────────────────────────────────────────

    @staticmethod
    def _access_filter(user_id: UUID, user_roles: list[str]):
        """
        Returns a SQLAlchemy WHERE condition for non-admin users, or None for admins.
        Admins (owner/admin org role) and collection owners always bypass restrictions.
        """
        if _ADMIN_ROLES.intersection(user_roles):
            return None

        non_empty_roles = [r for r in user_roles if r]

        role_grant = exists(
            select(CollectionAccessGrant.id).where(
                CollectionAccessGrant.collection_id == Collection.id,
                CollectionAccessGrant.grantee_type == "role",
                CollectionAccessGrant.grantee_value.in_(non_empty_roles)
                if non_empty_roles
                else CollectionAccessGrant.grantee_value == "__never__",
            )
        )
        member_grant = exists(
            select(CollectionAccessGrant.id).where(
                CollectionAccessGrant.collection_id == Collection.id,
                CollectionAccessGrant.grantee_type == "member",
                CollectionAccessGrant.grantee_value == str(user_id),
            )
        )

        return or_(
            Collection.owner_id == user_id,
            Collection.access_policy == "org_wide",
            and_(Collection.access_policy == "selected_roles", role_grant),
            and_(Collection.access_policy == "selected_members", member_grant),
            # 'admin_only' is excluded — non-admins cannot access those collections
        )

    # ── CRUD ───────────────────────────────────────────────────────────────────

    async def create(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        owner_id: UUID,
        name: str,
        description: str | None,
        access_policy: str,
        is_dynamic: bool = False,
        rule_schema: dict | None = None,
    ) -> Collection:
        collection = Collection(
            organization_id=organization_id,
            owner_id=owner_id,
            name=name.strip(),
            description=description,
            access_policy=access_policy,
            is_dynamic=is_dynamic,
            rule_schema=rule_schema,
        )
        session.add(collection)
        await session.flush()
        await session.refresh(collection, ["owner"])
        return collection

    async def get(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> Collection | None:
        stmt = (
            select(Collection)
            .options(selectinload(Collection.owner))
            .where(
                Collection.id == collection_id,
                Collection.organization_id == organization_id,
                Collection.is_archived.is_(False),
            )
        )
        access = self._access_filter(user_id, user_roles)
        if access is not None:
            stmt = stmt.where(access)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        name_query: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Collection]:
        stmt = (
            select(Collection)
            .options(selectinload(Collection.owner))
            .where(
                Collection.organization_id == organization_id,
                Collection.is_archived.is_(False),
            )
        )
        access = self._access_filter(user_id, user_roles)
        if access is not None:
            stmt = stmt.where(access)
        if name_query:
            stmt = stmt.where(Collection.name.ilike(f"%{name_query.strip()}%"))
        stmt = stmt.order_by(Collection.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        name_query: str | None = None,
    ) -> int:
        stmt = select(func.count(Collection.id)).where(
            Collection.organization_id == organization_id,
            Collection.is_archived.is_(False),
        )
        access = self._access_filter(user_id, user_roles)
        if access is not None:
            stmt = stmt.where(access)
        if name_query:
            stmt = stmt.where(Collection.name.ilike(f"%{name_query.strip()}%"))
        result = await session.execute(stmt)
        return result.scalar_one()

    async def count_documents(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(CollectionDocument.document_id)).where(
                CollectionDocument.collection_id == collection_id
            )
        )
        return result.scalar_one()

    async def count_indexed_documents(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(CollectionDocument.document_id))
            .join(Document, Document.id == CollectionDocument.document_id)
            .where(
                CollectionDocument.collection_id == collection_id,
                Document.status == DocumentStatus.indexed.value,
            )
        )
        return result.scalar_one()

    async def update(
        self,
        session: AsyncSession,
        *,
        collection: Collection,
        name: str | None = None,
        description: str | None = None,
        access_policy: str | None = None,
        rule_schema: dict | None = None,
        clear_rule_schema: bool = False,
    ) -> Collection:
        if name is not None:
            collection.name = name.strip()
        if description is not None:
            collection.description = description or None
        if access_policy is not None:
            collection.access_policy = access_policy
        if rule_schema is not None:
            collection.rule_schema = rule_schema
        elif clear_rule_schema:
            collection.rule_schema = None
        await session.flush()
        await session.refresh(collection, ["owner"])
        return collection

    async def set_rules(
        self,
        session: AsyncSession,
        *,
        collection: Collection,
        rule_schema: dict,
    ) -> Collection:
        collection.rule_schema = rule_schema
        collection.is_dynamic = True
        await session.flush()
        return collection

    async def list_dynamic_active(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[Collection]:
        result = await session.execute(
            select(Collection).where(
                Collection.organization_id == organization_id,
                Collection.is_dynamic.is_(True),
                Collection.is_archived.is_(False),
                Collection.rule_schema.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def archive(self, session: AsyncSession, *, collection: Collection) -> Collection:
        collection.is_archived = True
        await session.flush()
        return collection

    async def list_documents(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Document]:
        stmt = (
            select(Document)
            .join(CollectionDocument, CollectionDocument.document_id == Document.id)
            .where(CollectionDocument.collection_id == collection_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def document_in_collection(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
        document_id: UUID,
    ) -> bool:
        result = await session.execute(
            select(CollectionDocument).where(
                CollectionDocument.collection_id == collection_id,
                CollectionDocument.document_id == document_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_document(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
        document_id: UUID,
    ) -> None:
        membership = CollectionDocument(
            collection_id=collection_id,
            document_id=document_id,
        )
        session.add(membership)
        await session.flush()

    async def remove_document(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
        document_id: UUID,
    ) -> bool:
        result = await session.execute(
            delete(CollectionDocument).where(
                CollectionDocument.collection_id == collection_id,
                CollectionDocument.document_id == document_id,
            )
        )
        return result.rowcount > 0

    async def set_document_collections(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        organization_id: UUID,
        collection_ids: list[UUID],
    ) -> list[Collection]:
        await session.execute(
            delete(CollectionDocument).where(
                CollectionDocument.document_id == document_id,
                CollectionDocument.collection_id.in_(
                    select(Collection.id).where(Collection.organization_id == organization_id)
                ),
            )
        )
        for cid in collection_ids:
            session.add(CollectionDocument(collection_id=cid, document_id=document_id))
        await session.flush()

        if not collection_ids:
            return []
        result = await session.execute(
            select(Collection)
            .options(selectinload(Collection.owner))
            .where(
                Collection.id.in_(collection_ids),
                Collection.organization_id == organization_id,
            )
        )
        return list(result.scalars().all())

    async def get_document_collections(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> list[Collection]:
        stmt = (
            select(Collection)
            .options(selectinload(Collection.owner))
            .join(CollectionDocument, CollectionDocument.collection_id == Collection.id)
            .where(
                CollectionDocument.document_id == document_id,
                Collection.organization_id == organization_id,
                Collection.is_archived.is_(False),
            )
        )
        access = self._access_filter(user_id, user_roles)
        if access is not None:
            stmt = stmt.where(access)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_owner(self, session: AsyncSession, *, user_id: UUID) -> User | None:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    # ── Access policy management ───────────────────────────────────────────────

    async def get_policy(
        self,
        session: AsyncSession,
        *,
        collection_id: UUID,
    ) -> list[CollectionAccessGrant]:
        result = await session.execute(
            select(CollectionAccessGrant)
            .where(CollectionAccessGrant.collection_id == collection_id)
            .order_by(CollectionAccessGrant.grantee_type, CollectionAccessGrant.grantee_value)
        )
        return list(result.scalars().all())

    async def set_policy(
        self,
        session: AsyncSession,
        *,
        collection: Collection,
        access_policy: str,
        grants: list[
            dict
        ],  # list of {"grantee_type": ..., "grantee_value": ..., "granted_by_id": ...}
    ) -> list[CollectionAccessGrant]:
        # Update the policy mode on the collection
        collection.access_policy = access_policy

        # Replace all existing grants for this collection
        await session.execute(
            delete(CollectionAccessGrant).where(
                CollectionAccessGrant.collection_id == collection.id
            )
        )

        new_grants: list[CollectionAccessGrant] = []
        for grant in grants:
            g = CollectionAccessGrant(
                collection_id=collection.id,
                grantee_type=grant["grantee_type"],
                grantee_value=grant["grantee_value"],
                granted_by_id=grant.get("granted_by_id"),
            )
            session.add(g)
            new_grants.append(g)

        await session.flush()
        return new_grants
