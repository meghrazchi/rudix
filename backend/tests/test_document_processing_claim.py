from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Collection
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.repositories.processing_claims import (
    NON_PROCESSABLE_STATUSES,
    PROCESS_SKIP_STATUSES,
    REINDEX_FORBIDDEN_STATUSES,
    ClaimOutcome,
    ClaimResult,
    DocumentProcessingClaimRepository,
)
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User
from app.workers import status_tracking

pytestmark = pytest.mark.both_dialects

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
STALE_BEFORE = NOW - timedelta(hours=1)

_repo = DocumentProcessingClaimRepository()

MakeDocument = Callable[..., Awaitable[Document]]


def _naive(value: datetime | None) -> datetime | None:
    # SQLite drops tzinfo on round-trip; compare in naive UTC.
    return value.replace(tzinfo=None) if value is not None else None


@pytest_asyncio.fixture
async def make_document(db_session: AsyncSession) -> MakeDocument:
    org = Organization(name="Claim Org", slug=f"claim-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"claim-user-{uuid4().hex[:8]}",
        email=f"claim-{uuid4().hex[:8]}@example.com",
        display_name="Claim User",
    )
    db_session.add(user)
    await db_session.flush()

    async def _make(
        status: str = DocumentStatus.uploaded.value,
        *,
        task_id: str | None = None,
        started_at: datetime | None = None,
        reap_count: int = 0,
    ) -> Document:
        document = Document(
            organization_id=org.id,
            uploaded_by_user_id=user.id,
            filename="claim.txt",
            file_type="txt",
            storage_bucket="documents",
            storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
            status=status,
            processing_task_id=task_id,
            processing_started_at=started_at,
            processing_reap_count=reap_count,
        )
        db_session.add(document)
        await db_session.commit()
        return document

    return _make


async def _reload(session: AsyncSession, document: Document) -> Document:
    await session.refresh(document)
    return document


async def _claim(
    session: AsyncSession,
    document: Document,
    task_id: str,
    *,
    now: datetime = NOW,
    force: bool = False,
    skip_statuses: Collection[str] = (),
    forbidden_statuses: Collection[str] = (),
) -> ClaimResult:
    result = await _repo.claim_for_processing(
        session,
        document_id=document.id,
        task_id=task_id,
        now=now,
        stale_before=STALE_BEFORE,
        force=force,
        skip_statuses=skip_statuses,
        forbidden_statuses=forbidden_statuses,
    )
    await session.commit()
    return result


@pytest.mark.asyncio
async def test_uploaded_document_is_claimed(
    db_session: AsyncSession, make_document: MakeDocument
) -> None:
    document = await make_document()
    result = await _claim(db_session, document, "task-a", skip_statuses=PROCESS_SKIP_STATUSES)

    assert result.outcome == ClaimOutcome.claimed
    row = await _reload(db_session, document)
    assert row.status == DocumentStatus.processing.value
    assert row.processing_task_id == "task-a"
    assert _naive(row.processing_started_at) == _naive(NOW)
    assert row.error_message is None


@pytest.mark.asyncio
async def test_second_task_with_different_id_is_held(
    db_session: AsyncSession,
    make_document: MakeDocument,
) -> None:
    document = await make_document()
    await _claim(db_session, document, "task-a")
    result = await _claim(db_session, document, "task-b", skip_statuses=PROCESS_SKIP_STATUSES)

    assert result.outcome == ClaimOutcome.held
    assert result.current_status == DocumentStatus.processing.value
    row = await _reload(db_session, document)
    assert row.processing_task_id == "task-a"


@pytest.mark.asyncio
async def test_same_task_id_reclaims_and_refreshes_started_at(
    db_session: AsyncSession,
    make_document: MakeDocument,
) -> None:
    document = await make_document()
    await _claim(db_session, document, "task-a")
    later = NOW + timedelta(minutes=5)
    result = await _claim(db_session, document, "task-a", now=later)

    assert result.outcome == ClaimOutcome.claimed
    row = await _reload(db_session, document)
    assert row.processing_task_id == "task-a"
    assert _naive(row.processing_started_at) == _naive(later)


@pytest.mark.asyncio
async def test_stale_claim_is_taken_over(
    db_session: AsyncSession, make_document: MakeDocument
) -> None:
    document = await make_document(
        DocumentStatus.processing.value,
        task_id="task-dead",
        started_at=STALE_BEFORE - timedelta(seconds=1),
    )
    result = await _claim(db_session, document, "task-b")

    assert result.outcome == ClaimOutcome.claimed
    row = await _reload(db_session, document)
    assert row.processing_task_id == "task-b"


