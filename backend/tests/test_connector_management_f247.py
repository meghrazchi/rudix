from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.interfaces.http import connectors as connectors_http
from app.main import app
from app.models.enums import ConnectorAuthType, ConnectorCapability, OrganizationRole

TEST_ORG_ID = str(uuid4())
TEST_USER_ID = str(uuid4())
TEST_CONNECTION_ID = uuid4()


class DummySession:
    async def commit(self) -> None:  # pragma: no cover - exercised through route calls
        return None

    async def rollback(self) -> None:  # pragma: no cover - exercised through route calls
        return None

    async def refresh(
        self, _obj: object
    ) -> None:  # pragma: no cover - exercised through route calls
        return None


@pytest.fixture()
def provider_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    principal = AuthenticatedPrincipal(
        user_id=TEST_USER_ID,
        organization_id=TEST_ORG_ID,
        roles=[OrganizationRole.admin.value],
        auth_provider="test",
    )
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[connectors_http.get_db_session] = lambda: DummySession()
    monkeypatch.setattr(
        connectors_http,
        "_load_connections",
        _fake_load_connections,
    )
    monkeypatch.setattr(connectors_http, "_service", lambda: FakeConnectorService())
    monkeypatch.setattr(connectors_http, "_platform_service", lambda: FakeConnectorService())
    try:
        yield TestClient(app, base_url="http://testserver/api/v1")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
        app.dependency_overrides.pop(connectors_http.get_db_session, None)


