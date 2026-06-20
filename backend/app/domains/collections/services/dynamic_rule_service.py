from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.collection import Collection, CollectionDocument
from app.models.document import Document

_logger = get_logger("events.collections.dynamic_rules")

# Supported rule fields and their DB column mappings
_FIELD_COLUMNS: dict[str, Any] = {
    "file_type": Document.file_type,
    "language": Document.language,
    "status": Document.status,
    "ingestion_source": Document.ingestion_source,
    "trust_status": Document.trust_status,
    "uploaded_by_user_id": Document.uploaded_by_user_id,
}

# Allowed operators per field
_FIELD_OPERATORS: dict[str, frozenset[str]] = {
    "file_type": frozenset({"eq", "neq", "in", "not_in"}),
    "language": frozenset({"eq", "neq", "in", "not_in"}),
    "status": frozenset({"eq", "neq", "in", "not_in"}),
    "ingestion_source": frozenset({"eq", "neq"}),
    "trust_status": frozenset({"eq", "neq", "in", "not_in"}),
    "uploaded_by_user_id": frozenset({"eq", "neq"}),
    "tags": frozenset({"contains", "not_contains"}),
}

_MAX_CONDITIONS = 20
_MAX_PREVIEW_LIMIT = 100


class DynamicRuleValidationError(ValueError):
    pass


def _validate_rule_schema(rule_schema: dict) -> None:
    logic = rule_schema.get("logic")
    if logic not in ("and", "or"):
        raise DynamicRuleValidationError("rule_schema.logic must be 'and' or 'or'")
    conditions = rule_schema.get("conditions")
    if not isinstance(conditions, list) or len(conditions) == 0:
        raise DynamicRuleValidationError("rule_schema.conditions must be a non-empty list")
    if len(conditions) > _MAX_CONDITIONS:
        raise DynamicRuleValidationError(
            f"rule_schema.conditions must not exceed {_MAX_CONDITIONS} items"
        )
    for i, cond in enumerate(conditions):
        field = cond.get("field")
        operator = cond.get("operator")
        value = cond.get("value")
        if field not in _FIELD_OPERATORS:
            raise DynamicRuleValidationError(
                f"conditions[{i}].field '{field}' is not a supported rule field"
            )
        if operator not in _FIELD_OPERATORS[field]:
            allowed = ", ".join(sorted(_FIELD_OPERATORS[field]))
            raise DynamicRuleValidationError(
                f"conditions[{i}].operator '{operator}' is not valid for field '{field}'"
                f" — allowed: {allowed}"
            )
        if value is None:
            raise DynamicRuleValidationError(f"conditions[{i}].value must not be null")
        if operator in ("in", "not_in"):
            if not isinstance(value, list) or len(value) == 0:
                raise DynamicRuleValidationError(
                    f"conditions[{i}].value must be a non-empty list for operator '{operator}'"
                )
        elif operator in ("eq", "neq", "contains", "not_contains"):
            if not isinstance(value, str) or not value:
                raise DynamicRuleValidationError(
                    f"conditions[{i}].value must be a non-empty string for operator '{operator}'"
                )


def _build_condition_clause(condition: dict) -> Any:
    field = condition["field"]
    operator = condition["operator"]
    value = condition["value"]

    if field == "tags":
        col = Document.tags
        if operator == "contains":
            return col.ilike(f"%{value}%")
        else:  # not_contains
            return ~col.ilike(f"%{value}%")

    col = _FIELD_COLUMNS[field]

    if operator == "eq":
        return col == value
    elif operator == "neq":
        return col != value
    elif operator == "in":
        return col.in_(value)
    elif operator == "not_in":
        return col.not_in(value)

    raise DynamicRuleValidationError(f"Unknown operator: {operator}")


def _build_where_clause(rule_schema: dict, organization_id: UUID) -> Any:
    logic = rule_schema["logic"]
    conditions = rule_schema["conditions"]
    clauses = [_build_condition_clause(c) for c in conditions]

    membership_clause = Document.organization_id == organization_id

    combined = and_(*clauses) if logic == "and" else or_(*clauses)
    return and_(membership_clause, combined)


class DynamicRuleService:
    def validate(self, rule_schema: dict) -> None:
        _validate_rule_schema(rule_schema)

    async def evaluate_document_ids(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        rule_schema: dict,
    ) -> list[UUID]:
        where = _build_where_clause(rule_schema, organization_id)
        result = await session.execute(select(Document.id).where(where))
        return list(result.scalars().all())

    async def preview(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        rule_schema: dict,
        limit: int = 20,
    ) -> tuple[list[Document], int]:
        limit = min(limit, _MAX_PREVIEW_LIMIT)
        where = _build_where_clause(rule_schema, organization_id)

        count_result = await session.execute(select(Document.id).where(where))
        all_ids = list(count_result.scalars().all())
        total = len(all_ids)

        docs_result = await session.execute(
            select(Document).where(where).order_by(Document.created_at.desc()).limit(limit)
        )
        docs = list(docs_result.scalars().all())
        return docs, total

    async def refresh_membership(
        self,
        session: AsyncSession,
        *,
        collection: Collection,
    ) -> int:
        if not collection.is_dynamic or not collection.rule_schema:
            return 0

        org_id = collection.organization_id
        rule_schema = collection.rule_schema

        matching_ids = await self.evaluate_document_ids(
            session,
            organization_id=org_id,
            rule_schema=rule_schema,
        )

        # Replace membership: delete all current, insert matching
        await session.execute(
            delete(CollectionDocument).where(CollectionDocument.collection_id == collection.id)
        )
        for doc_id in matching_ids:
            session.add(CollectionDocument(collection_id=collection.id, document_id=doc_id))

        collection.last_rule_evaluated_at = datetime.now(UTC)
        await session.flush()

        _logger.info(
            "dynamic_collection.refreshed",
            collection_id=str(collection.id),
            organization_id=str(org_id),
            matched_count=len(matching_ids),
        )
        return len(matching_ids)

    async def refresh_all_dynamic(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> dict[str, int]:
        result = await session.execute(
            select(Collection).where(
                Collection.organization_id == organization_id,
                Collection.is_dynamic.is_(True),
                Collection.is_archived.is_(False),
                Collection.rule_schema.is_not(None),
            )
        )
        collections = list(result.scalars().all())
        counts: dict[str, int] = {}
        for col in collections:
            count = await self.refresh_membership(session, collection=col)
            counts[str(col.id)] = count
        return counts
