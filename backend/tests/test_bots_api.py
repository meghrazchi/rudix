import os
from dataclasses import dataclass
from typing import ClassVar
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from httpx import Request as HttpxRequest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.clients import qdrant_client as qdrant_module
from app.clients import redis_client as redis_module
from app.core.config import AuthProvider, RateLimitRedisFailureMode, settings
from app.db.session import get_db_session
from app.domains.ai.providers.factory import default_provider_factory
from app.domains.ai.providers.protocols import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.domains.documents.repositories.documents import DocumentRepository
from app.interfaces.http import chat as chat_api
from app.main import app
from app.models.bot import BotInstallation, BotUserMapping
from app.models.chat import ChatSession
from app.models.collection import Collection, CollectionDocument
from app.models.document import DocumentChunk
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


@dataclass
class FakeQdrantResult:
    score: float
    payload: dict[str, object]


class FakeQdrantClient:
    def __init__(self, results: list[FakeQdrantResult]) -> None:
        self._results = results
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> list[FakeQdrantResult]:
        self.calls.append(kwargs)
        return list(self._results)


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        return count

    async def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self.expiries.get(key, 60)


class FakeAsyncHttpClient:
    posts: ClassVar[list[dict[str, object]]] = []
    response_json: ClassVar[dict[str, object]] = {"ok": True}

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> "FakeAsyncHttpClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> Response:
        self.posts.append(
            {
                "url": url,
                "json": json,
                "headers": headers or {},
                "data": data,
            }
        )
        return Response(200, json=self.response_json, request=HttpxRequest("POST", url))


class _FakeChatProvider:
    def __init__(self, *, answer: str) -> None:
        self.answer = answer
        self.calls: list[ChatCompletionRequest] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls.append(request)
        return ChatCompletionResponse(
            content=self.answer,
            model=settings.openai_llm_model,
            prompt_tokens=31,
            completion_tokens=17,
            total_tokens=48,
            latency_ms=5,
        )


class _FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.calls.append(request)
        return EmbeddingResponse(
            vectors=[[0.01] * settings.qdrant_vector_size],
            model=request.model or settings.openai_embedding_model,
            prompt_tokens=7,
            total_tokens=7,
            latency_ms=1,
        )


@pytest_asyncio.fixture
async def bot_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_collaboration_bots", True)
    monkeypatch.setattr(settings, "feature_enable_embeddings", True)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(settings, "bot_slack_signing_secret", None)
    monkeypatch.setattr(settings, "bot_teams_shared_secret", None)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    qdrant_module.qdrant_client = None
    redis_module.redis_client = None
    chat_api._llm_service._provider = None
    chat_api._query_retrieval_service._embedding_provider = None
    default_provider_factory._chat_providers.clear()


def _inject_providers(monkeypatch: pytest.MonkeyPatch, *, answer: str) -> None:
    chat_provider = _FakeChatProvider(answer=answer)
    default_provider_factory._chat_providers.clear()
    default_provider_factory._chat_providers[settings.llm_default_provider] = chat_provider
    monkeypatch.setattr(chat_api._llm_service, "_provider", chat_provider)
    monkeypatch.setattr(
        chat_api._query_retrieval_service,
        "_embedding_provider",
        _FakeEmbeddingProvider(),
    )


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.member,
) -> tuple[Organization, User, User]:
    org = Organization(name=f"Bot Org {uuid4().hex[:8]}", slug=f"bot-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    admin = User(
        organization_id=org.id,
        external_auth_id=f"bot-admin-{uuid4().hex[:8]}",
        email=f"bot-admin-{uuid4().hex[:8]}@example.com",
        display_name="Bot Admin",
    )
    member = User(
        organization_id=org.id,
        external_auth_id=f"bot-member-{uuid4().hex[:8]}",
        email=f"bot-member-{uuid4().hex[:8]}@example.com",
        display_name="Bot Member",
    )
    db_session.add_all([admin, member])
    await db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(
                organization_id=org.id,
                user_id=admin.id,
                role=OrganizationRole.admin.value,
            ),
            OrganizationMember(
                organization_id=org.id,
                user_id=member.id,
                role=role.value,
            ),
        ]
    )
    await db_session.commit()
    return org, admin, member


