from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.domains.agents.repositories import AgentRunRepository
from app.domains.agents.schemas import ToolCall
from app.domains.agents.services import (
    AgentToolExecutor,
    DocumentIntelligenceToolService,
    ToolRegistry,
    build_default_tool_specs,
    register_document_intelligence_handlers,
)
from app.domains.documents.repositories.documents import DocumentRepository
from app.models import Organization, User
from app.models.enums import AgentRunStatus, DocumentStatus


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False


def _session_factory(session: AsyncSession) -> Callable[[], _SessionScope]:
    def factory() -> _SessionScope:
        return _SessionScope(session)

    return factory


def _principal(
    *, user_id: UUID, organization_id: UUID, role: str = "viewer"
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(user_id),
        organization_id=str(organization_id),
        email="agent-reader@example.com",
        roles=[role],
        auth_provider="app",
    )


@pytest_asyncio.fixture
async def seeded_documents(db_session: AsyncSession) -> dict[str, UUID]:
    organization_a = Organization(name="Doc Tool Org A", slug="doc-tool-org-a")
    organization_b = Organization(name="Doc Tool Org B", slug="doc-tool-org-b")
    db_session.add_all([organization_a, organization_b])
    await db_session.flush()

    user_a = User(
        organization_id=organization_a.id,
        external_auth_id="doc-tools-user-a",
        email="doc-tools-a@example.com",
    )
    user_b = User(
        organization_id=organization_b.id,
        external_auth_id="doc-tools-user-b",
        email="doc-tools-b@example.com",
    )
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    repository = DocumentRepository()
    document_a = await repository.create_document(
        db_session,
        organization_id=organization_a.id,
        uploaded_by_user_id=user_a.id,
        filename="Policy Handbook.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="org-a/policy-handbook.pdf",
        status=DocumentStatus.indexed.value,
    )
    await repository.create_document_chunk(
        db_session,
        document_id=document_a.id,
        chunk_index=0,
        page_number=1,
        text="Policy handbook chunk for org A.",
        token_count=6,
        embedding_model="text-embedding-3-small",
        index_version="v1",
        qdrant_point_id="1f42d6ec-67ef-4f7a-81f0-a6a04ec5a9d5",
    )

    document_b = await repository.create_document(
        db_session,
        organization_id=organization_b.id,
        uploaded_by_user_id=user_b.id,
        filename="Restricted Notes.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="org-b/restricted-notes.pdf",
        status=DocumentStatus.indexed.value,
    )
    await repository.create_document_chunk(
        db_session,
        document_id=document_b.id,
        chunk_index=0,
        page_number=1,
        text="Restricted chunk for org B only.",
        token_count=6,
        embedding_model="text-embedding-3-small",
        index_version="v1",
        qdrant_point_id="ea37f46d-5dc8-4579-93e0-fb4847cc6959",
    )
    await db_session.flush()

    return {
        "org_a_id": organization_a.id,
        "user_a_id": user_a.id,
        "doc_a_id": document_a.id,
        "org_b_id": organization_b.id,
        "user_b_id": user_b.id,
        "doc_b_id": document_b.id,
    }


def _build_executor(
    *,
    db_session: AsyncSession,
    service: DocumentIntelligenceToolService,
) -> AgentToolExecutor:
    registry = ToolRegistry(specs=build_default_tool_specs())
    register_document_intelligence_handlers(registry=registry, service=service)
    return AgentToolExecutor(registry=registry, repository=AgentRunRepository())


