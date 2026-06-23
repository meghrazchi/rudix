import csv
import io
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FeedbackReviewStatus
from app.models.feedback_review_item import FeedbackReviewItem


class FeedbackReviewRepository:
    async def get_or_create_review_item(
        self,
        session: AsyncSession,
        *,
        feedback_id: UUID,
        organization_id: UUID,
        reviewer_id: UUID,
        severity: str,
        reviewer_notes: str | None,
    ) -> tuple[FeedbackReviewItem, bool]:
        existing = await session.execute(
            select(FeedbackReviewItem).where(
                FeedbackReviewItem.feedback_id == feedback_id,
                FeedbackReviewItem.organization_id == organization_id,
            )
        )
        item = existing.scalar_one_or_none()
        if item is not None:
            return item, False

        item = FeedbackReviewItem(
            feedback_id=feedback_id,
            organization_id=organization_id,
            status=FeedbackReviewStatus.triaged.value,
            severity=severity,
            reviewer_id=reviewer_id,
            reviewer_notes=reviewer_notes,
        )
        session.add(item)
        await session.flush()
        await session.refresh(item)
        return item, True

    async def get_review_item(
        self,
        session: AsyncSession,
        *,
        review_id: UUID,
        organization_id: UUID,
    ) -> FeedbackReviewItem | None:
        result = await session.execute(
            select(FeedbackReviewItem).where(
                FeedbackReviewItem.id == review_id,
                FeedbackReviewItem.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_review_item_by_feedback(
        self,
        session: AsyncSession,
        *,
        feedback_id: UUID,
        organization_id: UUID,
    ) -> FeedbackReviewItem | None:
        result = await session.execute(
            select(FeedbackReviewItem).where(
                FeedbackReviewItem.feedback_id == feedback_id,
                FeedbackReviewItem.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_review_items(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        severity: str | None = None,
        rating: str | None = None,
        reason: str | None = None,
        reviewer_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[FeedbackReviewItem], int]:
        from app.models.message_feedback import MessageFeedback

        base_query = select(FeedbackReviewItem).where(
            FeedbackReviewItem.organization_id == organization_id
        )

        if status:
            base_query = base_query.where(FeedbackReviewItem.status == status)
        if severity:
            base_query = base_query.where(FeedbackReviewItem.severity == severity)
        if reviewer_id:
            base_query = base_query.where(FeedbackReviewItem.reviewer_id == reviewer_id)

        if rating or reason:
            base_query = base_query.join(
                MessageFeedback, FeedbackReviewItem.feedback_id == MessageFeedback.id
            )
            if rating:
                base_query = base_query.where(MessageFeedback.rating == rating)
            if reason:
                base_query = base_query.where(MessageFeedback.reason == reason)

        count_result = await session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        items_result = await session.execute(
            base_query.order_by(FeedbackReviewItem.created_at.desc()).limit(limit).offset(offset)
        )
        return list(items_result.scalars().all()), total

    async def update_review_item(
        self,
        session: AsyncSession,
        *,
        review_id: UUID,
        organization_id: UUID,
        reviewer_id: UUID,
        status: str | None = None,
        severity: str | None = None,
        reviewer_notes: str | None = None,
        linked_eval_question_id: UUID | None = None,
        linked_document_id: UUID | None = None,
        clear_linked_eval: bool = False,
        clear_linked_document: bool = False,
    ) -> FeedbackReviewItem | None:
        item = await self.get_review_item(
            session, review_id=review_id, organization_id=organization_id
        )
        if item is None:
            return None

        if status is not None:
            item.status = status
            _terminal = {
                FeedbackReviewStatus.fixed,
                FeedbackReviewStatus.rejected,
                FeedbackReviewStatus.duplicate,
            }
            if FeedbackReviewStatus(status) in _terminal and item.resolved_at is None:
                item.resolved_at = datetime.now(tz=UTC)
            elif (
                FeedbackReviewStatus(status) not in _terminal
                and status != FeedbackReviewStatus.eval_created
            ):
                item.resolved_at = None

        if severity is not None:
            item.severity = severity

        if reviewer_notes is not None:
            item.reviewer_notes = reviewer_notes

        if linked_eval_question_id is not None:
            item.linked_eval_question_id = linked_eval_question_id
        elif clear_linked_eval:
            item.linked_eval_question_id = None

        if linked_document_id is not None:
            item.linked_document_id = linked_document_id
        elif clear_linked_document:
            item.linked_document_id = None

        item.reviewer_id = reviewer_id
        session.add(item)
        await session.flush()
        await session.refresh(item)
        return item

    async def get_feedback_metrics(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        days: int = 30,
    ) -> dict:
        from datetime import timedelta

        from app.models.chat import ChatMessage
        from app.models.message_feedback import MessageFeedback

        since = datetime.now(tz=UTC) - timedelta(days=days)

        fb_result = await session.execute(
            select(
                MessageFeedback.category,
                func.count(MessageFeedback.id).label("count"),
            )
            .where(
                MessageFeedback.organization_id == organization_id,
                MessageFeedback.created_at >= since,
            )
            .group_by(MessageFeedback.category)
            .order_by(func.count(MessageFeedback.id).desc())
        )
        category_rows = fb_result.all()

        # Trust score correlation: avg confidence_score per category
        score_result = await session.execute(
            select(
                MessageFeedback.category,
                func.avg(ChatMessage.confidence_score).label("avg_confidence"),
                func.count(MessageFeedback.id).label("count"),
            )
            .join(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .where(
                MessageFeedback.organization_id == organization_id,
                MessageFeedback.created_at >= since,
                ChatMessage.confidence_score.is_not(None),
            )
            .group_by(MessageFeedback.category)
        )
        score_rows = score_result.all()
        score_by_category = {r.category: round(float(r.avg_confidence), 3) for r in score_rows}

        total = sum(r.count for r in category_rows)
        categories = [
            {
                "category": r.category or "uncategorized",
                "count": r.count,
                "avg_confidence_score": score_by_category.get(r.category),
            }
            for r in category_rows
        ]
        return {
            "period_days": days,
            "total_feedback": total,
            "categories": categories,
        }

    async def build_csv_export(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        severity: str | None = None,
        rating: str | None = None,
        reason: str | None = None,
    ) -> str:
        from app.models.message_feedback import MessageFeedback

        items, _ = await self.list_review_items(
            session,
            organization_id=organization_id,
            status=status,
            severity=severity,
            rating=rating,
            reason=reason,
            limit=10_000,
            offset=0,
        )

        feedback_ids = [item.feedback_id for item in items]
        fb_map: dict[UUID, MessageFeedback] = {}
        if feedback_ids:
            fb_result = await session.execute(
                select(MessageFeedback).where(MessageFeedback.id.in_(feedback_ids))
            )
            for fb in fb_result.scalars().all():
                fb_map[fb.id] = fb

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "review_id",
                "feedback_id",
                "status",
                "severity",
                "rating",
                "reason",
                "comment",
                "reviewer_notes",
                "linked_eval_question_id",
                "linked_document_id",
                "created_at",
                "resolved_at",
            ],
        )
        writer.writeheader()
        for item in items:
            fb = fb_map.get(item.feedback_id)
            writer.writerow(
                {
                    "review_id": str(item.id),
                    "feedback_id": str(item.feedback_id),
                    "status": item.status,
                    "severity": item.severity,
                    "rating": fb.rating if fb else "",
                    "reason": fb.reason if fb else "",
                    "comment": fb.comment if fb else "",
                    "reviewer_notes": item.reviewer_notes or "",
                    "linked_eval_question_id": str(item.linked_eval_question_id)
                    if item.linked_eval_question_id
                    else "",
                    "linked_document_id": str(item.linked_document_id)
                    if item.linked_document_id
                    else "",
                    "created_at": item.created_at.isoformat(),
                    "resolved_at": item.resolved_at.isoformat() if item.resolved_at else "",
                }
            )
        return output.getvalue()