async def _seed_document_with_chunk(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
    filename: str,
    text: str,
) -> tuple[object, DocumentChunk]:
    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename=filename,
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{filename}-{uuid4()}.pdf",
        status="indexed",
    )
    chunk = await repository.create_document_chunk(
        db_session,
        document_id=document.id,
        page_number=1,
        chunk_index=0,
        text=text,
        token_count=50,
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
        qdrant_point_id=f"{document.id}:{settings.document_index_version}:0",
    )
    await db_session.commit()
    await db_session.refresh(document)
    await db_session.refresh(chunk)
    return document, chunk


async def _seed_installation_and_mapping(
    db_session: AsyncSession,
    *,
    organization: Organization,
    user: User,
    provider: str = "slack",
    external_workspace_id: str = "T-BOT",
    external_tenant_id: str = "",
    external_team_id: str = "",
    external_user_id: str = "U-BOT",
    status: str = "enabled",
    default_source_scope: dict | None = None,
) -> BotInstallation:
    installation = BotInstallation(
        organization_id=organization.id,
        provider=provider,
        external_workspace_id=external_workspace_id,
        external_tenant_id=external_tenant_id,
        external_team_id=external_team_id,
        display_name="Rudix Bot",
        status=status,
        default_source_scope_json=default_source_scope or {},
        config_json={},
    )
    db_session.add(installation)
    await db_session.flush()
    db_session.add(
        BotUserMapping(
            organization_id=organization.id,
            installation_id=installation.id,
            rudix_user_id=user.id,
            external_user_id=external_user_id,
            status="active",
        )
    )
    await db_session.commit()
    await db_session.refresh(installation)
    return installation


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


def _sync_bot_headers() -> dict[str, str]:
    return {"X-Rudix-Bot-Sync": "true"}


@pytest.mark.asyncio
async def test_admin_can_install_bot_and_map_external_user(
    bot_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, admin, member = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=admin.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    create_response = await bot_client.post(
        "/api/v1/admin/bots/installations",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "provider": "slack",
            "external_workspace_id": "T-BOT",
            "display_name": "Rudix Slack",
            "default_source_scope": {"mode": "all"},
        },
    )

    assert create_response.status_code == 201
    installation_id = create_response.json()["id"]

    mapping_response = await bot_client.put(
        f"/api/v1/admin/bots/installations/{installation_id}/mappings",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "external_user_id": "U-BOT",
            "rudix_user_id": str(member.id),
            "external_email": "member@example.com",
        },
    )

    assert mapping_response.status_code == 200
    assert mapping_response.json()["external_user_id"] == "U-BOT"
    audit_actions = {
        row.action for row in (await db_session.execute(select(AuditLog))).scalars().all()
    }
    assert "bots.installation.created" in audit_actions
    assert "bots.user_mapping.upserted" in audit_actions