@pytest.mark.asyncio
async def test_document_intelligence_read_only_tools_success(
    db_session: AsyncSession,
    seeded_documents: dict[str, UUID],
) -> None:
    service = DocumentIntelligenceToolService(session_factory=_session_factory(db_session))
    executor = _build_executor(db_session=db_session, service=service)
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=seeded_documents["org_a_id"],
        user_id=seeded_documents["user_a_id"],
        status=AgentRunStatus.running.value,
    )
    principal = _principal(
        user_id=seeded_documents["user_a_id"],
        organization_id=seeded_documents["org_a_id"],
    )

    search_call = ToolCall(
        run_id=str(run.id),
        tool_name="search_documents",
        organization_id=str(seeded_documents["org_a_id"]),
        user_id=str(seeded_documents["user_a_id"]),
        arguments={
            "query": "Policy",
            "status": "indexed",
            "sort_by": "updated_at",
            "sort_order": "desc",
            "limit": 20,
            "offset": 0,
        },
    )
    search_result = await executor.execute(
        session=db_session, call=search_call, principal=principal
    )
    assert search_result.success is True
    assert search_result.output is not None
    assert search_result.output["total"] == 1
    assert search_result.output["items"][0]["document_id"] == str(seeded_documents["doc_a_id"])

    detail_call = ToolCall(
        run_id=str(run.id),
        tool_name="get_document_detail",
        organization_id=str(seeded_documents["org_a_id"]),
        user_id=str(seeded_documents["user_a_id"]),
        arguments={"document_id": str(seeded_documents["doc_a_id"])},
    )
    detail_result = await executor.execute(
        session=db_session, call=detail_call, principal=principal
    )
    assert detail_result.success is True
    assert detail_result.output is not None
    assert detail_result.output["document"]["chunk_count"] == 1

    chunks_call = ToolCall(
        run_id=str(run.id),
        tool_name="list_document_chunks",
        organization_id=str(seeded_documents["org_a_id"]),
        user_id=str(seeded_documents["user_a_id"]),
        arguments={"document_id": str(seeded_documents["doc_a_id"]), "limit": 10, "offset": 0},
    )
    chunks_result = await executor.execute(
        session=db_session, call=chunks_call, principal=principal
    )
    assert chunks_result.success is True
    assert chunks_result.output is not None
    assert chunks_result.output["total"] == 1
    assert "preview" in chunks_result.output["items"][0]


@pytest.mark.asyncio
async def test_document_intelligence_validation_failure(
    db_session: AsyncSession,
    seeded_documents: dict[str, UUID],
) -> None:
    service = DocumentIntelligenceToolService(session_factory=_session_factory(db_session))
    executor = _build_executor(db_session=db_session, service=service)
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=seeded_documents["org_a_id"],
        user_id=seeded_documents["user_a_id"],
        status=AgentRunStatus.running.value,
    )
    principal = _principal(
        user_id=seeded_documents["user_a_id"],
        organization_id=seeded_documents["org_a_id"],
    )

    invalid_call = ToolCall(
        run_id=str(run.id),
        tool_name="search_documents",
        organization_id=str(seeded_documents["org_a_id"]),
        user_id=str(seeded_documents["user_a_id"]),
        arguments={"sort_by": "bad_field"},
    )
    result = await executor.execute(session=db_session, call=invalid_call, principal=principal)
    assert result.success is False
    assert result.error is not None
    assert result.error.code.value == "validation_failed"


@pytest.mark.asyncio
async def test_document_intelligence_org_isolation(
    db_session: AsyncSession,
    seeded_documents: dict[str, UUID],
) -> None:
    service = DocumentIntelligenceToolService(session_factory=_session_factory(db_session))
    executor = _build_executor(db_session=db_session, service=service)
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=seeded_documents["org_a_id"],
        user_id=seeded_documents["user_a_id"],
        status=AgentRunStatus.running.value,
    )
    principal = _principal(
        user_id=seeded_documents["user_a_id"],
        organization_id=seeded_documents["org_a_id"],
    )

    call = ToolCall(
        run_id=str(run.id),
        tool_name="get_document_detail",
        organization_id=str(seeded_documents["org_a_id"]),
        user_id=str(seeded_documents["user_a_id"]),
        arguments={"document_id": str(seeded_documents["doc_b_id"])},
    )
    result = await executor.execute(session=db_session, call=call, principal=principal)
    assert result.success is False
    assert result.error is not None
    assert result.error.code.value == "authorization_failed"


