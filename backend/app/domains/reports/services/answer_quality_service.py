from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import ceil
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.collections.repositories.collections import CollectionRepository
from app.domains.reports.schemas.reports import (
    AnswerQualityCollectionPoint,
    AnswerQualityDetailResponse,
    AnswerQualityDistributionPoint,
    AnswerQualityFeedbackPoint,
    AnswerQualityLevel,
    AnswerQualityMetrics,
    AnswerQualityReportResponse,
    AnswerQualityRow,
    AnswerQualitySource,
    AnswerQualityTrendPoint,
    ReportPage,
)
from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.collection import Collection, CollectionDocument
from app.models.document import Document
from app.models.feedback_review_item import FeedbackReviewItem
from app.models.message_feedback import MessageFeedback
from app.models.usage import UsageEvent
from app.models.user import User

_TRUST_EVENT_TYPE = "trust.answer_metrics"
_LEVELS = ("high", "medium", "low", "warning", "not_found")


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _level(meta: dict[str, Any]) -> AnswerQualityLevel:
    value = meta.get("trust_level")
    return cast(AnswerQualityLevel, value) if value in _LEVELS else "low"


def _warnings(meta: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key, label in (
        ("citation_validation_failed", "missing_citations"),
        ("stale_source_warning", "stale_source"),
        ("conflict_detected", "source_conflict"),
        ("ocr_warning", "ocr_quality"),
        ("extraction_warning", "extraction_quality"),
        ("processing_warning", "source_processing"),
        ("evidence_quality_warning", "evidence_quality"),
    ):
        if meta.get(key):
            values.append(label)
    if int(meta.get("unsupported_claims_removed") or 0) > 0:
        values.append("unsupported_claims_removed")
    return values


class AnswerQualityService:
    def __init__(self) -> None:
        self._collections = CollectionRepository()

    async def _accessible_collection_ids(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> set[UUID]:
        rows = await self._collections.list(
            session,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=user_roles,
            limit=10_000,
            offset=0,
        )
        return {row.id for row in rows}

    async def _source_map(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        message_ids: list[UUID],
        accessible_collection_ids: set[UUID],
    ) -> tuple[dict[UUID, list[AnswerQualitySource]], set[UUID]]:
        if not message_ids:
            return {}, set()
        rows = (
            await session.execute(
                select(Citation, Document, CollectionDocument, Collection)
                .join(Document, Document.id == Citation.document_id)
                .outerjoin(CollectionDocument, CollectionDocument.document_id == Document.id)
                .outerjoin(Collection, Collection.id == CollectionDocument.collection_id)
                .where(
                    Citation.chat_message_id.in_(message_ids),
                    Document.organization_id == organization_id,
                )
            )
        ).all()
        by_message: dict[UUID, list[AnswerQualitySource]] = defaultdict(list)
        restricted_messages: set[UUID] = set()
        document_collections: dict[tuple[UUID, UUID], set[UUID]] = defaultdict(set)
        for citation, _document, membership, _collection in rows:
            if membership is not None:
                document_collections[(citation.chat_message_id, citation.document_id)].add(
                    membership.collection_id
                )
        for citation, document, membership, collection in rows:
            memberships = document_collections[(citation.chat_message_id, citation.document_id)]
            if memberships and not memberships.intersection(accessible_collection_ids):
                restricted_messages.add(citation.chat_message_id)
                continue
            source = AnswerQualitySource(
                document_id=document.id,
                document_name=document.filename,
                collection_id=membership.collection_id if membership is not None else None,
                collection_name=collection.name if collection is not None else None,
                page_number=citation.page_number,
            )
            if source not in by_message[citation.chat_message_id]:
                by_message[citation.chat_message_id].append(source)
        return by_message, restricted_messages

    async def _question_map(
        self, session: AsyncSession, messages: list[ChatMessage]
    ) -> dict[UUID, str]:
        session_ids = {message.chat_session_id for message in messages}
        if not session_ids:
            return {}
        user_messages = list(
            (
                await session.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.chat_session_id.in_(session_ids),
                        ChatMessage.role == "user",
                    )
                    .order_by(ChatMessage.created_at)
                )
            )
            .scalars()
            .all()
        )
        result: dict[UUID, str] = {}
        for answer in messages:
            previous = [
                item
                for item in user_messages
                if item.chat_session_id == answer.chat_session_id
                and item.created_at <= answer.created_at
            ]
            result[answer.id] = previous[-1].content if previous else "Question unavailable"
        return result

    async def build_report(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        viewer_user_id: UUID,
        viewer_roles: list[str],
        from_at: datetime,
        to_at: datetime,
        collection_id: UUID | None,
        source_id: UUID | None,
        user_id: UUID | None,
        warning: str | None,
        confidence_level: str | None,
        page: int,
        page_size: int,
        sort: str,
        direction: str,
    ) -> AnswerQualityReportResponse:
        stmt = select(UsageEvent).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.event_type == _TRUST_EVENT_TYPE,
            UsageEvent.created_at >= from_at,
            UsageEvent.created_at <= to_at,
        )
        if user_id is not None:
            stmt = stmt.where(UsageEvent.user_id == user_id)
        events = list((await session.execute(stmt)).scalars().all())
        event_by_message: dict[UUID, UsageEvent] = {}
        for event in events:
            raw_id = _dict(event.metadata_json).get("message_id")
            try:
                event_by_message[UUID(str(raw_id))] = event
            except (TypeError, ValueError):
                continue
        message_ids = list(event_by_message)
        messages = (
            list(
                (
                    await session.execute(
                        select(ChatMessage)
                        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
                        .where(
                            ChatMessage.id.in_(message_ids),
                            ChatSession.organization_id == organization_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if message_ids
            else []
        )
        accessible = await self._accessible_collection_ids(
            session,
            organization_id=organization_id,
            user_id=viewer_user_id,
            user_roles=viewer_roles,
        )
        sources, restricted = await self._source_map(
            session,
            organization_id=organization_id,
            message_ids=[message.id for message in messages],
            accessible_collection_ids=accessible,
        )
        messages = [message for message in messages if message.id not in restricted]
        questions = await self._question_map(session, messages)
        users = (
            {
                row.id: row
                for row in (
                    await session.execute(
                        select(User).where(
                            User.id.in_(
                                {
                                    event_by_message[m.id].user_id
                                    for m in messages
                                    if event_by_message[m.id].user_id is not None
                                }
                            )
                        )
                    )
                )
                .scalars()
                .all()
            }
            if messages
            else {}
        )
        feedback_rows = (
            list(
                (
                    await session.execute(
                        select(MessageFeedback, FeedbackReviewItem)
                        .outerjoin(
                            FeedbackReviewItem, FeedbackReviewItem.feedback_id == MessageFeedback.id
                        )
                        .where(
                            MessageFeedback.organization_id == organization_id,
                            MessageFeedback.message_id.in_([message.id for message in messages]),
                        )
                    )
                ).all()
            )
            if messages
            else []
        )
        feedback_by_message = {
            feedback.message_id: (feedback, review) for feedback, review in feedback_rows
        }

        records: list[tuple[AnswerQualityRow, dict[str, Any]]] = []
        for message in messages:
            event = event_by_message[message.id]
            meta = _dict(event.metadata_json)
            message_sources = sources.get(message.id, [])
            if collection_id is not None and not any(
                s.collection_id == collection_id for s in message_sources
            ):
                continue
            if source_id is not None and not any(
                s.document_id == source_id for s in message_sources
            ):
                continue
            warnings = _warnings(meta)
            level = _level(meta)
            if warning and warning != "all" and warning not in warnings:
                continue
            if confidence_level and confidence_level != "all" and level != confidence_level:
                continue
            first_source = message_sources[0] if message_sources else None
            user = users.get(event.user_id) if event.user_id is not None else None
            feedback, review = feedback_by_message.get(message.id, (None, None))
            records.append(
                (
                    AnswerQualityRow(
                        message_id=message.id,
                        question=questions.get(message.id, "Question unavailable"),
                        user_id=event.user_id or viewer_user_id,
                        user_name=(user.display_name or user.email)
                        if user is not None
                        else "Unknown user",
                        collection_id=first_source.collection_id if first_source else None,
                        collection_name=first_source.collection_name if first_source else None,
                        source_id=first_source.document_id if first_source else None,
                        source_name=first_source.document_name if first_source else None,
                        confidence=_float(meta.get("confidence_score")),
                        confidence_level=level,
                        citation_support_score=_float(meta.get("citation_support_score")),
                        warnings=warnings,
                        feedback_status=review.status
                        if review is not None
                        else ("received" if feedback is not None else None),
                        created_at=event.created_at,
                    ),
                    meta,
                )
            )

        reverse = direction == "desc"
        key = {
            "created_at": lambda item: item[0].created_at.timestamp(),
            "confidence": lambda item: item[0].confidence if item[0].confidence is not None else -1,
            "citation_support": lambda item: (
                item[0].citation_support_score if item[0].citation_support_score is not None else -1
            ),
        }[sort]
        records.sort(key=key, reverse=reverse)
        rows = [item[0] for item in records]
        metas = [item[1] for item in records]
        total = len(rows)
        confidence_values = [row.confidence for row in rows if row.confidence is not None]
        support_values = [
            row.citation_support_score for row in rows if row.citation_support_score is not None
        ]
        distribution = Counter(row.confidence_level for row in rows)
        by_day: dict[str, list[AnswerQualityRow]] = defaultdict(list)
        for row in rows:
            by_day[row.created_at.date().isoformat()].append(row)
        collection_counts = Counter(
            (row.collection_id, row.collection_name or "No collection")
            for row in rows
            if row.confidence_level in {"low", "warning", "not_found"}
        )
        feedback_categories = Counter(
            feedback.category or feedback.reason or "uncategorized"
            for feedback, _review in feedback_rows
            if feedback.rating == "down" and feedback.message_id in {row.message_id for row in rows}
        )
        start = (page - 1) * page_size
        return AnswerQualityReportResponse(
            metrics=AnswerQualityMetrics(
                total_questions=total,
                average_confidence=round(sum(confidence_values) / len(confidence_values), 4)
                if confidence_values
                else None,
                average_citation_support=round(sum(support_values) / len(support_values), 4)
                if support_values
                else None,
                not_found_count=sum(meta.get("not_found") is True for meta in metas),
                missing_citations_count=sum(
                    meta.get("citation_validation_failed") is True for meta in metas
                ),
                stale_source_warning_count=sum(
                    meta.get("stale_source_warning") is True for meta in metas
                ),
                source_conflict_count=sum(meta.get("conflict_detected") is True for meta in metas),
                unsupported_claims_removed=sum(
                    int(meta.get("unsupported_claims_removed") or 0) for meta in metas
                ),
            ),
            confidence_distribution=[
                AnswerQualityDistributionPoint(
                    level=cast(AnswerQualityLevel, level),
                    count=distribution[cast(AnswerQualityLevel, level)],
                )
                for level in _LEVELS
            ],
            trends=[
                AnswerQualityTrendPoint(
                    date=day,
                    answer_count=len(day_rows),
                    average_confidence=self._average([row.confidence for row in day_rows]),
                    average_citation_support=self._average(
                        [row.citation_support_score for row in day_rows]
                    ),
                    not_found_count=sum(row.confidence_level == "not_found" for row in day_rows),
                )
                for day, day_rows in sorted(by_day.items())
            ],
            low_confidence_by_collection=[
                AnswerQualityCollectionPoint(
                    collection_id=cid, collection_name=name, low_confidence_count=count
                )
                for (cid, name), count in collection_counts.most_common()
            ],
            bad_feedback_categories=[
                AnswerQualityFeedbackPoint(category=category, count=count)
                for category, count in feedback_categories.most_common()
            ],
            items=rows[start : start + page_size],
            pagination=ReportPage(
                page=page,
                page_size=page_size,
                total=total,
                pages=ceil(total / page_size) if total else 0,
            ),
        )

    async def get_detail(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        viewer_user_id: UUID,
        viewer_roles: list[str],
        message_id: UUID,
    ) -> AnswerQualityDetailResponse | None:
        candidate_events = list(
            (
                await session.execute(
                    select(UsageEvent).where(
                        UsageEvent.organization_id == organization_id,
                        UsageEvent.event_type == _TRUST_EVENT_TYPE,
                    )
                )
            )
            .scalars()
            .all()
        )
        event = next(
            (
                item
                for item in candidate_events
                if str(_dict(item.metadata_json).get("message_id")) == str(message_id)
            ),
            None,
        )
        if event is None:
            return None
        report = await self.build_report(
            session,
            organization_id=organization_id,
            viewer_user_id=viewer_user_id,
            viewer_roles=viewer_roles,
            from_at=event.created_at - timedelta(seconds=1),
            to_at=event.created_at + timedelta(seconds=1),
            collection_id=None,
            source_id=None,
            user_id=None,
            warning=None,
            confidence_level=None,
            page=1,
            page_size=200,
            sort="created_at",
            direction="desc",
        )
        row = next((item for item in report.items if item.message_id == message_id), None)
        if row is None:
            return None
        message = await session.scalar(select(ChatMessage).where(ChatMessage.id == message_id))
        if message is None:
            return None
        accessible = await self._accessible_collection_ids(
            session,
            organization_id=organization_id,
            user_id=viewer_user_id,
            user_roles=viewer_roles,
        )
        sources, restricted = await self._source_map(
            session,
            organization_id=organization_id,
            message_ids=[message_id],
            accessible_collection_ids=accessible,
        )
        if message_id in restricted:
            return None
        feedback_row = (
            await session.execute(
                select(MessageFeedback, FeedbackReviewItem)
                .outerjoin(FeedbackReviewItem, FeedbackReviewItem.feedback_id == MessageFeedback.id)
                .where(
                    MessageFeedback.organization_id == organization_id,
                    MessageFeedback.message_id == message_id,
                )
            )
        ).first()
        feedback, review = feedback_row if feedback_row else (None, None)
        trust = _dict(message.trust_metadata_json)
        confidence = _dict(trust.get("confidence"))
        raw_reasons = confidence.get("reasons")
        reasons: list[Any] = raw_reasons if isinstance(raw_reasons, list) else []
        return AnswerQualityDetailResponse(
            message_id=message_id,
            question=row.question,
            final_answer=message.content,
            user_id=row.user_id,
            user_name=row.user_name,
            confidence=row.confidence,
            confidence_level=row.confidence_level,
            citation_support_score=row.citation_support_score,
            confidence_reasons=[
                str(_dict(reason).get("label") or _dict(reason).get("code")) for reason in reasons
            ],
            warnings=row.warnings,
            sources=sources.get(message_id, []),
            feedback_id=feedback.id if feedback else None,
            feedback_category=feedback.category if feedback else None,
            feedback_comment=feedback.comment if feedback else None,
            feedback_status=review.status if review else ("received" if feedback else None),
            related_evaluation_case_id=(
                review.linked_eval_question_id
                if review
                else (feedback.converted_to_eval_question_id if feedback else None)
            ),
            review_item_id=review.id if review else None,
            created_at=row.created_at,
        )

    @staticmethod
    def _average(values: list[float | None]) -> float | None:
        present = [value for value in values if value is not None]
        return round(sum(present) / len(present), 4) if present else None