@pytest.mark.asyncio
async def test_admin_can_store_encrypted_bot_credential_without_exposing_secret(
    bot_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, admin, member = await _seed_org_user(db_session)
    installation = await _seed_installation_and_mapping(
        db_session,
        organization=org,
        user=member,
    )
    token = create_app_access_token(
        subject=admin.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    credential_response = await bot_client.put(
        f"/api/v1/admin/bots/installations/{installation.id}/credential",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"bot_token": "xoxb-secret-token", "scopes": ["chat:write", "chat:write"]},
    )

    assert credential_response.status_code == 200
    credential = credential_response.json()
    assert credential["configured"] is True
    assert credential["fingerprint"]
    assert credential["scopes"] == ["chat:write"]
    assert "xoxb-secret-token" not in credential_response.text

    list_response = await bot_client.get(
        "/api/v1/admin/bots/installations",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert list_response.status_code == 200
    assert "xoxb-secret-token" not in list_response.text
    refreshed = await db_session.get(BotInstallation, installation.id)
    assert refreshed is not None
    assert refreshed.encrypted_bot_token is not None
    assert "xoxb-secret-token" not in refreshed.encrypted_bot_token


@pytest.mark.asyncio
async def test_admin_installation_config_rejects_secret_like_keys(
    bot_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, admin, _ = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=admin.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await bot_client.post(
        "/api/v1/admin/bots/installations",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "provider": "slack",
            "external_workspace_id": "T-BOT",
            "config": {"oauth": {"bot_token": "xoxb-secret-token"}},
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_slack_oauth_callback_creates_installation_with_encrypted_token(
    bot_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, admin, _ = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=admin.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    monkeypatch.setattr(settings, "bot_slack_client_id", "123.abc")
    monkeypatch.setattr(settings, "bot_slack_client_secret", SecretStr("client-secret"))
    FakeAsyncHttpClient.posts = []
    FakeAsyncHttpClient.response_json = {
        "ok": True,
        "access_token": "xoxb-oauth-secret",
        "scope": "app_mentions:read,chat:write,commands",
        "team": {"id": "T-OAUTH", "name": "OAuth Workspace"},
        "enterprise": None,
        "bot_user_id": "B-OAUTH",
        "app_id": "A-OAUTH",
    }
    monkeypatch.setattr(
        "app.domains.bots.services.oauth.httpx.AsyncClient",
        FakeAsyncHttpClient,
    )

    start_response = await bot_client.post(
        "/api/v1/admin/bots/slack/oauth/start",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={},
    )
    assert start_response.status_code == 200
    state = start_response.json()["state"]

    callback_response = await bot_client.get(
        "/api/v1/bots/slack/oauth/callback",
        params={"state": state, "code": "oauth-code"},
    )

    assert callback_response.status_code == 200
    payload = callback_response.json()
    assert payload["ok"] is True
    assert payload["installation"]["external_workspace_id"] == "T-OAUTH"
    assert payload["credential"]["configured"] is True
    assert "xoxb-oauth-secret" not in callback_response.text
    installation = (
        await db_session.execute(
            select(BotInstallation).where(BotInstallation.external_workspace_id == "T-OAUTH")
        )
    ).scalar_one()
    assert installation.encrypted_bot_token is not None
    assert "xoxb-oauth-secret" not in installation.encrypted_bot_token


@pytest.mark.asyncio
async def test_slack_ask_uses_mapping_default_collection_scope_and_safe_citations(
    bot_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, member = await _seed_org_user(db_session)
    allowed_doc, allowed_chunk = await _seed_document_with_chunk(
        db_session,
        organization=org,
        uploader=member,
        filename="policy.pdf",
        text="Employees receive twenty days of annual leave.",
    )
    blocked_doc, blocked_chunk = await _seed_document_with_chunk(
        db_session,
        organization=org,
        uploader=member,
        filename="restricted.pdf",
        text="The acquisition codename is confidential.",
    )
    collection = Collection(
        organization_id=org.id,
        owner_id=member.id,
        name="HR",
        access_policy="org_wide",
    )
    db_session.add(collection)
    await db_session.flush()
    db_session.add(CollectionDocument(collection_id=collection.id, document_id=allowed_doc.id))
    await db_session.commit()

    await _seed_installation_and_mapping(
        db_session,
        organization=org,
        user=member,
        default_source_scope={"mode": "collections", "collection_ids": [str(collection.id)]},
    )
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.99,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(blocked_doc.id),
                    "chunk_id": str(blocked_chunk.id),
                    "filename": "restricted.pdf",
                    "page_number": 1,
                    "text": "The acquisition codename is confidential.",
                },
            ),
            FakeQdrantResult(
                score=0.92,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(allowed_doc.id),
                    "chunk_id": str(allowed_chunk.id),
                    "filename": "policy.pdf",
                    "page_number": 1,
                    "text": "Employees receive twenty days of annual leave.",
                },
            ),
        ]
    )
    _inject_providers(
        monkeypatch,
        answer=(
            '{"answer":"Employees receive twenty days of annual leave.",'
            '"not_found":false,"citations":[]}'
        ),
    )

    response = await bot_client.post(
        "/api/v1/bots/slack/events",
        headers=_sync_bot_headers(),
        json={
            "type": "event_callback",
            "team_id": "T-BOT",
            "event": {
                "type": "app_mention",
                "user": "U-BOT",
                "channel": "C-BOT",
                "text": "How much annual leave is provided?",
                "ts": "1710000000.0001",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["not_found"] is False
    assert "twenty days" in payload["text"]
    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["document_id"] == str(allowed_doc.id)
    assert payload["citations"][0]["chunk_id"] == str(allowed_chunk.id)
    assert "/documents/" in payload["citations"][0]["url"]
    assert "restricted" not in payload["text"].lower()
    assert str(blocked_doc.id) not in payload["text"]

    audit_actions = [
        row.action for row in (await db_session.execute(select(AuditLog))).scalars().all()
    ]
    assert "bots.ask.requested" in audit_actions
    assert "bots.ask.completed" in audit_actions
    assert "chat.query.completed" in audit_actions


@pytest.mark.asyncio
async def test_slack_slash_command_acknowledges_then_posts_final_response(
    bot_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, member = await _seed_org_user(db_session)
    document, chunk = await _seed_document_with_chunk(
        db_session,
        organization=org,
        uploader=member,
        filename="policy.pdf",
        text="Employees receive twenty days of annual leave.",
    )
    await _seed_installation_and_mapping(db_session, organization=org, user=member)
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.92,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(document.id),
                    "chunk_id": str(chunk.id),
                    "filename": "policy.pdf",
                    "page_number": 1,
                    "text": "Employees receive twenty days of annual leave.",
                },
            )
        ]
    )
    _inject_providers(
        monkeypatch,
        answer=(
            '{"answer":"Employees receive twenty days of annual leave.",'
            '"not_found":false,"citations":[]}'
        ),
    )
    FakeAsyncHttpClient.posts = []
    FakeAsyncHttpClient.response_json = {"ok": True}
    monkeypatch.setattr(
        "app.domains.bots.services.delivery.httpx.AsyncClient",
        FakeAsyncHttpClient,
    )

    response = await bot_client.post(
        "/api/v1/bots/slack/events",
        data={
            "team_id": "T-BOT",
            "user_id": "U-BOT",
            "channel_id": "C-BOT",
            "command": "/rudix",
            "text": "How much leave?",
            "response_url": "https://hooks.slack.test/response/123",
        },
    )

    assert response.status_code == 200
    ack = response.json()
    assert ack["ok"] is True
    assert "searching" in ack["text"]
    assert FakeAsyncHttpClient.posts
    final_post = FakeAsyncHttpClient.posts[-1]
    assert final_post["url"] == "https://hooks.slack.test/response/123"
    final_payload = final_post["json"]
    assert isinstance(final_payload, dict)
    assert final_payload["response_type"] == "in_channel"
    assert "twenty days" in str(final_payload["text"])
    assert "/documents/" in str(final_payload["text"])


@pytest.mark.asyncio
async def test_teams_ask_uses_mapped_user_and_safe_citations(
    bot_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, member = await _seed_org_user(db_session)
    document, chunk = await _seed_document_with_chunk(
        db_session,
        organization=org,
        uploader=member,
        filename="handbook.pdf",
        text="Rudix reimburses approved travel within thirty days.",
    )
    await _seed_installation_and_mapping(
        db_session,
        organization=org,
        user=member,
        provider="teams",
        external_workspace_id="TENANT-BOT",
        external_tenant_id="TENANT-BOT",
        external_team_id="TEAM-BOT",
        external_user_id="AAD-BOT",
    )
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.94,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(document.id),
                    "chunk_id": str(chunk.id),
                    "filename": "handbook.pdf",
                    "page_number": 2,
                    "text": "Rudix reimburses approved travel within thirty days.",
                },
            )
        ]
    )
    _inject_providers(
        monkeypatch,
        answer=(
            '{"answer":"Approved travel is reimbursed within thirty days.",'
            '"not_found":false,"citations":[]}'
        ),
    )

    response = await bot_client.post(
        "/api/v1/bots/teams/events",
        headers=_sync_bot_headers(),
        json={
            "type": "message",
            "text": "When is approved travel reimbursed?",
            "channelData": {
                "tenant": {"id": "TENANT-BOT"},
                "team": {"id": "TEAM-BOT"},
            },
            "conversation": {"id": "CONVERSATION-BOT"},
            "from": {"aadObjectId": "AAD-BOT"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "teams"
    assert "thirty days" in payload["text"]
    assert payload["citations"][0]["document_id"] == str(document.id)
    assert payload["citations"][0]["chunk_id"] == str(chunk.id)


@pytest.mark.asyncio
async def test_teams_event_acknowledges_then_posts_final_response(
    bot_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, admin, member = await _seed_org_user(db_session)
    document, chunk = await _seed_document_with_chunk(
        db_session,
        organization=org,
        uploader=member,
        filename="handbook.pdf",
        text="Rudix reimburses approved travel within thirty days.",
    )
    installation = await _seed_installation_and_mapping(
        db_session,
        organization=org,
        user=member,
        provider="teams",
        external_workspace_id="TENANT-BOT",
        external_tenant_id="TENANT-BOT",
        external_team_id="TEAM-BOT",
        external_user_id="AAD-BOT",
    )
    token = create_app_access_token(
        subject=admin.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    credential_response = await bot_client.put(
        f"/api/v1/admin/bots/installations/{installation.id}/credential",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"bot_token": "teams-bearer-token", "scopes": ["botframework.send"]},
    )
    assert credential_response.status_code == 200
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.94,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(document.id),
                    "chunk_id": str(chunk.id),
                    "filename": "handbook.pdf",
                    "page_number": 2,
                    "text": "Rudix reimburses approved travel within thirty days.",
                },
            )
        ]
    )
    _inject_providers(
        monkeypatch,
        answer=(
            '{"answer":"Approved travel is reimbursed within thirty days.",'
            '"not_found":false,"citations":[]}'
        ),
    )
    FakeAsyncHttpClient.posts = []
    FakeAsyncHttpClient.response_json = {"ok": True}
    monkeypatch.setattr(
        "app.domains.bots.services.delivery.httpx.AsyncClient",
        FakeAsyncHttpClient,
    )

    response = await bot_client.post(
        "/api/v1/bots/teams/events",
        json={
            "type": "message",
            "id": "ACTIVITY-BOT",
            "serviceUrl": "https://smba.trafficmanager.test/emea/",
            "text": "When is approved travel reimbursed?",
            "channelData": {
                "tenant": {"id": "TENANT-BOT"},
                "team": {"id": "TEAM-BOT"},
            },
            "conversation": {"id": "CONVERSATION-BOT"},
            "from": {"aadObjectId": "AAD-BOT"},
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert FakeAsyncHttpClient.posts
    final_post = FakeAsyncHttpClient.posts[-1]
    assert (
        final_post["url"]
        == "https://smba.trafficmanager.test/emea/v3/conversations/CONVERSATION-BOT/activities/ACTIVITY-BOT"
    )
    headers = final_post["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer teams-bearer-token"
    final_payload = final_post["json"]
    assert isinstance(final_payload, dict)
    assert "thirty days" in str(final_payload["text"])


@pytest.mark.asyncio
async def test_slack_ask_rejects_unmapped_user_without_creating_chat_session(
    bot_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, _, member = await _seed_org_user(db_session)
    await _seed_installation_and_mapping(db_session, organization=org, user=member)

    response = await bot_client.post(
        "/api/v1/bots/slack/events",
        headers=_sync_bot_headers(),
        json={
            "type": "event_callback",
            "team_id": "T-BOT",
            "event": {"user": "U-UNKNOWN", "channel": "C-BOT", "text": "Question?"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bot_user_not_mapped"
    sessions = list((await db_session.execute(select(ChatSession))).scalars().all())
    assert sessions == []


@pytest.mark.asyncio
async def test_slack_ask_returns_disabled_state(
    bot_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, _, member = await _seed_org_user(db_session)
    await _seed_installation_and_mapping(
        db_session,
        organization=org,
        user=member,
        status="disabled",
    )

    response = await bot_client.post(
        "/api/v1/bots/slack/events",
        headers=_sync_bot_headers(),
        json={
            "type": "event_callback",
            "team_id": "T-BOT",
            "event": {"user": "U-BOT", "channel": "C-BOT", "text": "Question?"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bot_disabled"


@pytest.mark.asyncio
async def test_bot_rate_limit_is_enforced_per_workspace_and_user(
    bot_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, member = await _seed_org_user(db_session)
    document, chunk = await _seed_document_with_chunk(
        db_session,
        organization=org,
        uploader=member,
        filename="policy.pdf",
        text="Employees receive twenty days of annual leave.",
    )
    await _seed_installation_and_mapping(db_session, organization=org, user=member)
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.92,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(document.id),
                    "chunk_id": str(chunk.id),
                    "filename": "policy.pdf",
                    "page_number": 1,
                    "text": "Employees receive twenty days of annual leave.",
                },
            )
        ]
    )
    _inject_providers(
        monkeypatch,
        answer=(
            '{"answer":"Employees receive twenty days of annual leave.",'
            '"not_found":false,"citations":[]}'
        ),
    )
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "rate_limit_bot_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.open)
    monkeypatch.setattr(redis_module, "redis_client", FakeRedis())

    event = {
        "type": "event_callback",
        "team_id": "T-BOT",
        "event": {"user": "U-BOT", "channel": "C-BOT", "text": "How much leave?"},
    }
    first = await bot_client.post(
        "/api/v1/bots/slack/events",
        headers=_sync_bot_headers(),
        json=event,
    )
    second = await bot_client.post(
        "/api/v1/bots/slack/events",
        headers=_sync_bot_headers(),
        json=event,
    )

    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert second.status_code == 200
    assert second.json()["ok"] is False
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