class _FailingRetrievalService:
    embedding_model = "text-embedding-3-small"

    async def embed_and_retrieve(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise RuntimeError("token=super-secret")


class _RecordingRerankService:
    candidate_count = 5

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def rerank(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        candidates = kwargs["candidates"]
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    key=candidate.key,
                    rerank_score=0.99,
                    rerank_rank=index + 1,
                )
                for index, candidate in enumerate(candidates[: kwargs["final_top_k"]])
            ]
        )


@pytest.mark.asyncio
async def test_document_intelligence_safe_error_redaction(
    db_session: AsyncSession,
    seeded_documents: dict[str, UUID],
) -> None:
    service = DocumentIntelligenceToolService(
        session_factory=_session_factory(db_session),
        query_retrieval_service=_FailingRetrievalService(),  # type: ignore[arg-type]
    )
    executor = _build_executor(db_session=db_session, service=service)
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=seeded_documents["org_a_id"],
        user_id=seeded_documents["user_a_id"],
        status=AgentRunStatus.running.value,
    )
    principal = _principal(
        user_id=seeded_documents["user_a_id"],
        organization_id=seeded_documents["org_a_id"],
    )

    call = ToolCall(
        run_id=str(run.id),
        tool_name="answer_from_context",
        organization_id=str(seeded_documents["org_a_id"]),
        user_id=str(seeded_documents["user_a_id"]),
        arguments={
            "question": "What is in the policy handbook?",
            "document_ids": [str(seeded_documents["doc_a_id"])],
            "top_k": 3,
            "rerank": False,
        },
    )
    result = await executor.execute(session=db_session, call=call, principal=principal)
    assert result.success is False
    assert result.error is not None
    assert result.error.code.value == "internal_error"
    assert result.error.safe_message == "Tool execution failed unexpectedly."
    assert result.error.details["error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_answer_from_context_passes_query_to_rerank_service(
    db_session: AsyncSession,
    seeded_documents: dict[str, UUID],
) -> None:
    rerank_service = _RecordingRerankService()

    class _StubRetrievalService:
        embedding_model = "text-embedding-3-small"

        async def embed_and_retrieve(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return SimpleNamespace(
                embedding_prompt_tokens=0,
                embedding_model="text-embedding-3-small",
                candidates=[
                    SimpleNamespace(
                        document_id=seeded_documents["doc_a_id"],
                        chunk_id=seeded_documents["doc_a_id"],
                        filename="Policy Handbook.pdf",
                        page_number=1,
                        text="Policy handbook chunk for org A.",
                        similarity_score=0.9,
                    )
                ],
            )

    service = DocumentIntelligenceToolService(
        session_factory=_session_factory(db_session),
        query_retrieval_service=_StubRetrievalService(),  # type: ignore[arg-type]
    )
    service._rerank_service = rerank_service  # type: ignore[attr-defined]
    service._llm_service.generate_answer = AsyncMock(  # type: ignore[assignment]
        return_value=SimpleNamespace(
            answer="The policy handbook says yes.",
            not_found=False,
            citations=[],
            model_name="gpt-4o",
            provider_key="openai",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            approximate_cost_usd=0.0,
            latency_ms=1,
            retry_count=0,
            used_fallback_parser=False,
        )
    )
    executor = _build_executor(db_session=db_session, service=service)
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=seeded_documents["org_a_id"],
        user_id=seeded_documents["user_a_id"],
        status=AgentRunStatus.running.value,
    )
    principal = _principal(
        user_id=seeded_documents["user_a_id"],
        organization_id=seeded_documents["org_a_id"],
    )

    call = ToolCall(
        run_id=str(run.id),
        tool_name="answer_from_context",
        organization_id=str(seeded_documents["org_a_id"]),
        user_id=str(seeded_documents["user_a_id"]),
        arguments={
            "question": "What is in the policy handbook?",
            "document_ids": [str(seeded_documents["doc_a_id"])],
            "top_k": 3,
            "rerank": True,
        },
    )
    result = await executor.execute(session=db_session, call=call, principal=principal)
    assert result.success is True
    assert rerank_service.calls
    assert rerank_service.calls[0]["query"] == "What is in the policy handbook?"
