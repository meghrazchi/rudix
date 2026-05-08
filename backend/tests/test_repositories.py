from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, OrganizationMember, User
from app.models.enums import DocumentStatus, EvaluationRunStatus, OrganizationRole
from app.repositories import ChatRepository, DocumentRepository, EvaluationRepository


@pytest.fixture
def document_repository() -> DocumentRepository:
    return DocumentRepository()


@pytest.fixture
def chat_repository() -> ChatRepository:
    return ChatRepository()


@pytest.fixture
def evaluation_repository() -> EvaluationRepository:
    return EvaluationRepository()


@pytest_asyncio.fixture
async def organization_user_ids(
    db_session: AsyncSession,
) -> tuple[UUID, UUID]:
    organization = Organization(name="Repo Org", slug="repo-org")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="repo-user-1",
        email="repo-user@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=OrganizationRole.owner.value,
    )
    db_session.add(membership)
    await db_session.flush()

    return organization.id, user.id


@pytest.mark.asyncio
async def test_document_repository_crud(
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    organization_user_ids,
) -> None:
    organization_id, user_id = organization_user_ids
    document = await document_repository.create_document(
        db_session,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        filename="repo.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="repo/repo.pdf",
    )

    fetched = await document_repository.get_document(
        db_session,
        document_id=document.id,
        organization_id=organization_id,
    )
    assert fetched is not None
    assert fetched.filename == "repo.pdf"

    await document_repository.create_document_page(
        db_session,
        document_id=document.id,
        page_number=1,
        text="p1",
        char_count=2,
    )
    chunk = await document_repository.create_document_chunk(
        db_session,
        document_id=document.id,
        chunk_index=0,
        text="chunk",
        token_count=1,
        embedding_model="text-embedding-3-small",
    )
    assert chunk.chunk_index == 0

    chunks = await document_repository.list_document_chunks(db_session, document_id=document.id)
    assert len(chunks) == 1

    updated = await document_repository.update_document_status(
        db_session,
        document_id=document.id,
        status=DocumentStatus.indexed.value,
        page_count=1,
    )
    assert updated is not None
    assert updated.status == DocumentStatus.indexed.value
    assert updated.page_count == 1


@pytest.mark.asyncio
async def test_chat_repository_crud(
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    chat_repository: ChatRepository,
    organization_user_ids,
) -> None:
    organization_id, user_id = organization_user_ids
    document = await document_repository.create_document(
        db_session,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        filename="chat.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="repo/chat.pdf",
    )
    chunk = await document_repository.create_document_chunk(
        db_session,
        document_id=document.id,
        chunk_index=0,
        text="chunk",
        token_count=1,
        embedding_model="text-embedding-3-small",
    )

    chat_session = await chat_repository.create_chat_session(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        title="Chat",
    )
    message = await chat_repository.create_chat_message(
        db_session,
        chat_session_id=chat_session.id,
        content="Hello",
        latency_ms=50,
        model_name="gpt-5.4-mini",
        token_input_count=10,
        token_output_count=12,
        cost_usd=Decimal("0.0001"),
    )

    citation = await chat_repository.create_citation(
        db_session,
        chat_message_id=message.id,
        document_id=document.id,
        chunk_id=chunk.id,
        text_snippet="chunk",
        page_number=1,
    )
    assert citation.page_number == 1

    citations = await chat_repository.list_citations_for_message(
        db_session,
        chat_message_id=message.id,
    )
    assert len(citations) == 1


@pytest.mark.asyncio
async def test_evaluation_repository_crud(
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    evaluation_repository: EvaluationRepository,
    organization_user_ids,
) -> None:
    organization_id, user_id = organization_user_ids
    document = await document_repository.create_document(
        db_session,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        filename="eval.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="repo/eval.pdf",
    )

    eval_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=organization_id,
        name="Default Set",
        description="desc",
    )
    question = await evaluation_repository.create_evaluation_question(
        db_session,
        evaluation_set_id=eval_set.id,
        question="Q1",
        expected_answer="A1",
        expected_document_id=document.id,
        expected_page_number=1,
        metadata={"difficulty": "easy"},
    )
    run = await evaluation_repository.create_evaluation_run(
        db_session,
        evaluation_set_id=eval_set.id,
        status=EvaluationRunStatus.running.value,
        config={"sample_size": 1},
    )
    fetched_run = await evaluation_repository.get_evaluation_run(
        db_session,
        evaluation_run_id=run.id,
    )
    assert fetched_run is not None
    assert fetched_run.status == EvaluationRunStatus.running.value

    updated_run = await evaluation_repository.update_evaluation_run_status(
        db_session,
        evaluation_run_id=run.id,
        status=EvaluationRunStatus.completed.value,
        mark_started=True,
        mark_completed=True,
    )
    assert updated_run is not None
    assert updated_run.status == EvaluationRunStatus.completed.value
    assert updated_run.started_at is not None
    assert updated_run.completed_at is not None

    result = await evaluation_repository.create_evaluation_result(
        db_session,
        evaluation_run_id=run.id,
        evaluation_question_id=question.id,
        generated_answer="A1",
        retrieval_score=0.9,
        details={"passed": True},
    )
    assert result.generated_answer == "A1"
