"""Unit tests for the batched citation loader (R04-03), with fake repository and provenance.

The database-backed paths are covered by tests/test_n_plus_one_guards.py; these fakes make the
grouping and provenance decoration observable without a database.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.application.chat.message_citations import load_message_citations
from app.domains.chat.schemas.chat import ChatCitationResponse
from app.models.chat import ChatMessage
from app.models.citation import Citation
from app.models.enums import ChatRole

pytestmark = pytest.mark.asyncio


class _FakeRepository:
    def __init__(self, rows: dict[UUID, list[tuple[Citation, str | None]]]) -> None:
        self.rows = rows
        self.calls: list[list[UUID]] = []

    async def list_citations_for_messages_with_filename(
        self, _session: Any, *, chat_message_ids: list[UUID]
    ) -> dict[UUID, list[tuple[Citation, str | None]]]:
        self.calls.append(list(chat_message_ids))
        return {key: value for key, value in self.rows.items() if key in chat_message_ids}


class _FakeProvenance:
    def __init__(self) -> None:
        self.calls: list[list[UUID]] = []

    async def load_citation_details_for_documents(
        self, _session: Any, *, organization_id: UUID, document_ids: list[UUID]
    ) -> dict[UUID, str]:
        self.calls.append(list(document_ids))
        return {document_id: f"prov-{document_id}" for document_id in document_ids}


def _message(role: str) -> ChatMessage:
    return ChatMessage(id=uuid4(), chat_session_id=uuid4(), role=role, content="x")


def _citation(message_id: UUID, document_id: UUID, rerank: float | None) -> Citation:
    return Citation(
        id=uuid4(),
        chat_message_id=message_id,
        document_id=document_id,
        chunk_id=uuid4(),
        text_snippet="snippet",
        page_number=2,
        similarity_score=0.4,
        rerank_score=rerank,
    )


async def test_groups_by_message_and_decorates_with_one_provenance_call() -> None:
    user, first, second = (
        _message(ChatRole.user.value),
        _message(ChatRole.assistant.value),
        _message(ChatRole.assistant.value),
    )
    doc_a, doc_b = uuid4(), uuid4()
    c1, c2, c3 = (
        _citation(first.id, doc_a, 0.9),
        _citation(first.id, doc_b, None),
        _citation(second.id, doc_a, None),
    )
    repository = _FakeRepository(
        {first.id: [(c1, "a.pdf"), (c2, None)], second.id: [(c3, "a.pdf")]}
    )
    provenance = _FakeProvenance()
    seen: list[Any] = []

    def decorate(response: ChatCitationResponse, detail: Any) -> ChatCitationResponse:
        seen.append(detail)
        return response.model_copy(update={"filename": f"{response.filename}|{detail}"})

    result = await load_message_citations(
        None,  # type: ignore[arg-type]
        messages=[user, first, second],
        organization_id=uuid4(),
        decorate=decorate,
        repository=repository,  # type: ignore[arg-type]
        provenance_service=provenance,  # type: ignore[arg-type]
    )

    # Only assistant messages are queried, in one call; provenance once with unique IDs.
    assert repository.calls == [[first.id, second.id]]
    assert provenance.calls == [[doc_a, doc_b]]
    assert set(result) == {first.id, second.id}
    assert [c.citation_id for c in result[first.id]] == [str(c1.id), str(c2.id)]
    assert result[first.id][0].score == 0.9
    assert result[first.id][1].score == 0.4
    assert result[first.id][0].filename == f"a.pdf|prov-{doc_a}"
    assert result[second.id][0].filename == f"a.pdf|prov-{doc_a}"
    assert seen == [f"prov-{doc_a}", f"prov-{doc_b}", f"prov-{doc_a}"]


async def test_without_decorate_skips_provenance() -> None:
    answer = _message(ChatRole.assistant.value)
    citation = _citation(answer.id, uuid4(), None)
    repository = _FakeRepository({answer.id: [(citation, "b.txt")]})
    provenance = _FakeProvenance()

    result = await load_message_citations(
        None,  # type: ignore[arg-type]
        messages=[answer],
        organization_id=uuid4(),
        repository=repository,  # type: ignore[arg-type]
        provenance_service=provenance,  # type: ignore[arg-type]
    )

    assert provenance.calls == []
    assert [c.filename for c in result[answer.id]] == ["b.txt"]
