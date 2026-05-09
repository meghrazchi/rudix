from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    PipelineEvent,
    PipelineRun,
    UsageEvent,
    User,
)
from app.models.enums import ChatRole, DocumentStatus, EvaluationRunStatus, OrganizationRole


@pytest.mark.asyncio
async def test_model_creation_roundtrip(db_session: AsyncSession) -> None:
    organization = Organization(name="Acme Inc", slug="acme-inc")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="auth_user_1",
        email="user1@example.com",
        display_name="User One",
    )
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=OrganizationRole.owner.value,
    )
    db_session.add(member)
    await db_session.flush()

    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=user.id,
        filename="spec.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="org/acme/spec.pdf",
        status=DocumentStatus.uploaded.value,
    )
    db_session.add(document)
    await db_session.flush()

    page = DocumentPage(
        document_id=document.id,
        page_number=1,
        text="Page one",
        char_count=8,
    )
    db_session.add(page)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=document.id,
        page_number=1,
        chunk_index=0,
        text="Chunk text",
        token_count=2,
        qdrant_point_id=str(uuid4()),
        embedding_model="text-embedding-3-small",
        index_version="v1",
    )
    db_session.add(chunk)
    await db_session.flush()

    session = ChatSession(
        organization_id=organization.id,
        user_id=user.id,
        title="Support chat",
    )
    db_session.add(session)
    await db_session.flush()

    message = ChatMessage(
        chat_session_id=session.id,
        role=ChatRole.user.value,
        content="What does the spec say?",
    )
    db_session.add(message)
    await db_session.flush()

    citation = Citation(
        chat_message_id=message.id,
        document_id=document.id,
        chunk_id=chunk.id,
        page_number=1,
        text_snippet="Chunk text",
    )
    db_session.add(citation)
    await db_session.flush()

    evaluation_set = EvaluationSet(
        organization_id=organization.id,
        name="Default eval set",
        description="Smoke test set",
    )
    db_session.add(evaluation_set)
    await db_session.flush()

    question = EvaluationQuestion(
        evaluation_set_id=evaluation_set.id,
        question="What is in the document?",
        expected_answer="Chunk text",
        expected_document_id=document.id,
        expected_page_number=1,
        metadata_json={"difficulty": "easy"},
    )
    db_session.add(question)
    await db_session.flush()

    evaluation_run = EvaluationRun(
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.queued.value,
        config={"sample_size": 1},
    )
    db_session.add(evaluation_run)
    await db_session.flush()

    result = EvaluationResult(
        evaluation_run_id=evaluation_run.id,
        evaluation_question_id=question.id,
        generated_answer="Chunk text",
        retrieval_score=0.95,
        details={"passed": True},
    )
    db_session.add(result)
    await db_session.flush()

    pipeline_run = PipelineRun(
        organization_id=organization.id,
        pipeline_type="document.process",
        status="completed",
        inputs_json={"document_id": str(document.id)},
        outputs_json={"chunk_count": 1},
        document_id=document.id,
    )
    db_session.add(pipeline_run)
    await db_session.flush()

    pipeline_event = PipelineEvent(
        pipeline_run_id=pipeline_run.id,
        sequence=0,
        node_name="extract",
        status="completed",
        outputs_json={"page_count": 1},
    )
    db_session.add(pipeline_event)
    await db_session.flush()

    usage = UsageEvent(
        organization_id=organization.id,
        user_id=user.id,
        event_type="chat.completion",
        model_name="gpt-5.4-mini",
        input_tokens=100,
        output_tokens=120,
        metadata_json={"request_id": "req-1"},
    )
    db_session.add(usage)
    await db_session.flush()

    audit = AuditLog(
        organization_id=organization.id,
        user_id=user.id,
        action="document.upload",
        resource_type="document",
        resource_id=document.id,
        metadata_json={"filename": document.filename},
    )
    db_session.add(audit)
    await db_session.commit()

    document_count = await db_session.scalar(select(func.count(Document.id)))
    message_count = await db_session.scalar(select(func.count(ChatMessage.id)))
    pipeline_event_count = await db_session.scalar(select(func.count(PipelineEvent.id)))
    assert document_count == 1
    assert message_count == 1
    assert pipeline_event_count == 1
