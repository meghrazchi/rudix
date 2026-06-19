from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.billing.schemas.billing import (
    BillingContact,
    BillingContactUpdateRequest,
    BillingCycle,
    BillingDateRange,
    BillingPlanInfo,
    BillingPlanStatus,
    BillingPortalSession,
    BillingQuota,
    BillingUsageSummary,
    Invoice,
    InvoiceStatus,
)
from app.domains.quota.repositories.quota_repository import QuotaRepository
from app.domains.quota.services.quota_service import get_effective_limits
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.quotas import OrgQuotaUsage
from app.models.usage import UsageEvent
from app.models.user import User

_quota_repo = QuotaRepository()

_GB = 1024**3
_UPLOADS_LABEL = "Document uploads"
_SEATS_LABEL = "Seats"
_STORAGE_LABEL = "Storage"
_QUESTIONS_LABEL = "Monthly questions"
_TOKENS_LABEL = "Token allowance"
_EVALUATIONS_LABEL = "Evaluation runs"
_AGENTS_LABEL = "Agent runs"
_CONNECTORS_LABEL = "Connector syncs"


def _parse_range(range_name: BillingDateRange) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    end = now
    if range_name == BillingDateRange.seven_days:
        start = end - timedelta(days=6)
    elif range_name == BillingDateRange.ninety_days:
        start = end - timedelta(days=89)
    elif range_name == BillingDateRange.billing_period:
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = end - timedelta(days=29)
    return start, end


def _start_of_month(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _to_gb(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value / _GB, 3)


def _limit_value(config: dict | None, key: str) -> int | None:
    if not config:
        return None
    value = config.get(key)
    return int(value) if isinstance(value, (int, float)) else None


def _current_value_for_usage(
    usage_map: dict[str, OrgQuotaUsage],
    quota_type: str,
) -> int:
    usage = usage_map.get(quota_type)
    return usage.current_value if usage is not None else 0


def _masked_payment_summary(payment_method_summary: str | None) -> str | None:
    if payment_method_summary is None:
        return "Managed securely in the billing portal"
    trimmed = payment_method_summary.strip()
    if not trimmed:
        return "Managed securely in the billing portal"
    return trimmed


def _sanitize_contact_payload(payload: dict[str, object]) -> BillingContact:
    return BillingContact(
        email=payload.get("email") if isinstance(payload.get("email"), str) else None,
        name=payload.get("name") if isinstance(payload.get("name"), str) else None,
        address_line1=payload.get("address_line1")
        if isinstance(payload.get("address_line1"), str)
        else None,
        address_line2=payload.get("address_line2")
        if isinstance(payload.get("address_line2"), str)
        else None,
        city=payload.get("city") if isinstance(payload.get("city"), str) else None,
        state=payload.get("state") if isinstance(payload.get("state"), str) else None,
        postal_code=payload.get("postal_code")
        if isinstance(payload.get("postal_code"), str)
        else None,
        country=payload.get("country") if isinstance(payload.get("country"), str) else None,
        tax_id=payload.get("tax_id") if isinstance(payload.get("tax_id"), str) else None,
        payment_method_summary=_masked_payment_summary(
            payload.get("payment_method_summary")
            if isinstance(payload.get("payment_method_summary"), str)
            else None
        ),
    )


async def _load_org_context(
    db_session: AsyncSession,
    organization_id: UUID,
) -> tuple[Organization | None, list[OrganizationMember]]:
    org_result = await db_session.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    organization = org_result.scalar_one_or_none()

    members_result = await db_session.execute(
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.created_at.asc())
    )
    members = list(members_result.scalars().all())
    return organization, members


async def _load_usage_events(
    db_session: AsyncSession,
    organization_id: UUID,
    start: datetime,
    end: datetime,
) -> list[UsageEvent]:
    result = await db_session.execute(
        select(UsageEvent)
        .where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.created_at >= start,
            UsageEvent.created_at <= end,
        )
        .order_by(UsageEvent.created_at.asc())
    )
    return list(result.scalars().all())


