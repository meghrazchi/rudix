"""Handlers return their pooled connection before slow network calls (R04-01).

Each fake network call asserts ``not db_session.in_transaction()``: the request's session
holds no connection (and no open transaction) while the call is in flight.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.ai.providers.protocols import ChatCompletionResponse, EmbeddingResponse
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery

_SAML_METADATA = (
    b'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
    b'entityID="https://idp.example.com"><md:IDPSSODescriptor '
    b'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
    b'<md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
    b'Location="https://idp.example.com/sso"/></md:IDPSSODescriptor></md:EntityDescriptor>'
)


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

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


async def _seed(db_session: AsyncSession, role: OrganizationRole) -> tuple[Organization, str]:
    org = Organization(name=f"Org {uuid4().hex[:6]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Admin",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    token = create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        role=role.value,
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )
    return org, token


def _headers(token: str, org: Organization) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}


async def test_provider_probe_runs_without_open_transaction(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, token = await _seed(db_session, OrganizationRole.admin)
    observed: list[bool] = []

    async def _complete(_request: Any) -> ChatCompletionResponse:
        observed.append(db_session.in_transaction())
        return ChatCompletionResponse(
            content="OK",
            model="gpt-test",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1,
        )

    provider = MagicMock()
    provider.complete = AsyncMock(side_effect=_complete)
    monkeypatch.setattr(settings, "llm_default_provider", "openai")
    with patch(
        "app.interfaces.http.model_provider_diagnostics.default_provider_factory.get_chat_provider",
        return_value=provider,
    ):
        response = await client.post(
            "/api/v1/admin/model-providers/test",
            json={"provider_key": "chat"},
            headers=_headers(token, org),
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert observed == [False]


async def test_embedding_probe_runs_without_open_transaction(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, token = await _seed(db_session, OrganizationRole.admin)
    observed: list[bool] = []

    async def _embed(_request: Any) -> EmbeddingResponse:
        observed.append(db_session.in_transaction())
        return EmbeddingResponse(
            vectors=[[0.1]], model="emb", prompt_tokens=1, total_tokens=1, latency_ms=1
        )

    provider = MagicMock()
    provider.embed = AsyncMock(side_effect=_embed)
    monkeypatch.setattr(settings, "embedding_default_provider", "openai")
    with patch(
        "app.interfaces.http.model_provider_diagnostics.default_provider_factory.get_embedding_provider",
        return_value=provider,
    ):
        response = await client.post(
            "/api/v1/admin/model-providers/test",
            json={"provider_key": "embeddings"},
            headers=_headers(token, org),
        )
    assert response.status_code == 200
    assert observed == [False]


class _FakeResponse:
    status_code = 204
    text = ""


async def test_webhook_test_delivery_runs_without_open_transaction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, token = await _seed(db_session, OrganizationRole.admin)
    webhook = Webhook(
        organization_id=org.id,
        name="Hook",
        url="https://example.com/hook",
        secret_prefix="whsec_testprefix",
        secret_hash="a" * 64,
        event_types=["document.indexed"],
        status="active",
        retry_policy={"max_attempts": 3, "backoff_seconds": 30},
    )
    db_session.add(webhook)
    await db_session.commit()
    observed: list[bool] = []

    class _FakeAsyncClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def post(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
            observed.append(db_session.in_transaction())
            return _FakeResponse()

    with patch("app.interfaces.http.admin_webhooks.httpx.AsyncClient", _FakeAsyncClient):
        response = await client.post(
            f"/api/v1/admin/webhooks/{webhook.id}/test", headers=_headers(token, org)
        )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["status"] == "delivered"
    assert observed == [False]
    # The pending delivery was committed before the call and then updated.
    deliveries = (
        (
            await db_session.execute(
                select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook.id)
            )
        )
        .scalars()
        .all()
    )
    assert [d.status for d in deliveries] == ["delivered"]


async def test_sso_test_connection_runs_without_open_transaction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, token = await _seed(db_session, OrganizationRole.owner)
    observed: list[bool] = []

    def _fetch(_url: str) -> bytes:
        observed.append(db_session.in_transaction())
        return _SAML_METADATA

    with patch("app.domains.sso.services.sso_service._fetch_metadata_url", _fetch):
        response = await client.post(
            "/api/v1/admin/sso/test-connection",
            json={"idp_metadata_url": "https://idp.example.com/metadata"},
            headers=_headers(token, org),
        )
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert observed == [False]
