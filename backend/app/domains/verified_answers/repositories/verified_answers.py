"""Repository layer for verified answers (F255)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.verified_answer import VerifiedAnswer, VerifiedAnswerCitation, VerifiedAnswerVersion


class VerifiedAnswerRepository:
    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        title: str,
        question: str,
        answer_text: str,
        tags: str | None,
        collection_id: UUID | None,
        owner_id: UUID | None,
        requires_citations: bool,
        review_date: date | None,
        expiry_date: date | None,
        source_message_id: UUID | None,
        created_by_id: UUID | None,
    ) -> VerifiedAnswer:
        answer = VerifiedAnswer(
            organization_id=organization_id,
            title=title,
            question=question,
            answer_text=answer_text,
            status="draft",
            tags=tags,
            collection_id=collection_id,
            owner_id=owner_id or created_by_id,
            requires_citations=requires_citations,
            review_date=review_date,
            expiry_date=expiry_date,
            source_message_id=source_message_id,
            created_by_id=created_by_id,
        )
        db.add(answer)
        await db.flush()
        # Create initial version snapshot.
        await self._snapshot_version(
            db, answer, change_reason="created", changed_by_id=created_by_id
        )
        return answer

    async def get(
        self,
        db: AsyncSession,
        *,
        answer_id: UUID,
        organization_id: UUID,
    ) -> VerifiedAnswer | None:
        stmt = (
            select(VerifiedAnswer)
            .options(
                selectinload(VerifiedAnswer.citations),
                selectinload(VerifiedAnswer.versions),
            )
            .where(
                VerifiedAnswer.id == answer_id,
                VerifiedAnswer.organization_id == organization_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        collection_id: UUID | None = None,
        owner_id: UUID | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VerifiedAnswer]:
        stmt = (
            select(VerifiedAnswer)
            .options(selectinload(VerifiedAnswer.citations))
            .where(VerifiedAnswer.organization_id == organization_id)
        )
        if status:
            stmt = stmt.where(VerifiedAnswer.status == status)
        if collection_id:
            stmt = stmt.where(VerifiedAnswer.collection_id == collection_id)
        if owner_id:
            stmt = stmt.where(VerifiedAnswer.owner_id == owner_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    VerifiedAnswer.title.ilike(like),
                    VerifiedAnswer.question.ilike(like),
                    VerifiedAnswer.answer_text.ilike(like),
                )
            )
        stmt = stmt.order_by(VerifiedAnswer.updated_at.desc()).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        collection_id: UUID | None = None,
        owner_id: UUID | None = None,
        query: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(VerifiedAnswer)
            .where(VerifiedAnswer.organization_id == organization_id)
        )
        if status:
            stmt = stmt.where(VerifiedAnswer.status == status)
        if collection_id:
            stmt = stmt.where(VerifiedAnswer.collection_id == collection_id)
        if owner_id:
            stmt = stmt.where(VerifiedAnswer.owner_id == owner_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(
                    VerifiedAnswer.title.ilike(like),
                    VerifiedAnswer.question.ilike(like),
                    VerifiedAnswer.answer_text.ilike(like),
                )
            )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def update_content(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
        *,
        title: str | None,
        question: str | None,
        answer_text: str | None,
        tags: str | None,
        collection_id: UUID | None,
        requires_citations: bool | None,
        review_date: date | None,
        expiry_date: date | None,
        change_reason: str,
        changed_by_id: UUID | None,
    ) -> None:
        if title is not None:
            answer.title = title
        if question is not None:
            answer.question = question
        if answer_text is not None:
            answer.answer_text = answer_text
        if tags is not None:
            answer.tags = tags
        if collection_id is not None:
            answer.collection_id = collection_id
        if requires_citations is not None:
            answer.requires_citations = requires_citations
        if review_date is not None:
            answer.review_date = review_date
        if expiry_date is not None:
            answer.expiry_date = expiry_date
        await db.flush()
        await self._snapshot_version(
            db, answer, change_reason=change_reason, changed_by_id=changed_by_id
        )

    async def set_status(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
        status: str,
    ) -> None:
        answer.status = status
        await db.flush()

    async def approve(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
        *,
        approved_by_id: UUID,
        note: str | None,
    ) -> None:
        now = datetime.now(UTC)
        answer.status = "approved"
        answer.approved_by_id = approved_by_id
        answer.approved_at = now
        answer.rejection_note = None
        await db.flush()

    async def reject(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
        *,
        rejected_by_id: UUID,
        note: str,
    ) -> None:
        answer.status = "draft"
        answer.rejection_note = note
        await db.flush()

    async def publish(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
    ) -> None:
        now = datetime.now(UTC)
        answer.status = "published"
        answer.published_at = now
        await db.flush()

    async def archive(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
    ) -> None:
        answer.status = "archived"
        await db.flush()

    # ------------------------------------------------------------------
    # Citations
    # ------------------------------------------------------------------

    async def replace_citations(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
        citations: list[dict],
    ) -> None:
        # Delete existing citations.
        for citation in list(answer.citations):
            await db.delete(citation)
        await db.flush()
        # Insert new citations.
        for cit in citations:
            db.add(
                VerifiedAnswerCitation(
                    verified_answer_id=answer.id,
                    document_id=UUID(cit["document_id"]),
                    chunk_id=UUID(cit["chunk_id"]) if cit.get("chunk_id") else None,
                    text_snippet=cit.get("text_snippet"),
                    page_number=cit.get("page_number"),
                    citation_order=cit.get("citation_order", 0),
                )
            )
        await db.flush()

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------

    async def list_versions(
        self,
        db: AsyncSession,
        *,
        answer_id: UUID,
        organization_id: UUID,
    ) -> list[VerifiedAnswerVersion]:
        stmt = (
            select(VerifiedAnswerVersion)
            .join(VerifiedAnswer, VerifiedAnswerVersion.verified_answer_id == VerifiedAnswer.id)
            .where(
                VerifiedAnswerVersion.verified_answer_id == answer_id,
                VerifiedAnswer.organization_id == organization_id,
            )
            .order_by(VerifiedAnswerVersion.version_number.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Retrieval helper — find published cards matching a query
    # ------------------------------------------------------------------

    async def find_published_match(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        query: str,
        collection_id: UUID | None = None,
        limit: int = 3,
    ) -> list[VerifiedAnswer]:
        like = f"%{query}%"
        stmt = (
            select(VerifiedAnswer)
            .options(selectinload(VerifiedAnswer.citations))
            .where(
                VerifiedAnswer.organization_id == organization_id,
                VerifiedAnswer.status == "published",
                or_(
                    VerifiedAnswer.question.ilike(like),
                    VerifiedAnswer.title.ilike(like),
                ),
            )
        )
        if collection_id:
            stmt = stmt.where(
                or_(
                    VerifiedAnswer.collection_id == collection_id,
                    VerifiedAnswer.collection_id.is_(None),
                )
            )
        stmt = stmt.order_by(VerifiedAnswer.published_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _snapshot_version(
        self,
        db: AsyncSession,
        answer: VerifiedAnswer,
        *,
        change_reason: str,
        changed_by_id: UUID | None,
    ) -> None:
        count_stmt = (
            select(func.count())
            .select_from(VerifiedAnswerVersion)
            .where(VerifiedAnswerVersion.verified_answer_id == answer.id)
        )
        result = await db.execute(count_stmt)
        next_version = (result.scalar_one() or 0) + 1

        db.add(
            VerifiedAnswerVersion(
                verified_answer_id=answer.id,
                version_number=next_version,
                title=answer.title,
                question=answer.question,
                answer_text=answer.answer_text,
                tags=answer.tags,
                change_reason=change_reason,
                changed_by_id=changed_by_id,
                created_at=datetime.now(UTC),
            )
        )
        await db.flush()
