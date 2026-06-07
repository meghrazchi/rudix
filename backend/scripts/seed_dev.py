"""Seed local development data for the backend schema."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.auth.passwords import PasswordHashConfig, build_password_hasher, hash_password
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    ChatMessage,
    ChatSession,
    Citation,
    Document,
    DocumentChunk,
    DocumentPage,
    EvaluationQuestion,
    EvaluationResult,
    EvaluationRun,
    EvaluationSet,
    Organization,
    OrganizationMember,
    UsageEvent,
    User,
)
from app.models.enums import (
    ChatRole,
    DocumentStatus,
    EvaluationRunStatus,
    OrganizationRole,
)

_PASSWORD_HASHER = build_password_hasher(
    PasswordHashConfig(
        memory_cost=settings.app_auth_password_hash_memory_cost_kib,
        time_cost=settings.app_auth_password_hash_time_cost,
        parallelism=settings.app_auth_password_hash_parallelism,
        hash_length=settings.app_auth_password_hash_length,
        salt_length=settings.app_auth_password_salt_length,
    )
)
_SEEDED_PASSWORD = "123123123"


async def _get_or_create_organization() -> Organization:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Organization).where(Organization.slug == "demo-org")
        )
        organization = result.scalar_one_or_none()
        if organization is not None:
            return organization

        organization = Organization(name="Demo Organization", slug="demo-org")
        session.add(organization)
        await session.commit()
        await session.refresh(organization)
        return organization


async def _get_or_create_user(organization: Organization) -> User:
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.external_auth_id == "seed-user-001")
        )
        user = result.scalar_one_or_none()
        if user is not None:
            if user.email != "seed-user@example.com":
                user.email = "seed-user@example.com"
            user.display_name = "Seed User"
            user.hashed_password = hash_password(_SEEDED_PASSWORD, _PASSWORD_HASHER)
            user.password_state = "active"
            user.password_changed_at = datetime.now(UTC)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

        user = User(
            organization_id=organization.id,
            external_auth_id="seed-user-001",
            email="seed-user@example.com",
            display_name="Seed User",
            hashed_password=hash_password(_SEEDED_PASSWORD, _PASSWORD_HASHER),
            password_state="active",
        )
        session.add(user)
        await session.flush()

        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.owner.value,
        )
        session.add(membership)
        await session.commit()
        await session.refresh(user)
        return user


async def _get_or_create_document(organization: Organization, user: User) -> Document:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Document).where(
                Document.organization_id == organization.id,
                Document.filename == "seed-document.pdf",
            )
        )
        document = result.scalar_one_or_none()
        if document is not None:
            return document

        document = Document(
            organization_id=organization.id,
            uploaded_by_user_id=user.id,
            filename="seed-document.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key="seed/demo-org/seed-document.pdf",
            status=DocumentStatus.indexed.value,
            page_count=1,
            checksum="seed-checksum-001",
        )
        session.add(document)
        await session.flush()

        page = DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Seed document page content.",
            char_count=27,
        )
        session.add(page)
        await session.flush()

        chunk = DocumentChunk(
            document_id=document.id,
            page_number=1,
            chunk_index=0,
            text="Seed chunk content.",
            token_count=4,
            embedding_model="text-embedding-3-small",
            qdrant_point_id=f"seed-{document.id}",
            index_version="v1",
        )
        session.add(chunk)

        await session.commit()
        await session.refresh(document)
        return document


async def _seed_chat(organization: Organization, user: User, document: Document) -> None:
    async with SessionLocal() as session:
        existing = await session.execute(
            select(ChatSession).where(
                ChatSession.organization_id == organization.id,
                ChatSession.user_id == user.id,
                ChatSession.title == "Seed Session",
            )
        )
        chat_session = existing.scalar_one_or_none()
        if chat_session is None:
            chat_session = ChatSession(
                organization_id=organization.id,
                user_id=user.id,
                title="Seed Session",
            )
            session.add(chat_session)
            await session.flush()

            user_message = ChatMessage(
                chat_session_id=chat_session.id,
                role=ChatRole.user.value,
                content="What is inside the seed document?",
            )
            assistant_message = ChatMessage(
                chat_session_id=chat_session.id,
                role=ChatRole.assistant.value,
                content="The seed document contains placeholder content.",
                model_name="gpt-5.4-mini",
                latency_ms=120,
                token_input_count=12,
                token_output_count=16,
            )
            session.add_all([user_message, assistant_message])
            await session.flush()

            chunk_result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document.id)
            )
            chunk = chunk_result.scalar_one()

            citation = Citation(
                chat_message_id=assistant_message.id,
                document_id=document.id,
                chunk_id=chunk.id,
                page_number=1,
                text_snippet=chunk.text,
                similarity_score=0.9,
            )
            session.add(citation)
            await session.flush()

        await session.commit()


async def _seed_evaluation(organization: Organization, document: Document) -> None:
    async with SessionLocal() as session:
        set_result = await session.execute(
            select(EvaluationSet).where(
                EvaluationSet.organization_id == organization.id,
                EvaluationSet.name == "Seed Eval Set",
            )
        )
        evaluation_set = set_result.scalar_one_or_none()
        if evaluation_set is None:
            evaluation_set = EvaluationSet(
                organization_id=organization.id,
                name="Seed Eval Set",
                description="Local seed evaluation set.",
            )
            session.add(evaluation_set)
            await session.flush()

            question = EvaluationQuestion(
                evaluation_set_id=evaluation_set.id,
                question="What does the seed document contain?",
                expected_answer="placeholder content",
                expected_document_id=document.id,
                expected_page_number=1,
                metadata_json={"seed": True},
            )
            session.add(question)
            await session.flush()

            run = EvaluationRun(
                evaluation_set_id=evaluation_set.id,
                status=EvaluationRunStatus.completed.value,
                config={"seed": True},
            )
            session.add(run)
            await session.flush()

            result = EvaluationResult(
                evaluation_run_id=run.id,
                evaluation_question_id=question.id,
                generated_answer="placeholder content",
                retrieval_score=0.95,
                answer_relevance_score=0.92,
                details={"seed": True, "pass": True},
            )
            session.add(result)
            await session.flush()

        await session.commit()


async def _seed_usage_and_audit(organization: Organization, user: User, document: Document) -> None:
    async with SessionLocal() as session:
        usage_exists = await session.execute(
            select(UsageEvent).where(
                UsageEvent.organization_id == organization.id,
                UsageEvent.event_type == "seed.event",
            )
        )
        if usage_exists.scalar_one_or_none() is None:
            usage = UsageEvent(
                organization_id=organization.id,
                user_id=user.id,
                event_type="seed.event",
                model_name="gpt-5.4-mini",
                input_tokens=10,
                output_tokens=12,
                metadata_json={"seed": True},
            )
            session.add(usage)

        audit_exists = await session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == organization.id,
                AuditLog.action == "seed.document.created",
            )
        )
        if audit_exists.scalar_one_or_none() is None:
            audit = AuditLog(
                organization_id=organization.id,
                user_id=user.id,
                action="seed.document.created",
                resource_type="document",
                resource_id=document.id,
                metadata_json={"filename": document.filename},
            )
            session.add(audit)

        await session.commit()


async def seed() -> dict[str, Any]:
    organization = await _get_or_create_organization()
    user = await _get_or_create_user(organization)
    document = await _get_or_create_document(organization, user)
    await _seed_chat(organization, user, document)
    await _seed_evaluation(organization, document)
    await _seed_usage_and_audit(organization, user, document)

    return {
        "organization_id": str(organization.id),
        "user_id": str(user.id),
        "document_id": str(document.id),
    }


def main() -> None:
    result = asyncio.run(seed())
    print("Seed complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