def _provider_summary(
    *,
    provider_key: str = "confluence",
    display_name: str | None = None,
    auth_type: str = ConnectorAuthType.oauth2.value,
    config_schema: dict | None = None,
    capabilities: list[str] | None = None,
) -> SimpleNamespace:
    schema = config_schema or {
        "type": "object",
        "properties": {
            "site_url": {"type": "string", "format": "uri"},
            "space_keys": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["site_url"],
        "additionalProperties": False,
    }
    return SimpleNamespace(
        key=provider_key,
        display_name=display_name or provider_key.title(),
        enabled_by_default=True,
        capabilities=SimpleNamespace(auth_type=auth_type),
        auth_type=auth_type,
        is_enabled=True,
        capabilities_json=capabilities or ["acls", "attachments", "comments", "delta_sync"],
        config_schema_json=schema,
        rate_limits_json=[],
        export_formats_json=[],
    )


def _fake_connection(
    *,
    connection_id: UUID | None = None,
    display_name: str = "Engineering Confluence",
    status: str = "active",
    auth_config: dict | None = None,
    provider: SimpleNamespace | None = None,
) -> SimpleNamespace:
    created_at = datetime.now(tz=UTC)
    provider = provider or _provider_summary(
        provider_key="confluence",
        display_name="Confluence",
    )
    return SimpleNamespace(
        id=connection_id or TEST_CONNECTION_ID,
        provider=provider,
        display_name=display_name,
        external_account_id="confluence-site-1",
        collection_id=None,
        status=status,
        auth_config_json=auth_config
        or {
            "provider_key": "confluence",
            "site_url": "https://confluence.example.test",
            "space_keys": ["ENG", "DOCS"],
        },
        last_sync_at=created_at,
        error_message=None,
        sources=[],
        sync_jobs=[SimpleNamespace(id=uuid4())],
        created_at=created_at,
        updated_at=created_at,
    )


async def _fake_load_connections(
    _db_session: object, *, organization_id: UUID
) -> list[SimpleNamespace]:
    del organization_id
    return [_fake_connection(connection_id=TEST_CONNECTION_ID)]


class FakeConnectorService:
    async def complete_callback_public(
        self,
        _db_session: object,
        *,
        state: str,
        code: str | None = None,
        error: str | None = None,
    ) -> SimpleNamespace:
        del state, code, error
        return _fake_connection(connection_id=TEST_CONNECTION_ID)

    async def complete_callback(
        self,
        _db_session: object,
        *,
        organization_id: UUID,
        state: str,
        code: str | None = None,
        error: str | None = None,
        user_id: UUID | None = None,
    ) -> SimpleNamespace:
        del organization_id, state, code, error, user_id
        return _fake_connection(connection_id=TEST_CONNECTION_ID)

    async def diagnostics(
        self,
        _db_session: object,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> dict:
        del organization_id, connection_id
        return {
            "connection_id": str(uuid4()),
            "provider_key": "confluence",
            "status": "active",
            "error_message": None,
            "auth_type": "oauth2",
            "credential_status": "active",
            "credential_version": 1,
            "credential_fingerprint": "fingerprint",
            "scopes": ["read:confluence-content.all"],
            "expires_at": None,
            "metadata": {"provider_key": "confluence"},
        }

    async def create_connection(
        self,
        _db_session: object,
        *,
        organization_id: UUID,
        provider_key: str,
        display_name: str,
        collection_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        external_account_id: str | None = None,
        auth_config: dict | None = None,
    ) -> SimpleNamespace:
        del organization_id, collection_id, created_by_user_id, external_account_id
        auth_type = (
            ConnectorAuthType.api_token.value
            if provider_key == "linear"
            else ConnectorAuthType.oauth2.value
        )
        provider = _provider_summary(
            provider_key=provider_key,
            display_name=display_name,
            auth_type=auth_type,
            config_schema={
                "type": "object",
                "properties": {
                    "api_token": {"type": "string"},
                    "base_url": {"type": "string", "format": "uri"},
                },
                "required": ["api_token", "base_url"],
                "additionalProperties": False,
            }
            if provider_key == "linear"
            else None,
            capabilities=[
                ConnectorCapability.comments.value,
                ConnectorCapability.delta_sync.value,
            ]
            if provider_key == "linear"
            else None,
        )
        return _fake_connection(
            connection_id=uuid4(),
            display_name=display_name,
            auth_config=auth_config,
            provider=provider,
        )


def test_connector_list_and_detail_include_provider_metadata(
    provider_client: TestClient,
) -> None:
    list_response = provider_client.get("/connectors/connections")
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert list_data["total"] == 1

    item = list_data["items"][0]
    assert item["provider_key"] == "confluence"
    assert item["provider"]["config_schema"]["properties"]["site_url"]["format"] == "uri"
    assert item["source_count"] == 0
    assert item["sync_job_count"] == 1

    connection_id = item["id"]
    detail_response = provider_client.get(f"/connectors/connections/{connection_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["diagnostics"]["provider_key"] == "confluence"
    assert detail["auth_config"]["site_url"] == "https://confluence.example.test"
    assert detail["provider"]["config_schema"]["properties"]["space_keys"]["type"] == "array"


def test_oauth_callback_get_redirects_to_connector_detail(
    provider_client: TestClient,
) -> None:
    response = provider_client.get(
        "/connectors/oauth/callback?state=test-state&code=test-code",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].endswith(f"/connectors/{TEST_CONNECTION_ID}")


def test_oauth_callback_get_does_not_require_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_principal_override = app.dependency_overrides.pop(get_current_principal, None)
    app.dependency_overrides[connectors_http.get_db_session] = lambda: DummySession()
    monkeypatch.setattr(connectors_http, "_service", lambda: FakeConnectorService())
    try:
        client = TestClient(app, base_url="http://testserver/api/v1")
        response = client.get(
            "/connectors/oauth/callback?state=test-state&code=test-code",
            follow_redirects=False,
        )
        assert response.status_code == 302
    finally:
        if previous_principal_override is not None:
            app.dependency_overrides[get_current_principal] = previous_principal_override
        else:
            app.dependency_overrides.pop(get_current_principal, None)
        app.dependency_overrides.pop(connectors_http.get_db_session, None)


def test_create_connection_accepts_non_oauth_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider_client: TestClient,
) -> None:
    provider = SimpleNamespace(
        key="linear",
        display_name="Linear",
        capabilities=SimpleNamespace(auth_type=ConnectorAuthType.api_token.value),
        auth_type=ConnectorAuthType.api_token.value,
        is_enabled=True,
        capabilities_json=[
            ConnectorCapability.comments.value,
            ConnectorCapability.delta_sync.value,
        ],
        config_schema_json={
            "type": "object",
            "properties": {
                "api_token": {"type": "string"},
                "base_url": {"type": "string", "format": "uri"},
            },
            "required": ["api_token", "base_url"],
            "additionalProperties": False,
        },
        rate_limits_json=[],
        export_formats_json=[],
    )
    monkeypatch.setattr(
        connectors_http.default_provider_registry,
        "require",
        lambda _provider_key: provider,
    )

    response = provider_client.post(
        "/connectors/connections",
        json={
            "provider_key": "linear",
            "display_name": "Linear Cloud",
            "external_account_id": "linear-account",
            "config": {
                "api_token": "token-123",
                "base_url": "https://linear.example.test",
            },
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["provider_key"] == "linear"
    assert data["provider"]["capabilities"]["auth_type"] == "api_token"
    assert data["auth_config"]["provider_key"] == "linear"
    assert data["auth_config"]["api_token"] == "token-123"
