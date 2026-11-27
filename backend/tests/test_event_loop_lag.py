"""Blocking storage, broker, and Qdrant calls must not stall the event loop (R04-11)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.clients import minio_client as minio_module
from app.core.config import AuthProvider, settings
from app.core.loop_lag import LoopLagMonitor
from app.db.session import get_db_session
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.malware_scan import MalwareScanResult
from app.interfaces.http import documents as documents_api
from app.main import app
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.workers.dispatch import enqueue

BLOCK_SECONDS = 0.3
MAX_ALLOWED_LAG = 0.1


class SlowBody:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._pos = 0

    def read(self, amt: int | None = None) -> bytes:
        time.sleep(BLOCK_SECONDS)
        end = len(self._content) if amt is None else self._pos + amt
        chunk = self._content[self._pos : end]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        pass


class SlowMinio:
    def put_object(self, **kwargs: Any) -> None:
        time.sleep(BLOCK_SECONDS)

    def delete_object(self, **kwargs: Any) -> None:
        time.sleep(BLOCK_SECONDS)

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        time.sleep(BLOCK_SECONDS)
        return {"Body": SlowBody(b"%PDF-1.7\nslow")}


class FastMinio:
    def put_object(self, **kwargs: Any) -> None:
        return None

    def delete_object(self, **kwargs: Any) -> None:
        return None


class SlowQdrant:
    def search(self, **kwargs: Any) -> list[Any]:
        time.sleep(BLOCK_SECONDS)
        return []


class _EmbedResponse:
    vectors: ClassVar[list[list[float]]] = [[0.0, 0.0, 0.0]]
    prompt_tokens = 1


class FakeEmbeddingProvider:
    async def embed(self, request: Any) -> _EmbedResponse:
        return _EmbedResponse()


class _TaskResult:
    id = "task-1"


class QuickTask:
    def delay(self, *args: Any, **kwargs: Any) -> _TaskResult:
        return _TaskResult()


class SlowTask:
    def delay(self, *args: Any, **kwargs: Any) -> str:
        time.sleep(BLOCK_SECONDS)
        return "queued"


class _Scan:
    async def scan_bytes(self, *, content: bytes) -> MalwareScanResult:
        return MalwareScanResult(status="clean", duration_ms=1)


@pytest_asyncio.fixture
async def monitor() -> AsyncIterator[LoopLagMonitor]:
    mon = LoopLagMonitor(interval_ms=10)
    mon.start()
    await asyncio.sleep(0.05)
    mon.reset()
    yield mon
    await mon.stop()


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client
    app.dependency_overrides.clear()


async def _seed(db_session: AsyncSession) -> tuple[User, Organization]:
    org = Organization(name="Lag Org", slug=f"lag-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"lag-{uuid4().hex[:8]}",
        email=f"lag-{uuid4().hex[:8]}@example.com",
        display_name="Lag User",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value
        )
    )
    await db_session.commit()
    return user, org


def _headers(user: User, org: Organization) -> dict[str, str]:
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}


@pytest.mark.asyncio
async def test_upload_does_not_block_event_loop(
    client: AsyncClient,
    db_session: AsyncSession,
    monitor: LoopLagMonitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    monkeypatch.setattr(documents_api, "malware_scan_service", _Scan())
    monkeypatch.setattr(documents_api, "process_document", QuickTask())

    # Warm up first: the first upload lazily imports heavy modules, which is real
    # (one-off) blocking unrelated to the I/O under test.
    monkeypatch.setattr(minio_module, "minio_client", FastMinio())
    warmup = await client.post(
        "/api/v1/documents/upload",
        headers=_headers(user, org),
        files={"file": ("warm.txt", b"warm-up text", "text/plain")},
    )
    assert warmup.status_code == 201, warmup.text
    monkeypatch.setattr(minio_module, "minio_client", SlowMinio())
    monitor.reset()

    started = time.perf_counter()
    response = await client.post(
        "/api/v1/documents/upload",
        headers=_headers(user, org),
        files={"file": ("lag.txt", b"plain text", "text/plain")},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 201, response.text
    assert elapsed >= BLOCK_SECONDS  # the slow put_object really ran
    assert monitor.max_lag_seconds < MAX_ALLOWED_LAG


@pytest.mark.asyncio
async def test_download_does_not_block_event_loop(
    client: AsyncClient,
    db_session: AsyncSession,
    monitor: LoopLagMonitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed(db_session)
    document = await DocumentRepository().create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="slow.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{uuid4()}.pdf",
        status=DocumentStatus.indexed.value,
    )
    await db_session.commit()
    monkeypatch.setattr(minio_module, "minio_client", SlowMinio())

    response = await client.get(
        f"/api/v1/documents/{document.id}/download", headers=_headers(user, org)
    )

    assert response.status_code == 200, response.text
    assert response.content == b"%PDF-1.7\nslow"
    assert monitor.max_lag_seconds < MAX_ALLOWED_LAG


@pytest.mark.asyncio
async def test_embed_and_retrieve_does_not_block_event_loop(monitor: LoopLagMonitor) -> None:
    service = QueryRetrievalService(
        embedding_model="test-model",
        qdrant_collection="documents",
        vector_size=3,
        embedding_provider=FakeEmbeddingProvider(),  # type: ignore[arg-type]
        qdrant_client=SlowQdrant(),  # type: ignore[arg-type]
    )

    result = await service.embed_and_retrieve(
        question="what is rudix?",
        organization_id=UUID(int=1),
        document_ids=None,
        initial_top_k=5,
    )

    assert result.candidates == []
    assert monitor.max_lag_seconds < MAX_ALLOWED_LAG


@pytest.mark.asyncio
async def test_enqueue_offloads_blocking_delay(monitor: LoopLagMonitor) -> None:
    result = await enqueue(SlowTask(), "a", key="b")

    assert result == "queued"
    assert monitor.max_lag_seconds < MAX_ALLOWED_LAG


@pytest.mark.asyncio
async def test_enqueue_propagates_broker_errors() -> None:
    class Broken:
        def delay(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("broker down")

    with pytest.raises(ConnectionError):
        await enqueue(Broken())


@pytest.mark.asyncio
async def test_control_blocking_call_on_loop_is_detected(monitor: LoopLagMonitor) -> None:
    """Proves the probe: a blocking call directly on the loop shows up as lag."""
    SlowQdrant().search()
    await asyncio.sleep(0.05)

    assert monitor.max_lag_seconds >= 0.25
