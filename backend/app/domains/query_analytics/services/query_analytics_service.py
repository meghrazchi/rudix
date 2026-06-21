from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.query_analytics.repositories.query_analytics import QueryAnalyticsRepository
from app.domains.query_analytics.schemas.query_analytics import (
    ConvertKnowledgeGapResponse,
    DetectGapsResponse,
    FeedbackCategoryCount,
    KnowledgeGapListResponse,
    KnowledgeGapResponse,
    QueryAnalyticsDateRange,
    QueryAnalyticsSummaryResponse,
    QueryTrendPoint,
    QueryTrendsResponse,
)
from app.models.query_analytics import KnowledgeGap

_LOW_CONFIDENCE_THRESHOLD = 0.5


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


def _gap_to_response(gap: KnowledgeGap) -> KnowledgeGapResponse:
    return KnowledgeGapResponse(
        gap_id=str(gap.id),
        organization_id=str(gap.organization_id),
        gap_type=gap.gap_type,
        topic_label=gap.topic_label,
        description=gap.description,
        gap_source=gap.gap_source,
        occurrence_count=gap.occurrence_count,
        avg_confidence=gap.avg_confidence,
        example_query=gap.example_query,
        status=gap.status,
        remediation_json=gap.remediation_json,
        collection_id=str(gap.collection_id) if gap.collection_id else None,
        linked_document_id=str(gap.linked_document_id) if gap.linked_document_id else None,
        linked_eval_question_id=str(gap.linked_eval_question_id)
        if gap.linked_eval_question_id
        else None,
        converted_to=gap.converted_to,
        converted_at=gap.converted_at,
        reviewer_notes=gap.reviewer_notes,
        created_at=gap.created_at,
        updated_at=gap.updated_at,
    )