@pytest.mark.asyncio
async def test_processing_without_started_at_is_claimable(
    db_session: AsyncSession,
    make_document: MakeDocument,
) -> None:
    document = await make_document(DocumentStatus.processing.value)
    result = await _claim(db_session, document, "task-b")

    assert result.outcome == ClaimOutcome.claimed


@pytest.mark.asyncio
async def test_indexed_is_held_unless_forced(
    db_session: AsyncSession, make_document: MakeDocument
) -> None:
    document = await make_document(DocumentStatus.indexed.value)
    held = await _claim(db_session, document, "task-a", skip_statuses=PROCESS_SKIP_STATUSES)
    assert held.outcome == ClaimOutcome.held
    assert held.current_status == DocumentStatus.indexed.value

    forced = await _claim(
        db_session, document, "task-a", force=True, skip_statuses=PROCESS_SKIP_STATUSES
    )
    assert forced.outcome == ClaimOutcome.claimed
    row = await _reload(db_session, document)
    assert row.status == DocumentStatus.processing.value


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(NON_PROCESSABLE_STATUSES))
async def test_non_processable_status_is_held_unless_forced(
    db_session: AsyncSession, make_document: MakeDocument, status: str
) -> None:
    document = await make_document(status)
    held = await _claim(db_session, document, "task-a", skip_statuses=PROCESS_SKIP_STATUSES)
    assert held.outcome == ClaimOutcome.held
    assert held.current_status == status
    assert (await _reload(db_session, document)).status == status

    # force=True bypasses the skip list entirely (documents current behaviour).
    forced = await _claim(
        db_session, document, "task-a", force=True, skip_statuses=PROCESS_SKIP_STATUSES
    )
    assert forced.outcome == ClaimOutcome.claimed


