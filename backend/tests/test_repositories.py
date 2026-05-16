from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.repositories.usage import UsageRepository
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.models import Organization, OrganizationMember, User
from app.models.enums import DocumentStatus, EvaluationRunStatus, OrganizationRole


@pytest.fixture
def document_repository() -> DocumentRepository:
    return DocumentRepository()


@pytest.fixture
def chat_repository() -> ChatRepository:
    return ChatRepository()


@pytest.fixture
def evaluation_repository() -> EvaluationRepository:
    return EvaluationRepository()


@pytest.fixture
def usage_repository() -> UsageRepository:
    return UsageRepository()


@pytest.fixture
def pipeline_repository() -> PipelineRepository:
    return PipelineRepository()


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
    await document_repository.create_document_chunk(
        db_session,
        document_id=document.id,
        chunk_index=0,
        text="chunk-v2",
        token_count=2,
        embedding_model="text-embedding-3-small",
        index_version="v2",
    )
    assert chunk.chunk_index == 0

    chunks = await document_repository.list_document_chunks(
        db_session,
        document_id=document.id,
        index_version="v1",
    )
    assert len(chunks) == 1
    assert chunks[0].index_version == "v1"

    removed = await document_repository.delete_document_chunks(
        db_session,
        document_id=document.id,
        index_version="v1",
    )
    assert removed == 1
    chunks_after_delete = await document_repository.list_document_chunks(db_session, document_id=document.id)
    assert len(chunks_after_delete) == 1
    assert chunks_after_delete[0].index_version == "v2"

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

    fetched_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session.id,
        organization_id=organization_id,
        user_id=user_id,
    )
    assert fetched_session is not None
    assert fetched_session.title == "Chat"

    listed_sessions = await chat_repository.list_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        limit=10,
        offset=0,
    )
    assert len(listed_sessions) == 1
    assert listed_sessions[0].id == chat_session.id

    total_sessions = await chat_repository.count_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )
    assert total_sessions == 1

    message_counts = await chat_repository.count_messages_by_session_ids(
        db_session,
        session_ids=[chat_session.id],
    )
    assert message_counts[chat_session.id] == 1


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


@pytest.mark.asyncio
async def test_usage_repository_create_event(
    db_session: AsyncSession,
    usage_repository: UsageRepository,
    organization_user_ids,
) -> None:
    organization_id, user_id = organization_user_ids
    event = await usage_repository.create_usage_event(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        event_type="document.embedding",
        model_name="text-embedding-3-small",
        input_tokens=321,
        output_tokens=None,
        cost_usd=Decimal("0.000006"),
        metadata={"document_id": "doc-1", "batch_count": 3},
    )
    assert event.event_type == "document.embedding"
    assert event.model_name == "text-embedding-3-small"
    assert event.input_tokens == 321
    assert event.metadata_json["batch_count"] == 3


@pytest.mark.asyncio
async def test_usage_repository_create_audit_log(
    db_session: AsyncSession,
    usage_repository: UsageRepository,
    organization_user_ids,
) -> None:
    organization_id, user_id = organization_user_ids
    audit_log = await usage_repository.create_audit_log(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="document.upload.accepted",
        resource_type="document",
        metadata={"request_id": "req-1", "status_code": 201},
    )
    assert audit_log.action == "document.upload.accepted"
    assert audit_log.resource_type == "document"
    assert audit_log.metadata_json["request_id"] == "req-1"
    assert audit_log.metadata_json["status_code"] == 201


@pytest.mark.asyncio
async def test_pipeline_repository_create_and_update(
    db_session: AsyncSession,
    pipeline_repository: PipelineRepository,
    organization_user_ids,
) -> None:
    organization_id, user_id = organization_user_ids
    document_repository = DocumentRepository()
    document = await document_repository.create_document(
        db_session,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        filename="pipeline.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="repo/pipeline.pdf",
    )

    run = await pipeline_repository.create_pipeline_run(
        db_session,
        organization_id=organization_id,
        document_id=document.id,
        pipeline_type="document.process",
        status="running",
        inputs={"document_id": str(document.id)},
    )
    event = await pipeline_repository.create_pipeline_event(
        db_session,
        pipeline_run_id=run.id,
        sequence=0,
        node_name="extract",
        status="started",
    )
    assert event.node_name == "extract"
    assert event.sequence == 0

    updated = await pipeline_repository.update_pipeline_run(
        db_session,
        pipeline_run_id=run.id,
        status="completed",
        duration_ms=1200,
        outputs={"page_count": 1},
    )
    assert updated is not None
    assert updated.status == "completed"
    assert updated.duration_ms == 1200
    assert updated.outputs_json["page_count"] == 1