class QueryAnalyticsService:
    def __init__(self, repository: QueryAnalyticsRepository | None = None) -> None:
        self._repo = repository or QueryAnalyticsRepository()

    def _is_enabled(self) -> bool:
        return settings.feature_enable_query_analytics

    def _redact_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        if settings.query_analytics_redact_query_text:
            return "[redacted]"
        return text

    async def build_summary(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> QueryAnalyticsSummaryResponse:
        resolved_from, resolved_to = _range_bounds(from_date, to_date)
        date_range = QueryAnalyticsDateRange(from_date=resolved_from, to_date=resolved_to)
        now = datetime.now(tz=UTC)

        if not self._is_enabled():
            return QueryAnalyticsSummaryResponse(
                organization_id=str(organization_id),
                range=date_range,
                generated_at=now,
                enabled=False,
                disabled_reason="disabled_by_environment",
                total_queries=0,
                answered_queries=0,
                unanswered_queries=0,
                low_confidence_queries=0,
                negative_feedback_count=0,
                unanswered_rate=None,
                avg_confidence=None,
                negative_feedback_rate=None,
                top_feedback_categories=[],
                top_feedback_reasons=[],
            )

        from_dt, to_dt = _range_datetimes(resolved_from, resolved_to)

        total_queries = await self._repo.count_user_messages(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )
        messages = await self._repo.load_assistant_messages(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )
        feedback_items = await self._repo.load_feedback(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )

        unanswered = sum(1 for m in messages if m.confidence_score is None)
        low_confidence = sum(
            1
            for m in messages
            if m.confidence_score is not None and m.confidence_score < _LOW_CONFIDENCE_THRESHOLD
        )
        answered = len(messages) - unanswered

        confidence_values = [m.confidence_score for m in messages if m.confidence_score is not None]
        avg_confidence = (
            (sum(confidence_values) / len(confidence_values)) if confidence_values else None
        )

        negative = [f for f in feedback_items if f.rating == "down"]
        negative_count = len(negative)
        total_feedback = len(feedback_items)

        unanswered_rate = round(unanswered / len(messages), 4) if messages else None
        negative_rate = round(negative_count / total_feedback, 4) if total_feedback > 0 else None

        category_counts: dict[str, int] = defaultdict(int)
        reason_counts: dict[str, int] = defaultdict(int)
        for f in negative:
            if f.category:
                category_counts[f.category] += 1
            if f.reason:
                reason_counts[f.reason] += 1

        top_categories = sorted(
            [FeedbackCategoryCount(category=k, count=v) for k, v in category_counts.items()],
            key=lambda x: x.count,
            reverse=True,
        )[:10]
        top_reasons = sorted(
            [FeedbackCategoryCount(category=k, count=v) for k, v in reason_counts.items()],
            key=lambda x: x.count,
            reverse=True,
        )[:10]

        return QueryAnalyticsSummaryResponse(
            organization_id=str(organization_id),
            range=date_range,
            generated_at=now,
            enabled=True,
            disabled_reason=None,
            total_queries=total_queries,
            answered_queries=answered,
            unanswered_queries=unanswered,
            low_confidence_queries=low_confidence,
            negative_feedback_count=negative_count,
            unanswered_rate=unanswered_rate,
            avg_confidence=round(avg_confidence, 4) if avg_confidence is not None else None,
            negative_feedback_rate=negative_rate,
            top_feedback_categories=top_categories,
            top_feedback_reasons=top_reasons,
        )

    async def build_trends(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> QueryTrendsResponse:
        resolved_from, resolved_to = _range_bounds(from_date, to_date)
        from_dt, to_dt = _range_datetimes(resolved_from, resolved_to)
        now = datetime.now(tz=UTC)

        messages = await self._repo.load_assistant_messages(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )
        feedback_items = await self._repo.load_feedback(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )

        # Build per-day buckets
        per_day_total: dict[date, int] = defaultdict(int)
        per_day_unanswered: dict[date, int] = defaultdict(int)
        per_day_low_conf: dict[date, int] = defaultdict(int)
        per_day_conf_sum: dict[date, float] = defaultdict(float)
        per_day_conf_count: dict[date, int] = defaultdict(int)
        per_day_neg_feedback: dict[date, int] = defaultdict(int)

        for msg in messages:
            day = msg.created_at.date() if msg.created_at else resolved_from
            per_day_total[day] += 1
            if msg.confidence_score is None:
                per_day_unanswered[day] += 1
            elif msg.confidence_score < _LOW_CONFIDENCE_THRESHOLD:
                per_day_low_conf[day] += 1
            if msg.confidence_score is not None:
                per_day_conf_sum[day] += msg.confidence_score
                per_day_conf_count[day] += 1

        for fb in feedback_items:
            if fb.rating == "down":
                day = fb.created_at.date() if fb.created_at else resolved_from
                per_day_neg_feedback[day] += 1

        # Enumerate every day in range
        points: list[QueryTrendPoint] = []
        current = resolved_from
        while current <= resolved_to:
            count = per_day_conf_count.get(current, 0)
            avg_conf = (per_day_conf_sum[current] / count) if count > 0 else None
            points.append(
                QueryTrendPoint(
                    date=current,
                    total_queries=per_day_total.get(current, 0),
                    unanswered=per_day_unanswered.get(current, 0),
                    low_confidence=per_day_low_conf.get(current, 0),
                    negative_feedback=per_day_neg_feedback.get(current, 0),
                    avg_confidence=round(avg_conf, 4) if avg_conf is not None else None,
                )
            )
            current += timedelta(days=1)

        return QueryTrendsResponse(
            organization_id=str(organization_id),
            range=QueryAnalyticsDateRange(from_date=resolved_from, to_date=resolved_to),
            generated_at=now,
            points=points,
        )

    # ── Knowledge gaps ─────────────────────────────────────────────────────────

    async def create_gap(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        gap_type: str,
        topic_label: str,
        description: str | None = None,
        occurrence_count: int = 1,
        avg_confidence: float | None = None,
        example_query: str | None = None,
        collection_id: UUID | None = None,
        gap_source: str = "admin",
    ) -> KnowledgeGapResponse:
        redacted_example = self._redact_text(example_query)
        gap = await self._repo.create_gap(
            session,
            organization_id=organization_id,
            gap_type=gap_type,
            topic_label=topic_label,
            description=description,
            gap_source=gap_source,
            occurrence_count=occurrence_count,
            avg_confidence=avg_confidence,
            example_query=redacted_example,
            collection_id=collection_id,
        )
        return _gap_to_response(gap)

    async def list_gaps(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        gap_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> KnowledgeGapListResponse:
        items, total = await self._repo.list_gaps(
            session,
            organization_id=organization_id,
            status=status,
            gap_type=gap_type,
            limit=limit,
            offset=offset,
        )
        return KnowledgeGapListResponse(
            items=[_gap_to_response(g) for g in items],
            total=total,
        )

    async def update_gap(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        gap_id: UUID,
        status: str | None = None,
        reviewer_notes: str | None = None,
        linked_document_id: UUID | None = None,
        description: str | None = None,
    ) -> KnowledgeGapResponse | None:
        gap = await self._repo.get_gap(session, organization_id=organization_id, gap_id=gap_id)
        if gap is None:
            return None
        if status is not None:
            gap.status = status
        if reviewer_notes is not None:
            gap.reviewer_notes = reviewer_notes
        if linked_document_id is not None:
            gap.linked_document_id = linked_document_id
        if description is not None:
            gap.description = description
        await session.flush()
        return _gap_to_response(gap)

    async def convert_gap(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        gap_id: UUID,
        target: str,
        notes: str | None = None,
    ) -> ConvertKnowledgeGapResponse | None:
        gap = await self._repo.get_gap(session, organization_id=organization_id, gap_id=gap_id)
        if gap is None:
            return None

        now = datetime.now(tz=UTC)
        gap.converted_to = target
        gap.converted_at = now
        gap.status = "in_review"
        if notes:
            gap.reviewer_notes = notes

        await session.flush()
        return ConvertKnowledgeGapResponse(
            gap_id=str(gap.id),
            converted_to=target,
            converted_at=now,
            linked_eval_question_id=str(gap.linked_eval_question_id)
            if gap.linked_eval_question_id
            else None,
        )

    async def detect_gaps(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        low_confidence_threshold: float = 0.5,
        min_occurrences: int = 3,
    ) -> DetectGapsResponse:
        resolved_from, resolved_to = _range_bounds(from_date, to_date)
        from_dt, to_dt = _range_datetimes(resolved_from, resolved_to)

        messages = await self._repo.load_assistant_messages(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )
        feedback_items = await self._repo.load_feedback(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )

        # Detect low-confidence pattern
        low_conf_messages = [
            m
            for m in messages
            if m.confidence_score is not None and m.confidence_score < low_confidence_threshold
        ]
        no_answer_messages = [m for m in messages if m.confidence_score is None]

        # Detect bad feedback by category
        category_counts: dict[str, int] = defaultdict(int)
        for f in feedback_items:
            if f.rating == "down" and f.category:
                category_counts[f.category] += 1

        detected = 0
        created = 0
        skipped = 0

        # Create a low_confidence gap if enough occurrences
        if len(low_conf_messages) >= min_occurrences:
            detected += 1
            topic = "Low-confidence answers"
            exists = await self._repo.exists_similar_gap(
                session,
                organization_id=organization_id,
                gap_type="low_confidence",
                topic_label=topic,
            )
            if exists:
                skipped += 1
            else:
                conf_vals = [
                    m.confidence_score for m in low_conf_messages if m.confidence_score is not None
                ]
                avg_conf = sum(conf_vals) / len(conf_vals) if conf_vals else None
                example = (
                    self._redact_text(low_conf_messages[0].content[:200])
                    if low_conf_messages
                    else None
                )
                await self._repo.create_gap(
                    session,
                    organization_id=organization_id,
                    gap_type="low_confidence",
                    topic_label=topic,
                    description=f"{len(low_conf_messages)} answers below {low_confidence_threshold:.0%} confidence in period",
                    gap_source="low_confidence_analysis",
                    occurrence_count=len(low_conf_messages),
                    avg_confidence=avg_conf,
                    example_query=example,
                )
                created += 1

        # Create no_answer gap
        if len(no_answer_messages) >= min_occurrences:
            detected += 1
            topic = "Unanswered questions"
            exists = await self._repo.exists_similar_gap(
                session,
                organization_id=organization_id,
                gap_type="no_answer",
                topic_label=topic,
            )
            if exists:
                skipped += 1
            else:
                await self._repo.create_gap(
                    session,
                    organization_id=organization_id,
                    gap_type="no_answer",
                    topic_label=topic,
                    description=f"{len(no_answer_messages)} queries returned no confident answer in period",
                    gap_source="no_answer_analysis",
                    occurrence_count=len(no_answer_messages),
                )
                created += 1

        # Create feedback-derived gaps per category
        for cat, count in category_counts.items():
            if count >= min_occurrences:
                detected += 1
                topic = cat.replace("_", " ").capitalize()
                exists = await self._repo.exists_similar_gap(
                    session,
                    organization_id=organization_id,
                    gap_type="bad_feedback",
                    topic_label=topic,
                )
                if exists:
                    skipped += 1
                else:
                    await self._repo.create_gap(
                        session,
                        organization_id=organization_id,
                        gap_type="bad_feedback",
                        topic_label=topic,
                        description=f"{count} negative feedback items with category '{cat}' in period",
                        gap_source="feedback_analysis",
                        occurrence_count=count,
                    )
                    created += 1

        return DetectGapsResponse(detected=detected, created=created, skipped_duplicates=skipped)

    # ── CSV export ─────────────────────────────────────────────────────────────

    async def build_export_csv(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> str:
        trends = await self.build_trends(
            session, organization_id=organization_id, from_date=from_date, to_date=to_date
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "date",
                "total_queries",
                "unanswered",
                "low_confidence",
                "negative_feedback",
                "avg_confidence",
            ]
        )
        for point in trends.points:
            writer.writerow(
                [
                    point.date.isoformat(),
                    point.total_queries,
                    point.unanswered,
                    point.low_confidence,
                    point.negative_feedback,
                    f"{point.avg_confidence:.4f}" if point.avg_confidence is not None else "",
                ]
            )
        return output.getvalue()