async def _load_documents(
    db_session: AsyncSession,
    organization_id: UUID,
    start: datetime,
    end: datetime,
) -> list[Document]:
    result = await db_session.execute(
        select(Document)
        .where(
            Document.organization_id == organization_id,
            Document.created_at >= start,
            Document.created_at <= end,
        )
        .order_by(Document.created_at.asc())
    )
    return list(result.scalars().all())


def _usage_event_matches(event_type: str, prefixes: Iterable[str]) -> bool:
    return any(event_type.startswith(prefix) for prefix in prefixes)


class BillingService:
    async def get_plan_info(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> BillingPlanInfo:
        policy = await _quota_repo.get_policy(db_session, organization_id=organization_id)
        effective_limits = get_effective_limits(policy)
        usage_map = {
            usage.quota_type: usage
            for usage in await _quota_repo.list_usage(db_session, organization_id=organization_id)
        }
        _, members = await _load_org_context(db_session, organization_id)
        seat_limit = _limit_value(effective_limits.get("seats"), "hard_limit")

        managed = policy is not None
        renewal_date = datetime.now(UTC) + timedelta(days=30) if managed else None

        return BillingPlanInfo(
            plan_name="Self-hosted" if not managed else "Managed plan",
            status=BillingPlanStatus.self_hosted if not managed else BillingPlanStatus.active,
            billing_cycle=BillingCycle.monthly if managed else None,
            renewal_date=renewal_date,
            trial_end_date=None,
            seats_used=len(members),
            seats_included=seat_limit,
            storage_used_gb=_to_gb(_current_value_for_usage(usage_map, "storage_bytes")),
            storage_included_gb=_to_gb(
                _limit_value(effective_limits.get("storage_bytes"), "hard_limit")
            ),
            monthly_questions_used=_current_value_for_usage(usage_map, "questions"),
            monthly_questions_included=_limit_value(
                effective_limits.get("questions"), "hard_limit"
            ),
            token_allowance_used=_current_value_for_usage(usage_map, "tokens"),
            token_allowance_included=_limit_value(effective_limits.get("tokens"), "hard_limit"),
            evaluation_allowance_used=_current_value_for_usage(usage_map, "evaluations"),
            evaluation_allowance_included=_limit_value(
                effective_limits.get("evaluations"), "hard_limit"
            ),
            agent_allowance_used=_current_value_for_usage(usage_map, "agent_runs"),
            agent_allowance_included=_limit_value(effective_limits.get("agent_runs"), "hard_limit"),
            connector_allowance_used=_current_value_for_usage(usage_map, "connectors"),
            connector_allowance_included=_limit_value(
                effective_limits.get("connectors"), "hard_limit"
            ),
            can_manage_subscription=managed,
            can_cancel_plan=managed,
        )

    async def get_usage_summary(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        range_name: BillingDateRange = BillingDateRange.thirty_days,
    ) -> BillingUsageSummary:
        start, end = _parse_range(range_name)
        documents = await _load_documents(db_session, organization_id, start, end)
        events = await _load_usage_events(db_session, organization_id, start, end)
        usage_map = {
            usage.quota_type: usage
            for usage in await _quota_repo.list_usage(db_session, organization_id=organization_id)
        }

        confidence_values: list[float] = []
        latency_values: list[float] = []
        cost_values: list[Decimal] = []

        for event in events:
            metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
            confidence = metadata.get("confidence_score")
            if isinstance(confidence, (int, float)):
                confidence_values.append(float(confidence))
            latency = metadata.get("latency_ms")
            if isinstance(latency, (int, float)):
                latency_values.append(float(latency))
            if event.cost_usd is not None:
                cost_values.append(Decimal(event.cost_usd))

        input_tokens = sum(max(0, event.input_tokens or 0) for event in events)
        output_tokens = sum(max(0, event.output_tokens or 0) for event in events)
        estimated_cost = float(sum(cost_values)) if cost_values else None

        return BillingUsageSummary(
            range={"from": start.isoformat(), "to": end.isoformat()},
            documents_uploaded=len(documents),
            indexed_documents=sum(
                1 for document in documents if document.status == DocumentStatus.indexed.value
            ),
            storage_used_gb=_to_gb(_current_value_for_usage(usage_map, "storage_bytes")),
            total_chunks=sum(max(0, document.chunk_count or 0) for document in documents),
            questions_asked=sum(1 for event in events if event.event_type.startswith("chat.")),
            avg_confidence=(
                round(sum(confidence_values) / len(confidence_values), 4)
                if confidence_values
                else None
            ),
            avg_latency_ms=(
                round(sum(latency_values) / len(latency_values), 2) if latency_values else None
            ),
            input_tokens=input_tokens or None,
            output_tokens=output_tokens or None,
            estimated_llm_cost_usd=estimated_cost,
            evaluation_runs=sum(
                1 for event in events if _usage_event_matches(event.event_type, ("evaluation.",))
            ),
            agent_runs=sum(
                1 for event in events if _usage_event_matches(event.event_type, ("agent.",))
            ),
            connector_sync_jobs=sum(
                1
                for event in events
                if _usage_event_matches(event.event_type, ("connector.", "sync."))
            ),
            failed_indexing_jobs=sum(
                1
                for document in documents
                if document.status
                in {
                    DocumentStatus.failed.value,
                    DocumentStatus.extraction_failed.value,
                    DocumentStatus.unsupported.value,
                }
            ),
        )

    async def get_quotas(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[BillingQuota]:
        policy = await _quota_repo.get_policy(db_session, organization_id=organization_id)
        effective_limits = get_effective_limits(policy)
        usage_map = {
            usage.quota_type: usage
            for usage in await _quota_repo.list_usage(db_session, organization_id=organization_id)
        }
        _, members = await _load_org_context(db_session, organization_id)
        seat_limit = _limit_value(effective_limits.get("seats"), "hard_limit")

        quotas = [
            BillingQuota(
                resource="seats",
                label=_SEATS_LABEL,
                used=float(len(members)),
                limit=float(seat_limit) if seat_limit is not None else None,
                unit="seats",
            ),
            BillingQuota(
                resource="uploads",
                label=_UPLOADS_LABEL,
                used=float(_current_value_for_usage(usage_map, "uploads")),
                limit=float(
                    _limit_value(effective_limits.get("uploads"), "hard_limit")
                    if _limit_value(effective_limits.get("uploads"), "hard_limit") is not None
                    else 0
                )
                if _limit_value(effective_limits.get("uploads"), "hard_limit") is not None
                else None,
                unit="documents",
            ),
            BillingQuota(
                resource="storage_bytes",
                label=_STORAGE_LABEL,
                used=float(_to_gb(_current_value_for_usage(usage_map, "storage_bytes")) or 0.0),
                limit=_to_gb(_limit_value(effective_limits.get("storage_bytes"), "hard_limit")),
                unit="GB",
            ),
            BillingQuota(
                resource="questions",
                label=_QUESTIONS_LABEL,
                used=float(_current_value_for_usage(usage_map, "questions")),
                limit=float(_limit_value(effective_limits.get("questions"), "hard_limit"))
                if _limit_value(effective_limits.get("questions"), "hard_limit") is not None
                else None,
                unit="questions",
            ),
            BillingQuota(
                resource="tokens",
                label=_TOKENS_LABEL,
                used=float(_current_value_for_usage(usage_map, "tokens")),
                limit=float(_limit_value(effective_limits.get("tokens"), "hard_limit"))
                if _limit_value(effective_limits.get("tokens"), "hard_limit") is not None
                else None,
                unit="tokens",
            ),
            BillingQuota(
                resource="evaluations",
                label=_EVALUATIONS_LABEL,
                used=float(_current_value_for_usage(usage_map, "evaluations")),
                limit=float(_limit_value(effective_limits.get("evaluations"), "hard_limit"))
                if _limit_value(effective_limits.get("evaluations"), "hard_limit") is not None
                else None,
                unit="runs",
            ),
            BillingQuota(
                resource="agent_runs",
                label=_AGENTS_LABEL,
                used=float(_current_value_for_usage(usage_map, "agent_runs")),
                limit=float(_limit_value(effective_limits.get("agent_runs"), "hard_limit"))
                if _limit_value(effective_limits.get("agent_runs"), "hard_limit") is not None
                else None,
                unit="runs",
            ),
            BillingQuota(
                resource="connectors",
                label=_CONNECTORS_LABEL,
                used=float(_current_value_for_usage(usage_map, "connectors")),
                limit=float(_limit_value(effective_limits.get("connectors"), "hard_limit"))
                if _limit_value(effective_limits.get("connectors"), "hard_limit") is not None
                else None,
                unit="syncs",
            ),
        ]
        return quotas

    async def get_invoices(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[Invoice]:
        policy = await _quota_repo.get_policy(db_session, organization_id=organization_id)
        if policy is None:
            return []

        now = datetime.now(UTC)
        billing_month = _start_of_month(now)
        previous_month = _start_of_month(billing_month - timedelta(days=1))
        events = await _load_usage_events(db_session, organization_id, previous_month, now)
        current_total = sum(
            Decimal(event.cost_usd or 0) for event in events if event.created_at >= billing_month
        )
        previous_total = sum(
            Decimal(event.cost_usd or 0) for event in events if event.created_at < billing_month
        )

        invoices: list[Invoice] = []
        if previous_total > 0:
            invoices.append(
                Invoice(
                    id=f"inv-{previous_month.strftime('%Y%m')}",
                    date=previous_month,
                    amount_usd=float(previous_total),
                    status=InvoiceStatus.paid,
                    download_url=None,
                )
            )
        invoices.append(
            Invoice(
                id=f"inv-{billing_month.strftime('%Y%m')}",
                date=billing_month,
                amount_usd=float(current_total),
                status=InvoiceStatus.open,
                download_url=None,
            )
        )
        return invoices

    async def get_billing_contact(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> BillingContact:
        organization, members = await _load_org_context(db_session, organization_id)
        contact_user: User | None = None
        if members:
            billing_member = next(
                (member for member in members if member.role in {"owner", "billing_admin"}),
                None,
            )
            if billing_member is not None:
                user_result = await db_session.execute(
                    select(User).where(User.id == billing_member.user_id)
                )
                contact_user = user_result.scalar_one_or_none()

        return _sanitize_contact_payload(
            {
                "email": contact_user.email if contact_user is not None else None,
                "name": organization.name if organization is not None else None,
                "address_line1": None,
                "address_line2": None,
                "city": None,
                "state": None,
                "postal_code": None,
                "country": None,
                "tax_id": None,
                "payment_method_summary": "Managed securely in the billing portal",
                # These raw keys are intentionally ignored by the sanitizer.
                "card_number": "4242424242424242",
                "billing_provider_id": "prov_123",
            }
        )

    async def update_billing_contact(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        payload: BillingContactUpdateRequest,
    ) -> BillingContact:
        current = await self.get_billing_contact(db_session, organization_id=organization_id)
        merged = current.model_dump()
        for key, value in payload.model_dump(exclude_unset=True).items():
            if key == "payment_method_summary":
                continue
            merged[key] = value
        merged["payment_method_summary"] = current.payment_method_summary
        return BillingContact(**merged)

    async def create_portal_session(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> BillingPortalSession:
        _ = await self.get_plan_info(db_session, organization_id=organization_id)
        return BillingPortalSession(
            url=f"{str(settings.frontend_base_url).rstrip('/')}/settings?tab=billing",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
