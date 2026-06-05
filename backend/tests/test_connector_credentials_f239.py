from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.domains.admin.services.audit_service import sanitize_metadata
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.schemas.credentials import OAuthTokenResponse
from app.domains.connectors.services.connector_service import ConnectorPlatformService
from app.domains.connectors.services.credential_crypto import CredentialCipher
from app.domains.connectors.services.credential_vault import ConnectorCredentialVault
from app.domains.connectors.services.oauth_lifecycle import (
    ConnectorOAuthLifecycleService,
    ConnectorSyncBlockedError,
    OAuthRefreshError,
    OAuthStateValidationError,
)
from app.domains.connectors.services.provider_registry import (
    ProviderRegistryError,
    build_default_provider_registry,
)
from app.models.connector import ConnectorConnection
from app.models.connector_credential import ConnectorCredential
from app.models.enums import (
    ConnectorConnectionStatus,
    ConnectorCredentialStatus,
    ConnectorSyncJobStatus,
    OrganizationRole,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


class _FakeOAuthTokenClient:
    def __init__(self) -> None:
        self.exchange_calls: list[str] = []
        self.refresh_calls: list[str] = []
        self.revoke_calls: list[tuple[str, str]] = []
        self.exchange_response = OAuthTokenResponse(
            access_token="access-token-secret",
            refresh_token="refresh-token-secret",
            token_type="Bearer",
            expires_in=60,
            scopes=["read:jira-work", "offline_access"],
            provider_account_id="jira-site-1",
        )
        self.refresh_response = OAuthTokenResponse(
            access_token="access-token-refreshed",
            refresh_token="refresh-token-refreshed",
            token_type="Bearer",
            expires_in=3600,
            scopes=["read:jira-work", "offline_access"],
            provider_account_id="jira-site-1",
        )
        self.refresh_error: Exception | None = None

    async def exchange_code(
        self,
        *,
        provider_key: str,
        code: str,
        redirect_uri: str,
        scopes: list[str],
    ) -> OAuthTokenResponse:
        del provider_key, redirect_uri, scopes
        self.exchange_calls.append(code)
        return self.exchange_response

    async def refresh(
        self,
        *,
        provider_key: str,
        refresh_token: str,
        scopes: list[str],
    ) -> OAuthTokenResponse:
        del provider_key, scopes
        self.refresh_calls.append(refresh_token)
        if self.refresh_error is not None:
            raise self.refresh_error
        return self.refresh_response

    async def revoke(
        self,
        *,
        provider_key: str,
        token: str,
        token_type_hint: str,
    ) -> None:
        del provider_key
        self.revoke_calls.append((token_type_hint, token))


@pytest.mark.asyncio
async def test_oauth_callback_stores_encrypted_secret_and_safe_metadata(
    db_session: AsyncSession,
) -> None:
    context = await _seed_connector_context(db_session)
    token_client = _FakeOAuthTokenClient()
    service = _service(token_client)

    connect = await service.begin_connect(
        db_session,
        organization_id=context.organization_id,
        provider_key="jira",
        redirect_uri="https://app.example.test/oauth/callback",
        user_id=context.user_id,
        display_name="Jira Production",
    )
    connection = await service.complete_callback(
        db_session,
        organization_id=context.organization_id,
        state=connect.state,
        code="oauth-code",
        user_id=context.user_id,
    )

    credential = await _current_credential(db_session, connection.id)
    assert credential is not None
    assert credential.encrypted_payload
    assert "access-token-secret" not in credential.encrypted_payload
    assert "refresh-token-secret" not in credential.encrypted_payload
    assert connection.auth_config_json["credential_status"] == "active"
    assert "access_token" not in str(connection.auth_config_json)
    assert "refresh_token" not in str(connection.auth_config_json)

    diagnostics = await service.diagnostics(
        db_session,
        organization_id=context.organization_id,
        connection_id=connection.id,
    )
    assert "access-token-secret" not in str(diagnostics)
    assert "refresh-token-secret" not in str(diagnostics)
    assert diagnostics["credential_fingerprint"] == credential.secret_fingerprint


@pytest.mark.asyncio
async def test_expired_oauth_token_refreshes_through_shared_service(
    db_session: AsyncSession,
) -> None:
    context = await _seed_connector_context(db_session)
    token_client = _FakeOAuthTokenClient()
    service = _service(token_client)
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)

    connection = await _connected_jira(
        db_session,
        service=service,
        context=context,
        now=now,
    )
    payload = await service.get_valid_oauth_payload(
        db_session,
        organization_id=context.organization_id,
        connection_id=connection.id,
        now=now + timedelta(minutes=2),
    )

    assert payload.access_token == "access-token-refreshed"
    assert token_client.refresh_calls == ["refresh-token-secret"]

    credentials = list(
        (
            await db_session.execute(
                select(ConnectorCredential).where(
                    ConnectorCredential.connection_id == connection.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(credentials) == 2
    assert [credential.version for credential in credentials] == [1, 2]
    assert sum(1 for credential in credentials if credential.is_current) == 1


@pytest.mark.asyncio
async def test_failed_refresh_blocks_connection_without_leaking_provider_error(
    db_session: AsyncSession,
) -> None:
    context = await _seed_connector_context(db_session)
    token_client = _FakeOAuthTokenClient()
    token_client.refresh_error = RuntimeError("refresh_token=provider-secret")
    service = _service(token_client)
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    connection = await _connected_jira(
        db_session,
        service=service,
        context=context,
        now=now,
    )

    with pytest.raises(OAuthRefreshError, match="connector credential refresh failed"):
        await service.get_valid_oauth_payload(
            db_session,
            organization_id=context.organization_id,
            connection_id=connection.id,
            now=now + timedelta(minutes=2),
        )

    assert connection.status == ConnectorConnectionStatus.error.value
    assert "provider-secret" not in str(connection.auth_config_json)
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert "provider-secret" not in str([log.metadata_json for log in audit_logs])


@pytest.mark.asyncio
async def test_disconnect_revokes_credential_disables_sync_and_blocks_future_sync(
    db_session: AsyncSession,
) -> None:
    context = await _seed_connector_context(db_session)
    token_client = _FakeOAuthTokenClient()
    service = _service(token_client)
    connection = await _connected_jira(
        db_session,
        service=service,
        context=context,
        now=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
    )
    sync_job = await service.repository.create_sync_job(
        db_session,
        organization_id=context.organization_id,
        connection_id=connection.id,
        name="Daily Jira Sync",
    )

    result = await service.disconnect(
        db_session,
        organization_id=context.organization_id,
        connection_id=connection.id,
        user_id=context.user_id,
    )

    assert result["status"] == ConnectorConnectionStatus.revoked.value
    assert result["disabled_sync_jobs"] == 1
    assert sync_job.status == ConnectorSyncJobStatus.disabled.value
    credential = await _current_credential(db_session, connection.id)
    assert credential is not None
    assert credential.status == ConnectorCredentialStatus.revoked.value
    assert connection.status == ConnectorConnectionStatus.revoked.value
    assert ("refresh_token", "refresh-token-secret") in token_client.revoke_calls
    assert ("access_token", "access-token-secret") in token_client.revoke_calls
    with pytest.raises(ConnectorSyncBlockedError):
        await service.get_valid_oauth_payload(
            db_session,
            organization_id=context.organization_id,
            connection_id=connection.id,
        )

    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert "connector.connection.revoked" in {log.action for log in audit_logs}


@pytest.mark.asyncio
async def test_invalid_oauth_callback_state_does_not_exchange_code(
    db_session: AsyncSession,
) -> None:
    context = await _seed_connector_context(db_session)
    token_client = _FakeOAuthTokenClient()
    service = _service(token_client)

    with pytest.raises(OAuthStateValidationError, match="OAuth state is invalid"):
        await service.complete_callback(
            db_session,
            organization_id=context.organization_id,
            state="invalid-state",
            code="oauth-code",
            user_id=context.user_id,
        )

    assert token_client.exchange_calls == []


def test_provider_scope_validation_enforces_least_privilege() -> None:
    registry = build_default_provider_registry()

    assert registry.validate_scopes("jira", None) == [
        "read:jira-work",
        "read:jira-user",
        "offline_access",
    ]
    with pytest.raises(ProviderRegistryError, match="not allowed"):
        registry.validate_scopes(
            "google_drive",
            [
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/drive",
            ],
        )
    with pytest.raises(ProviderRegistryError, match="missing required"):
        registry.validate_scopes("confluence", ["offline_access"])


def test_connector_secret_redaction_handles_oauth_and_api_key_shapes() -> None:
    sanitized = sanitize_metadata(
        {
            "access_token": "access-secret",
            "refreshToken": "refresh-secret",
            "clientSecret": "client-secret",
            "nested": {
                "Authorization": "Bearer header-secret",
                "diagnostic": "api_key=api-secret refresh_token=refresh-secret",
            },
        }
    )

    assert sanitized["access_token"] == "***"
    assert sanitized["refreshToken"] == "***"
    assert sanitized["clientSecret"] == "***"
    assert sanitized["nested"]["Authorization"] == "***"
    assert "api-secret" not in sanitized["nested"]["diagnostic"]
    assert "refresh-secret" not in sanitized["nested"]["diagnostic"]


class _ConnectorTestContext:
    def __init__(self, *, organization_id: UUID, user_id: UUID) -> None:
        self.organization_id = organization_id
        self.user_id = user_id


async def _seed_connector_context(db_session: AsyncSession) -> _ConnectorTestContext:
    org = Organization(name=f"Connector Credential Org {uuid4()}", slug=f"cred-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"credential-user-{uuid4()}",
        email=f"credential-{uuid4().hex[:8]}@example.test",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db_session.flush()
    return _ConnectorTestContext(organization_id=org.id, user_id=user.id)


def _service(token_client: _FakeOAuthTokenClient) -> ConnectorOAuthLifecycleService:
    repository = ConnectorRepository()
    provider_registry = build_default_provider_registry()
    return ConnectorOAuthLifecycleService(
        repository=repository,
        platform_service=ConnectorPlatformService(
            repository=repository,
            provider_registry=provider_registry,
        ),
        provider_registry=provider_registry,
        vault=ConnectorCredentialVault(
            repository=repository,
            cipher=CredentialCipher(secret="connector-test-secret", key_id="test-key"),
        ),
        token_client=token_client,
        state_ttl_seconds=600,
        refresh_skew_seconds=60,
    )


async def _connected_jira(
    db_session: AsyncSession,
    *,
    service: ConnectorOAuthLifecycleService,
    context: _ConnectorTestContext,
    now: datetime,
) -> ConnectorConnection:
    connect = await service.begin_connect(
        db_session,
        organization_id=context.organization_id,
        provider_key="jira",
        redirect_uri="https://app.example.test/oauth/callback",
        user_id=context.user_id,
        display_name="Jira Production",
        now=now,
    )
    return await service.complete_callback(
        db_session,
        organization_id=context.organization_id,
        state=connect.state,
        code="oauth-code",
        user_id=context.user_id,
        now=now,
    )


async def _current_credential(
    db_session: AsyncSession,
    connection_id: UUID,
) -> ConnectorCredential | None:
    result = await db_session.execute(
        select(ConnectorCredential).where(
            ConnectorCredential.connection_id == connection_id,
            ConnectorCredential.is_current.is_(True),
        )
    )
    return result.scalar_one_or_none()