@pytest.mark.asyncio
async def test_process_document_skips_non_processable_status(
    db_session: AsyncSession,
    make_document: MakeDocument,
    patched_status_session: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import document_tasks

    document = await make_document(DocumentStatus.quarantined.value)
    claim = await status_tracking._claim_document_for_processing_async(
        str(document.id), task_id="task-a", force=False, skip_statuses=PROCESS_SKIP_STATUSES
    )
    monkeypatch.setattr(document_tasks, "claim_document_for_processing", lambda *a, **k: claim)

    result = document_tasks.process_document.run(str(document.id))

    assert result == {"document_id": str(document.id), "status": "skipped"}
    assert (await _reload(db_session, document)).status == DocumentStatus.quarantined.value


@pytest.mark.asyncio
async def test_forced_claim_takes_over_live_holder(
    db_session: AsyncSession,
    make_document: MakeDocument,
) -> None:
    document = await make_document(
        DocumentStatus.processing.value, task_id="task-live", started_at=NOW
    )
    result = await _claim(db_session, document, "task-admin", force=True)

    assert result.outcome == ClaimOutcome.claimed
    row = await _reload(db_session, document)
    assert row.processing_task_id == "task-admin"


@pytest.mark.asyncio
async def test_reindex_rules(db_session: AsyncSession, make_document: MakeDocument) -> None:
    indexed = await make_document(DocumentStatus.indexed.value)
    claimed = await _claim(
        db_session, indexed, "task-r", forbidden_statuses=REINDEX_FORBIDDEN_STATUSES
    )
    assert claimed.outcome == ClaimOutcome.claimed

    for status in (DocumentStatus.deleted.value, DocumentStatus.deleting.value):
        document = await make_document(status)
        for force in (False, True):
            result = await _claim(
                db_session,
                document,
                "task-r",
                force=force,
                forbidden_statuses=REINDEX_FORBIDDEN_STATUSES,
            )
            assert result.outcome == ClaimOutcome.held
            assert result.current_status == status
        row = await _reload(db_session, document)
        assert row.status == status


@pytest.mark.asyncio
async def test_missing_document_is_not_found(db_session: AsyncSession) -> None:
    result = await _repo.claim_for_processing(
        db_session,
        document_id=uuid4(),
        task_id="task-a",
        now=NOW,
        stale_before=STALE_BEFORE,
        force=True,
    )
    assert result.outcome == ClaimOutcome.not_found
    assert result.current_status is None


@pytest.mark.asyncio
async def test_update_document_status_clears_processing_claim(
    db_session: AsyncSession,
    make_document: MakeDocument,
) -> None:
    document = await make_document(
        DocumentStatus.processing.value, task_id="task-a", started_at=NOW, reap_count=2
    )
    updated = await DocumentRepository().update_document_status(
        db_session,
        document_id=document.id,
        status=DocumentStatus.indexed.value,
        clear_processing_claim=True,
    )
    await db_session.commit()

    assert updated is not None
    row = await _reload(db_session, document)
    assert row.status == DocumentStatus.indexed.value
    assert row.processing_task_id is None
    assert row.processing_started_at is None
    assert row.processing_reap_count == 0


@pytest.mark.asyncio
async def test_update_document_status_keeps_claim_by_default(
    db_session: AsyncSession,
    make_document: MakeDocument,
) -> None:
    document = await make_document(DocumentStatus.processing.value, task_id="task-a", reap_count=1)
    await DocumentRepository().update_document_status(
        db_session, document_id=document.id, status=DocumentStatus.processing.value
    )
    await db_session.commit()

    row = await _reload(db_session, document)
    assert row.processing_task_id == "task-a"
    assert row.processing_reap_count == 1


@pytest.fixture
def patched_status_session(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(status_tracking, "SessionLocal", session_factory)


@pytest.mark.asyncio
async def test_owner_guard_rejects_non_owner(
    db_session: AsyncSession,
    make_document: MakeDocument,
    patched_status_session: None,
) -> None:
    document = await make_document(
        DocumentStatus.processing.value, task_id="task-new", started_at=NOW
    )
    updated = await status_tracking._set_document_status_async(
        str(document.id),
        status=DocumentStatus.failed,
        error_message="boom",
        clear_processing_claim=True,
        owner_task_id="task-old",
    )

    assert updated is False
    row = await _reload(db_session, document)
    assert row.status == DocumentStatus.processing.value
    assert row.processing_task_id == "task-new"
    assert row.error_message is None


@pytest.mark.asyncio
@pytest.mark.parametrize("holder", ["task-a", None])
async def test_owner_guard_allows_owner_or_unclaimed(
    db_session: AsyncSession,
    make_document: MakeDocument,
    patched_status_session: None,
    holder: str | None,
) -> None:
    document = await make_document(
        DocumentStatus.processing.value, task_id=holder, started_at=NOW, reap_count=1
    )
    updated = await status_tracking._set_document_status_async(
        str(document.id),
        status=DocumentStatus.failed,
        error_message="boom",
        clear_processing_claim=True,
        owner_task_id="task-a",
    )

    assert updated is True
    row = await _reload(db_session, document)
    assert row.status == DocumentStatus.failed.value
    assert row.error_message == "boom"
    assert row.processing_task_id is None
    assert row.processing_started_at is None
    assert row.processing_reap_count == 0


@pytest.mark.asyncio
async def test_owner_guard_returns_false_for_missing_document(
    patched_status_session: None,
) -> None:
    updated = await status_tracking._set_document_status_async(
        str(uuid4()), status=DocumentStatus.failed, owner_task_id="task-a"
    )
    assert updated is False


@pytest.mark.asyncio
async def test_clear_claim_is_not_short_circuited_when_status_unchanged(
    db_session: AsyncSession,
    make_document: MakeDocument,
    patched_status_session: None,
) -> None:
    document = await make_document(DocumentStatus.failed.value, task_id="task-a", started_at=NOW)
    updated = await status_tracking._set_document_status_async(
        str(document.id), status=DocumentStatus.failed, clear_processing_claim=True
    )

    assert updated is True
    row = await _reload(db_session, document)
    assert row.processing_task_id is None
    assert row.processing_started_at is None

    # Nothing left to clear: the idempotent short-circuit applies again.
    again = await status_tracking._set_document_status_async(
        str(document.id), status=DocumentStatus.failed, clear_processing_claim=True
    )
    assert again is True


@pytest.mark.asyncio
async def test_claim_wrapper_uses_configured_stale_window(
    db_session: AsyncSession,
    make_document: MakeDocument,
    patched_status_session: None,
) -> None:
    fresh = datetime.now(UTC) - timedelta(seconds=60)
    document = await make_document(
        DocumentStatus.processing.value, task_id="task-live", started_at=fresh
    )

    held = await status_tracking._claim_document_for_processing_async(
        str(document.id), task_id="task-other", force=False, skip_statuses=PROCESS_SKIP_STATUSES
    )
    assert held.outcome == ClaimOutcome.held

    reentered = await status_tracking._claim_document_for_processing_async(
        str(document.id), task_id="task-live", force=False
    )
    assert reentered.outcome == ClaimOutcome.claimed

    with pytest.raises(ValueError):
        await status_tracking._claim_document_for_processing_async(
            "not-a-uuid", task_id="task-a", force=False
        )
