from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.analytics.schemas.analytics import (
    ACTIVATION_EVENT_NAMES,
    AnalyticsActivationSummaryResponse,
    AnalyticsDateRange,
    AnalyticsEventIngestRequest,
    AnalyticsSummaryResponse,
)
from app.models.organization import Organization
from app.models.usage import UsageEvent


@dataclass(frozen=True)
class AnalyticsPolicy:
    enabled: bool
    disabled_reason: str | None = None


def _range_bounds(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    today = datetime.now(tz=UTC).date()
    resolved_to = to_date or today
    resolved_from = from_date or resolved_to - timedelta(days=29)
    if resolved_from > resolved_to:
        raise ValueError("from must be less than or equal to to")
    return resolved_from, resolved_to


def _range_datetimes(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(from_date, time.min, tzinfo=UTC),
        datetime.combine(to_date, time.max, tzinfo=UTC),
    )


def _event_type(event_name: str, schema_version: int) -> str:
    return f"analytics.v{schema_version}.{event_name}"


def _metadata_from_request(request: AnalyticsEventIngestRequest) -> dict[str, object]:
    metadata: dict[str, object] = {
        "event_name": request.event_name,
        "schema_version": request.schema_version,
        "surface": request.surface,
    }
    for key in (
        "route",
        "page_key",
        "feature_area",
        "entity_id",
        "entity_type",
        "status",
        "method",
        "count",
        "citation_count",
        "has_citations",
        "locale",
        "source",
        "dedupe_key",
    ):
        value = getattr(request, key)
        if value is not None:
            metadata[key] = value
    return metadata


async def _load_organization(
    session: AsyncSession,
    organization_id: UUID,
) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.id == organization_id))
    return result.scalar_one_or_none()


class AnalyticsService:
    def __init__(self, usage_repository: UsageRepository | None = None) -> None:
        self._usage_repository = usage_repository or UsageRepository()

    async def resolve_policy(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> AnalyticsPolicy:
        if not settings.feature_enable_product_analytics:
            return AnalyticsPolicy(enabled=False, disabled_reason="disabled_by_environment")

        organization = await _load_organization(session, organization_id)
        if organization is None:
            return AnalyticsPolicy(enabled=False, disabled_reason="organization_not_found")
        if not organization.analytics_enabled:
            return AnalyticsPolicy(enabled=False, disabled_reason="disabled_by_organization")
        return AnalyticsPolicy(enabled=True)

    async def record_event(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        request: AnalyticsEventIngestRequest,
        request_id: str | None = None,
    ) -> tuple[bool, bool]:
        policy = await self.resolve_policy(session, organization_id=organization_id)
        if not policy.enabled:
            return False, False

        event_type = _event_type(request.event_name, request.schema_version)
        deduped = False
        dedupe_key = request.dedupe_key.strip() if request.dedupe_key else None

        if request.event_name in ACTIVATION_EVENT_NAMES:
            existing = await session.execute(
                select(UsageEvent.id).where(
                    UsageEvent.organization_id == organization_id,
                    UsageEvent.user_id == user_id,
                    UsageEvent.event_type == event_type,
                )
            )
            if existing.first() is not None:
                return True, True
        elif dedupe_key:
            existing = await session.execute(
                select(UsageEvent.id).where(
                    UsageEvent.organization_id == organization_id,
                    UsageEvent.user_id == user_id,
                    UsageEvent.event_type == event_type,
                    func.coalesce(UsageEvent.metadata_json["dedupe_key"].as_string(), "")
                    == dedupe_key,
                )
            )
            if existing.first() is not None:
                return True, True

        await self._usage_repository.create_usage_event(
            session,
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type,
            metadata=_metadata_from_request(request),
            request_id=request_id,
        )
        return True, deduped

    async def build_summary(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> AnalyticsSummaryResponse:
        resolved_from, resolved_to = _range_bounds(from_date, to_date)

        policy = await self.resolve_policy(session, organization_id=organization_id)
        if not policy.enabled:
            return AnalyticsSummaryResponse(
                organization_id=str(organization_id),
                range=AnalyticsDateRange.model_validate({"from": resolved_from, "to": resolved_to}),
                generated_at=datetime.now(tz=UTC),
                enabled=False,
                disabled_reason=policy.disabled_reason,
                total_events=0,
                active_users=0,
                activation=AnalyticsActivationSummaryResponse(
                    signup_completed=0,
                    organization_created=0,
                    first_upload=0,
                    first_indexed_document=0,
                    first_question=0,
                    first_cited_answer=0,
                    funnel_completion_rate=None,
                ),
                feature_usage={},
                page_usage={},
                event_counts={},
            )

        from_created_at, to_created_at = _range_datetimes(resolved_from, resolved_to)
        events = await self._usage_repository.list_usage_events_filtered(
            session,
            organization_id=organization_id,
            from_created_at=from_created_at,
            to_created_at=to_created_at,
            event_type_prefix="analytics.v1.",
        )

        total_events = len(events)
        active_users = len({str(event.user_id) for event in events if event.user_id is not None})
        event_counts: dict[str, int] = defaultdict(int)
        feature_usage: dict[str, int] = defaultdict(int)
        page_usage: dict[str, int] = defaultdict(int)
        activation_counts = {name: 0 for name in ACTIVATION_EVENT_NAMES}

        for event in events:
            metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
            event_name = metadata.get("event_name")
            if isinstance(event_name, str):
                event_counts[event_name] += 1
                if event_name in activation_counts:
                    activation_counts[event_name] += 1

            feature_area = metadata.get("feature_area")
            if isinstance(feature_area, str) and feature_area:
                feature_usage[feature_area] += 1

            page_key = metadata.get("page_key")
            if isinstance(page_key, str) and page_key:
                page_usage[page_key] += 1

        first_upload = activation_counts["activation.first_upload"]
        first_indexed = activation_counts["activation.first_indexed_document"]
        first_question = activation_counts["activation.first_question"]
        first_cited = activation_counts["activation.first_cited_answer"]
        signup_completed = activation_counts["activation.signup_completed"]
        organization_created = activation_counts["activation.organization_created"]
        activation_rate = round(first_cited / first_question, 4) if first_question > 0 else None

        return AnalyticsSummaryResponse(
            organization_id=str(organization_id),
            range=AnalyticsDateRange.model_validate({"from": resolved_from, "to": resolved_to}),
            generated_at=datetime.now(tz=UTC),
            enabled=policy.enabled,
            disabled_reason=policy.disabled_reason,
            total_events=total_events,
            active_users=active_users,
            activation=AnalyticsActivationSummaryResponse(
                signup_completed=signup_completed,
                organization_created=organization_created,
                first_upload=first_upload,
                first_indexed_document=first_indexed,
                first_question=first_question,
                first_cited_answer=first_cited,
                funnel_completion_rate=activation_rate,
            ),
            feature_usage=dict(feature_usage),
            page_usage=dict(page_usage),
            event_counts=dict(event_counts),
        )
