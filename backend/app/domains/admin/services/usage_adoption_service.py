"""Aggregation service for the admin usage & adoption report (F353).

Rolls up existing usage-event, chat, citation, feedback, verified-answer,
answer-share, and invitation signals into adoption metrics, an activation
funnel, charts, and an actionable per-user table. No new persisted state is
introduced — every field read here already exists from prior features
(F134 chat history, F132 citations, F138 feedback, F255 verified answers,
F259 answer sharing, F278 invitations, and the F153/F349 usage-event
pipeline that the frontend's `analytics.ts` already writes to).

Two distinct date-range semantics are used deliberately:
  - Summary/charts/table metrics are windowed: they count activity whose own
    timestamp falls inside [from, to].
  - The activation funnel is cohort-based: [from, to] selects which users
    *signed up* in that window, then each funnel step counts how many of
    those users ever reached it (at any time), matching how product funnels
    are normally read ("of everyone who joined in January, how many asked a
    question eventually?").

There is no `Team` entity in this codebase (see `app/domains/team/`, which
just manages the single org-wide member list) — the ticket's "team" filter
and "team adoption comparison" chart are therefore implemented as grouping
by organization role, the only real grouping axis available.

Follows the fetch-then-aggregate-in-Python style used by
`source_health_service.py` so the aggregation logic can be unit tested
without exotic SQL.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.schemas.usage_adoption import (
    ActivationFunnelStepResponse,
    ActiveUsersPoint,
    QuestionsPerUserBucket,
    RoleAdoptionRow,
    UsageAdoptionChartsResponse,
    UsageAdoptionSummaryResponse,
    UsageAdoptionUserListResponse,
    UsageAdoptionUserRow,
)
from app.models.answer_share import AnswerShare
from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.collection import CollectionDocument
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.connector_source import SourceDocument
from app.models.document import Document
from app.models.message_feedback import MessageFeedback
from app.models.organization_invitation import OrganizationInvitation
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User
from app.models.verified_answer import VerifiedAnswer

_DEFAULT_WINDOW_DAYS = 30
_MAX_USERS_SCANNED = 5_000
_QUESTIONS_PER_USER_BUCKETS = ((0, 0), (1, 4), (5, 19), (20, 99), (100, None))

_EVT_INDEXED = "analytics.v1.activation.first_indexed_document"
_EVT_FIRST_QUESTION = "analytics.v1.activation.first_question"
_EVT_CITATION_OPENED = "analytics.v1.feature.chat.citation_opened"
_EVT_TRUST_PANEL_OPENED = "analytics.v1.feature.chat.trust_panel_opened"

_FUNNEL_STEPS: tuple[tuple[str, str], ...] = (
    ("signed_up", "Signed up"),
    ("joined_organization", "Joined organization"),
    ("connected_or_uploaded_source", "Connected or uploaded a source"),
    ("source_indexed", "Source indexed"),
    ("asked_first_question", "Asked first question"),
    ("opened_citation", "Opened a citation"),
    ("saved_or_shared_answer", "Saved or shared an answer"),
    ("invited_teammate", "Invited a teammate"),
    ("returned_again", "Returned again"),
)

# Core RAG loop steps used to derive per-user onboarding status when no
# persisted checklist state exists server-side (F327's checklist is
# client-side/localStorage only). "invited_teammate" is intentionally
# excluded — not every activated user needs to invite anyone.
_ONBOARDING_CORE_STEPS = (
    "connected_or_uploaded_source",
    "source_indexed",
    "asked_first_question",
    "opened_citation",
)


@dataclass
class UsageAdoptionFilters:
    from_date: date | None = None
    to_date: date | None = None
    role: str | None = None


def _resolve_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    today = datetime.now(tz=UTC).date()
    resolved_to = to_date or today
    resolved_from = from_date or resolved_to - timedelta(days=_DEFAULT_WINDOW_DAYS - 1)
    if resolved_from > resolved_to:
        resolved_from, resolved_to = resolved_to, resolved_from
    return resolved_from, resolved_to


def _range_datetimes(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(from_date, time.min, tzinfo=UTC),
        datetime.combine(to_date, time.max, tzinfo=UTC),
    )


def _bucket_label(count: int) -> str:
    for low, high in _QUESTIONS_PER_USER_BUCKETS:
        if high is None:
            if count >= low:
                return f"{low}+"
        elif low <= count <= high:
            return f"{low}-{high}" if low != high else str(low)
    return "0"


class UsageAdoptionService:
    async def get_summary(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: UsageAdoptionFilters,
    ) -> UsageAdoptionSummaryResponse:
        from_date, to_date = _resolve_range(filters.from_date, filters.to_date)
        from_dt, to_dt = _range_datetimes(from_date, to_date)
        role_ids = await self._role_filtered_user_ids(session, organization_id, filters.role)
        if role_ids is not None and not role_ids:
            return UsageAdoptionSummaryResponse(generated_at=datetime.now(tz=UTC))

        active_users, new_users, returning_users = await self._user_activity_counts(
            session, organization_id, from_dt, to_dt, role_ids
        )
        questions_asked = await self._questions_asked_count(
            session, organization_id, from_dt, to_dt, role_ids
        )
        documents_uploaded = await self._documents_uploaded_count(
            session, organization_id, from_dt, to_dt, role_ids
        )
        collections_used, connectors_used = await self._collections_and_connectors_used(
            session, organization_id, from_dt, to_dt, role_ids
        )
        citation_clicks = await self._usage_event_count(
            session, organization_id, _EVT_CITATION_OPENED, from_dt, to_dt, role_ids
        )
        trust_panel_opens = await self._usage_event_count(
            session, organization_id, _EVT_TRUST_PANEL_OPENED, from_dt, to_dt, role_ids
        )
        feedback_submitted = await self._feedback_count(
            session, organization_id, from_dt, to_dt, role_ids
        )
        saved_answers = await self._saved_answers_count(
            session, organization_id, from_dt, to_dt, role_ids
        )
        invitations_sent, invitations_accepted = await self._invitation_counts(
            session, organization_id, from_dt, to_dt
        )
        onboarding_rate = await self._onboarding_completion_rate(session, organization_id, role_ids)

        return UsageAdoptionSummaryResponse(
            active_users=active_users,
            new_users=new_users,
            returning_users=returning_users,
            questions_asked=questions_asked,
            documents_uploaded=documents_uploaded,
            collections_used=collections_used,
            connectors_used=connectors_used,
            citation_clicks=citation_clicks,
            trust_panel_opens=trust_panel_opens,
            feedback_submitted=feedback_submitted,
            saved_answers=saved_answers,
            onboarding_completion_rate=onboarding_rate,
            invitations_sent=invitations_sent,
            invitations_accepted=invitations_accepted,
            generated_at=datetime.now(tz=UTC),
        )

    async def get_charts(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: UsageAdoptionFilters,
    ) -> UsageAdoptionChartsResponse:
        from_date, to_date = _resolve_range(filters.from_date, filters.to_date)
        from_dt, to_dt = _range_datetimes(from_date, to_date)
        role_ids = await self._role_filtered_user_ids(session, organization_id, filters.role)

        active_users_series = await self._active_users_series(
            session, organization_id, from_date, to_date, role_ids
        )
        questions_per_user = await self._questions_per_user_buckets(
            session, organization_id, from_dt, to_dt, role_ids
        )
        feature_usage = await self._feature_usage(
            session, organization_id, from_dt, to_dt, role_ids
        )
        funnel = await self.get_activation_funnel(
            session, organization_id=organization_id, filters=filters
        )
        role_adoption = await self._role_adoption_comparison(
            session, organization_id, from_dt, to_dt
        )
        drop_off_points = sorted(
            [step for step in funnel if step.drop_off_rate is not None],
            key=lambda step: step.drop_off_rate or 0,
            reverse=True,
        )[:3]

        return UsageAdoptionChartsResponse(
            active_users_series=active_users_series,
            questions_per_user=questions_per_user,
            feature_usage=feature_usage,
            funnel=funnel,
            role_adoption_comparison=role_adoption,
            drop_off_points=drop_off_points,
            generated_at=datetime.now(tz=UTC),
        )

    async def get_activation_funnel(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: UsageAdoptionFilters,
    ) -> list[ActivationFunnelStepResponse]:
        role_ids = await self._role_filtered_user_ids(session, organization_id, filters.role)
        if role_ids is not None and not role_ids:
            return [
                ActivationFunnelStepResponse(step=key, label=label, users_reached=0)
                for key, label in _FUNNEL_STEPS
            ]

        # Join through OrganizationMember rather than filtering on User.organization_id:
        # that column is just a user's default/last-active org (see auth.py's
        # _select_active_membership), not their full membership set, so a user whose
        # default org differs from this one would otherwise be dropped from the cohort.
        cohort_stmt = (
            select(User.id, User.created_at)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == organization_id)
        )
        if filters.from_date is not None:
            cohort_stmt = cohort_stmt.where(
                User.created_at >= _range_datetimes(filters.from_date, filters.from_date)[0]
            )
        if filters.to_date is not None:
            cohort_stmt = cohort_stmt.where(
                User.created_at <= _range_datetimes(filters.to_date, filters.to_date)[1]
            )
        cohort_rows = (await session.execute(cohort_stmt)).all()
        cohort_ids = {user_id for user_id, _ in cohort_rows}
        if role_ids is not None:
            cohort_ids &= role_ids

        reached_by_step = await self._step_reached_user_ids(session, organization_id)

        steps: list[ActivationFunnelStepResponse] = []
        previous_reached: int | None = None
        for key, label in _FUNNEL_STEPS:
            reached_ids = reached_by_step.get(key, set()) & cohort_ids
            reached = len(reached_ids)
            drop_off = None
            if previous_reached is not None and previous_reached > 0:
                drop_off = round((previous_reached - reached) / previous_reached, 4)
            steps.append(
                ActivationFunnelStepResponse(
                    step=key, label=label, users_reached=reached, drop_off_rate=drop_off
                )
            )
            previous_reached = reached
        return steps

    async def list_users(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: UsageAdoptionFilters,
        page: int = 1,
        page_size: int = 25,
    ) -> UsageAdoptionUserListResponse:
        rows = await self._build_user_rows(session, organization_id, filters)
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        return UsageAdoptionUserListResponse(
            rows=page_rows, total=total, page=page, page_size=page_size
        )

    async def build_export_csv(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: UsageAdoptionFilters,
    ) -> str:
        rows = await self._build_user_rows(session, organization_id, filters)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "name",
                "email",
                "role",
                "last_active_at",
                "questions_asked",
                "sources_used",
                "citation_clicks",
                "feedback_submitted",
                "saved_answers",
                "onboarding_status",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.name,
                    row.email,
                    row.role,
                    row.last_active_at.isoformat() if row.last_active_at else "",
                    row.questions_asked,
                    row.sources_used,
                    row.citation_clicks,
                    row.feedback_submitted,
                    row.saved_answers,
                    row.onboarding_status,
                ]
            )
        return buffer.getvalue()

    # -- internal: role scoping ------------------------------------------------

    async def _role_filtered_user_ids(
        self, session: AsyncSession, organization_id: UUID, role: str | None
    ) -> set[UUID] | None:
        if role is None:
            return None
        stmt = select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == role,
        )
        result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    async def _member_roles(self, session: AsyncSession, organization_id: UUID) -> dict[UUID, str]:
        stmt = select(OrganizationMember.user_id, OrganizationMember.role).where(
            OrganizationMember.organization_id == organization_id
        )
        result = await session.execute(stmt)
        return {user_id: role for user_id, role in result.all()}

    # -- internal: summary metrics ----------------------------------------------

    async def _active_user_ids(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None = None,
    ) -> set[UUID]:
        # Plain columns (not func.distinct(...)) — the row is deduped into a Python
        # set below anyway, and wrapping a Uuid column in func.distinct() erases its
        # result type on some dialects (e.g. sqlite), yielding raw strings instead of
        # UUID objects that then silently fail to match UUID-keyed sets/dicts.
        active_stmt = (
            select(ChatSession.user_id)
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatMessage.created_at >= from_dt,
                ChatMessage.created_at <= to_dt,
            )
        )
        active_ids = {row[0] for row in (await session.execute(active_stmt)).all()}
        # Union with any org usage-event actor (covers uploads/citations/etc.,
        # not only chat) so "active" isn't chat-only.
        usage_stmt = select(UsageEvent.user_id).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.user_id.is_not(None),
            UsageEvent.created_at >= from_dt,
            UsageEvent.created_at <= to_dt,
        )
        active_ids |= {row[0] for row in (await session.execute(usage_stmt)).all()}
        if role_ids is not None:
            active_ids &= role_ids
        return active_ids

    async def _user_activity_counts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> tuple[int, int, int]:
        first_activity = await self._first_activity_map(session, organization_id)
        active_ids = await self._active_user_ids(session, organization_id, from_dt, to_dt, role_ids)

        new_users = 0
        returning_users = 0
        for user_id in active_ids:
            first_seen = first_activity.get(user_id)
            # Some DBAPI drivers (e.g. sqlite) drop tzinfo on round-trip; timestamps
            # in this table are always written in UTC, so a naive value is UTC.
            if first_seen is not None and first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=UTC)
            if first_seen is not None and first_seen >= from_dt:
                new_users += 1
            else:
                returning_users += 1
        return len(active_ids), new_users, returning_users

    async def _first_activity_map(
        self, session: AsyncSession, organization_id: UUID
    ) -> dict[UUID, datetime]:
        stmt = (
            select(UsageEvent.user_id, func.min(UsageEvent.created_at))
            .where(UsageEvent.organization_id == organization_id, UsageEvent.user_id.is_not(None))
            .group_by(UsageEvent.user_id)
        )
        result = await session.execute(stmt)
        return {user_id: first_seen for user_id, first_seen in result.all()}

    async def _questions_asked_count(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> int:
        stmt = (
            select(func.count(ChatMessage.id))
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= from_dt,
                ChatMessage.created_at <= to_dt,
            )
        )
        if role_ids is not None:
            stmt = stmt.where(ChatSession.user_id.in_(role_ids))
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _documents_uploaded_count(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> int:
        stmt = select(func.count(Document.id)).where(
            Document.organization_id == organization_id,
            Document.created_at >= from_dt,
            Document.created_at <= to_dt,
        )
        if role_ids is not None:
            stmt = stmt.where(Document.uploaded_by_user_id.in_(role_ids))
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _collections_and_connectors_used(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> tuple[int, int]:
        base = (
            select(ChatSession.user_id, Citation.document_id)
            .select_from(Citation)
            .join(ChatMessage, ChatMessage.id == Citation.chat_message_id)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.organization_id == organization_id,
                Citation.created_at >= from_dt,
                Citation.created_at <= to_dt,
            )
        )
        if role_ids is not None:
            base = base.where(ChatSession.user_id.in_(role_ids))
        cited = (await session.execute(base)).all()
        if not cited:
            return 0, 0
        document_ids = {doc_id for _, doc_id in cited}

        collections_stmt = select(CollectionDocument.collection_id).where(
            CollectionDocument.document_id.in_(document_ids)
        )
        collections_used = len({row[0] for row in (await session.execute(collections_stmt)).all()})

        connectors_stmt = (
            select(ConnectorConnection.id)
            .select_from(SourceDocument)
            .join(ExternalItem, ExternalItem.id == SourceDocument.external_item_id)
            .join(ConnectorConnection, ConnectorConnection.id == ExternalItem.connection_id)
            .where(SourceDocument.document_id.in_(document_ids))
        )
        connectors_used = len({row[0] for row in (await session.execute(connectors_stmt)).all()})
        return collections_used, connectors_used

    async def _usage_event_count(
        self,
        session: AsyncSession,
        organization_id: UUID,
        event_type: str,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> int:
        stmt = select(func.count(UsageEvent.id)).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.event_type == event_type,
            UsageEvent.created_at >= from_dt,
            UsageEvent.created_at <= to_dt,
        )
        if role_ids is not None:
            stmt = stmt.where(UsageEvent.user_id.in_(role_ids))
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _feedback_count(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> int:
        stmt = select(func.count(MessageFeedback.id)).where(
            MessageFeedback.organization_id == organization_id,
            MessageFeedback.created_at >= from_dt,
            MessageFeedback.created_at <= to_dt,
        )
        if role_ids is not None:
            stmt = stmt.where(MessageFeedback.user_id.in_(role_ids))
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _saved_answers_count(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> int:
        stmt = select(func.count(VerifiedAnswer.id)).where(
            VerifiedAnswer.organization_id == organization_id,
            VerifiedAnswer.created_at >= from_dt,
            VerifiedAnswer.created_at <= to_dt,
        )
        if role_ids is not None:
            stmt = stmt.where(VerifiedAnswer.created_by_id.in_(role_ids))
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _invitation_counts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
    ) -> tuple[int, int]:
        sent_stmt = select(func.count(OrganizationInvitation.id)).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.created_at >= from_dt,
            OrganizationInvitation.created_at <= to_dt,
        )
        sent = int((await session.execute(sent_stmt)).scalar_one() or 0)

        accepted_stmt = select(func.count(OrganizationInvitation.id)).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.accepted_at.is_not(None),
            OrganizationInvitation.accepted_at >= from_dt,
            OrganizationInvitation.accepted_at <= to_dt,
        )
        accepted = int((await session.execute(accepted_stmt)).scalar_one() or 0)
        return sent, accepted

    async def _onboarding_completion_rate(
        self, session: AsyncSession, organization_id: UUID, role_ids: set[UUID] | None
    ) -> float | None:
        member_ids_stmt = select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == organization_id
        )
        all_member_ids = {row[0] for row in (await session.execute(member_ids_stmt)).all()}
        if role_ids is not None:
            all_member_ids &= role_ids
        if not all_member_ids:
            return None

        reached_by_step = await self._step_reached_user_ids(session, organization_id)
        completed = {
            user_id
            for user_id in all_member_ids
            if all(user_id in reached_by_step.get(step, set()) for step in _ONBOARDING_CORE_STEPS)
        }
        return round(len(completed) / len(all_member_ids), 4)

    # -- internal: funnel step derivation ----------------------------------------

    async def _step_reached_user_ids(
        self, session: AsyncSession, organization_id: UUID
    ) -> dict[str, set[UUID]]:
        # "Signed up" and "joined organization" are the same membership set in this
        # schema (see get_activation_funnel's cohort_stmt comment) — both are kept as
        # distinct funnel steps for readability even though they never diverge here.
        joined_stmt = select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == organization_id
        )
        joined = {row[0] for row in (await session.execute(joined_stmt)).all()}
        signed_up = set(joined)

        uploaded_stmt = select(Document.uploaded_by_user_id).where(
            Document.organization_id == organization_id,
            Document.uploaded_by_user_id.is_not(None),
        )
        connected_stmt = select(ConnectorConnection.created_by_user_id).where(
            ConnectorConnection.organization_id == organization_id,
            ConnectorConnection.created_by_user_id.is_not(None),
        )
        connected_or_uploaded = {row[0] for row in (await session.execute(uploaded_stmt)).all()}
        connected_or_uploaded |= {row[0] for row in (await session.execute(connected_stmt)).all()}

        indexed = await self._usage_event_actor_ids(session, organization_id, _EVT_INDEXED)
        asked = await self._usage_event_actor_ids(session, organization_id, _EVT_FIRST_QUESTION)
        opened_citation = await self._usage_event_actor_ids(
            session, organization_id, _EVT_CITATION_OPENED
        )

        saved_stmt = select(VerifiedAnswer.created_by_id).where(
            VerifiedAnswer.organization_id == organization_id,
            VerifiedAnswer.created_by_id.is_not(None),
        )
        shared_stmt = select(AnswerShare.shared_by_user_id).where(
            AnswerShare.organization_id == organization_id
        )
        saved_or_shared = {row[0] for row in (await session.execute(saved_stmt)).all()}
        saved_or_shared |= {row[0] for row in (await session.execute(shared_stmt)).all()}

        invited_stmt = select(OrganizationInvitation.invited_by_user_id).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.invited_by_user_id.is_not(None),
        )
        invited_teammate = {row[0] for row in (await session.execute(invited_stmt)).all()}

        returned_again = await self._returned_again_user_ids(session, organization_id)

        return {
            "signed_up": signed_up,
            "joined_organization": joined,
            "connected_or_uploaded_source": connected_or_uploaded,
            "source_indexed": indexed,
            "asked_first_question": asked,
            "opened_citation": opened_citation,
            "saved_or_shared_answer": saved_or_shared,
            "invited_teammate": invited_teammate,
            "returned_again": returned_again,
        }

    async def _usage_event_actor_ids(
        self, session: AsyncSession, organization_id: UUID, event_type: str
    ) -> set[UUID]:
        stmt = select(UsageEvent.user_id).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.event_type == event_type,
            UsageEvent.user_id.is_not(None),
        )
        result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    async def _returned_again_user_ids(
        self, session: AsyncSession, organization_id: UUID
    ) -> set[UUID]:
        stmt = select(UsageEvent.user_id, func.date(UsageEvent.created_at)).where(
            UsageEvent.organization_id == organization_id, UsageEvent.user_id.is_not(None)
        )
        result = await session.execute(stmt)
        days_by_user: dict[UUID, set] = {}
        for user_id, day in result.all():
            days_by_user.setdefault(user_id, set()).add(day)
        return {user_id for user_id, days in days_by_user.items() if len(days) >= 2}

    # -- internal: chart builders -----------------------------------------------

    async def _active_users_series(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_date: date,
        to_date: date,
        role_ids: set[UUID] | None,
    ) -> list[ActiveUsersPoint]:
        from_dt, to_dt = _range_datetimes(from_date, to_date)
        stmt = select(UsageEvent.user_id, func.date(UsageEvent.created_at)).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.user_id.is_not(None),
            UsageEvent.created_at >= from_dt,
            UsageEvent.created_at <= to_dt,
        )
        if role_ids is not None:
            stmt = stmt.where(UsageEvent.user_id.in_(role_ids))
        result = await session.execute(stmt)
        # func.date() returns a driver-specific type (str on sqlite, date on
        # postgres/asyncpg) — normalize to ISO strings so lookups below are stable.
        users_by_day: dict[str, set[UUID]] = {}
        for user_id, day in result.all():
            users_by_day.setdefault(str(day), set()).add(user_id)

        points: list[ActiveUsersPoint] = []
        current = from_date
        while current <= to_date:
            label = current.isoformat()
            points.append(
                ActiveUsersPoint(date=label, active_users=len(users_by_day.get(label, set())))
            )
            current += timedelta(days=1)
        return points

    async def _questions_per_user_buckets(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> list[QuestionsPerUserBucket]:
        stmt = (
            select(ChatSession.user_id, func.count(ChatMessage.id))
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= from_dt,
                ChatMessage.created_at <= to_dt,
            )
            .group_by(ChatSession.user_id)
        )
        if role_ids is not None:
            stmt = stmt.where(ChatSession.user_id.in_(role_ids))
        result = await session.execute(stmt)
        bucket_counts: dict[str, int] = {}
        for _, count in result.all():
            label = _bucket_label(int(count))
            bucket_counts[label] = bucket_counts.get(label, 0) + 1
        order = [_bucket_label(low) for low, _ in _QUESTIONS_PER_USER_BUCKETS]
        return [
            QuestionsPerUserBucket(bucket=label, user_count=bucket_counts.get(label, 0))
            for label in order
        ]

    async def _feature_usage(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        role_ids: set[UUID] | None,
    ) -> dict[str, int]:
        stmt = select(UsageEvent.event_type, func.count(UsageEvent.id)).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.event_type.like("analytics.v1.feature.%"),
            UsageEvent.created_at >= from_dt,
            UsageEvent.created_at <= to_dt,
        )
        if role_ids is not None:
            stmt = stmt.where(UsageEvent.user_id.in_(role_ids))
        stmt = stmt.group_by(UsageEvent.event_type)
        result = await session.execute(stmt)
        usage: dict[str, int] = {}
        for event_type, count in result.all():
            # "analytics.v1.feature.<area>.<name>" -> "<area>"
            parts = event_type.split(".")
            area = parts[3] if len(parts) > 3 else "other"
            usage[area] = usage.get(area, 0) + int(count)
        return usage

    async def _role_adoption_comparison(
        self,
        session: AsyncSession,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[RoleAdoptionRow]:
        roles_by_user = await self._member_roles(session, organization_id)
        if not roles_by_user:
            return []

        user_counts: dict[str, int] = {}
        for member_role in roles_by_user.values():
            user_counts[member_role] = user_counts.get(member_role, 0) + 1

        active_ids = await self._active_user_ids(session, organization_id, from_dt, to_dt)
        active_by_role: dict[str, int] = {}
        for user_id in active_ids:
            role = roles_by_user.get(user_id)
            if role:
                active_by_role[role] = active_by_role.get(role, 0) + 1

        questions_stmt = (
            select(ChatSession.user_id, func.count(ChatMessage.id))
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= from_dt,
                ChatMessage.created_at <= to_dt,
            )
            .group_by(ChatSession.user_id)
        )
        questions_by_role: dict[str, int] = {}
        for user_id, count in (await session.execute(questions_stmt)).all():
            role = roles_by_user.get(user_id)
            if role:
                questions_by_role[role] = questions_by_role.get(role, 0) + int(count)

        rows: list[RoleAdoptionRow] = []
        for role, total in sorted(user_counts.items(), key=lambda item: item[1], reverse=True):
            active = active_by_role.get(role, 0)
            rows.append(
                RoleAdoptionRow(
                    role=role,
                    user_count=total,
                    active_users=active,
                    questions_asked=questions_by_role.get(role, 0),
                    activation_rate=round(active / total, 4) if total else None,
                )
            )
        return rows

    # -- internal: user table -----------------------------------------------

    async def _build_user_rows(
        self,
        session: AsyncSession,
        organization_id: UUID,
        filters: UsageAdoptionFilters,
    ) -> list[UsageAdoptionUserRow]:
        from_date, to_date = _resolve_range(filters.from_date, filters.to_date)
        from_dt, to_dt = _range_datetimes(from_date, to_date)

        members_stmt = (
            select(User, OrganizationMember.role)
            .select_from(OrganizationMember)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == organization_id)
            .limit(_MAX_USERS_SCANNED)
        )
        if filters.role is not None:
            members_stmt = members_stmt.where(OrganizationMember.role == filters.role)
        members = (await session.execute(members_stmt)).all()
        if not members:
            return []

        user_ids = {user.id for user, _ in members}

        last_active_stmt = (
            select(UsageEvent.user_id, func.max(UsageEvent.created_at))
            .where(UsageEvent.organization_id == organization_id, UsageEvent.user_id.in_(user_ids))
            .group_by(UsageEvent.user_id)
        )
        last_active = {
            user_id: last_seen
            for user_id, last_seen in (await session.execute(last_active_stmt)).all()
        }

        questions_stmt = (
            select(ChatSession.user_id, func.count(ChatMessage.id))
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatSession.user_id.in_(user_ids),
                ChatMessage.role == "user",
                ChatMessage.created_at >= from_dt,
                ChatMessage.created_at <= to_dt,
            )
            .group_by(ChatSession.user_id)
        )
        questions_asked = {
            user_id: int(count) for user_id, count in (await session.execute(questions_stmt)).all()
        }

        sources_stmt = (
            select(ChatSession.user_id, func.count(func.distinct(Citation.document_id)))
            .select_from(Citation)
            .join(ChatMessage, ChatMessage.id == Citation.chat_message_id)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatSession.user_id.in_(user_ids),
                Citation.created_at >= from_dt,
                Citation.created_at <= to_dt,
            )
            .group_by(ChatSession.user_id)
        )
        sources_used = {
            user_id: int(count) for user_id, count in (await session.execute(sources_stmt)).all()
        }

        citation_clicks_stmt = (
            select(UsageEvent.user_id, func.count(UsageEvent.id))
            .where(
                UsageEvent.organization_id == organization_id,
                UsageEvent.user_id.in_(user_ids),
                UsageEvent.event_type == _EVT_CITATION_OPENED,
                UsageEvent.created_at >= from_dt,
                UsageEvent.created_at <= to_dt,
            )
            .group_by(UsageEvent.user_id)
        )
        citation_clicks = {
            user_id: int(count)
            for user_id, count in (await session.execute(citation_clicks_stmt)).all()
        }

        feedback_stmt = (
            select(MessageFeedback.user_id, func.count(MessageFeedback.id))
            .where(
                MessageFeedback.organization_id == organization_id,
                MessageFeedback.user_id.in_(user_ids),
                MessageFeedback.created_at >= from_dt,
                MessageFeedback.created_at <= to_dt,
            )
            .group_by(MessageFeedback.user_id)
        )
        feedback_submitted = {
            user_id: int(count) for user_id, count in (await session.execute(feedback_stmt)).all()
        }

        saved_stmt = (
            select(VerifiedAnswer.created_by_id, func.count(VerifiedAnswer.id))
            .where(
                VerifiedAnswer.organization_id == organization_id,
                VerifiedAnswer.created_by_id.in_(user_ids),
                VerifiedAnswer.created_at >= from_dt,
                VerifiedAnswer.created_at <= to_dt,
            )
            .group_by(VerifiedAnswer.created_by_id)
        )
        saved_answers = {
            user_id: int(count) for user_id, count in (await session.execute(saved_stmt)).all()
        }

        reached_by_step = await self._step_reached_user_ids(session, organization_id)

        rows: list[UsageAdoptionUserRow] = []
        for user, role in members:
            reached_count = sum(
                1 for step in _ONBOARDING_CORE_STEPS if user.id in reached_by_step.get(step, set())
            )
            if reached_count == 0:
                onboarding_status = "not_started"
            elif reached_count == len(_ONBOARDING_CORE_STEPS):
                onboarding_status = "completed"
            else:
                onboarding_status = "in_progress"

            rows.append(
                UsageAdoptionUserRow(
                    user_id=str(user.id),
                    name=user.display_name or user.email,
                    email=user.email,
                    role=role,
                    last_active_at=last_active.get(user.id),
                    questions_asked=questions_asked.get(user.id, 0),
                    sources_used=sources_used.get(user.id, 0),
                    citation_clicks=citation_clicks.get(user.id, 0),
                    feedback_submitted=feedback_submitted.get(user.id, 0),
                    saved_answers=saved_answers.get(user.id, 0),
                    onboarding_status=onboarding_status,
                )
            )

        rows.sort(key=lambda r: r.name.lower())
        return rows
