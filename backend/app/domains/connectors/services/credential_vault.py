from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.services.audit_service import sanitize_metadata
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.schemas.credentials import (
    ApiTokenCredentialPayload,
    ConnectorCredentialPayload,
    OAuthCredentialPayload,
    ServiceAccountCredentialPayload,
)
from app.domains.connectors.services.credential_crypto import CredentialCipher
from app.models.connector import ConnectorConnection
from app.models.connector_credential import ConnectorCredential
from app.models.enums import (
    ConnectorAuthType,
    ConnectorConnectionStatus,
    ConnectorCredentialStatus,
)


class ConnectorCredentialError(RuntimeError):
    """Raised when connector credentials cannot be used safely."""


class ConnectorCredentialVault:
    def __init__(
        self,
        *,
        repository: ConnectorRepository | None = None,
        cipher: CredentialCipher | None = None,
    ) -> None:
        self.repository = repository or ConnectorRepository()
        self.cipher = cipher or CredentialCipher()

    async def store(
        self,
        session: AsyncSession,
        *,
        connection: ConnectorConnection,
        payload: ConnectorCredentialPayload,
        scopes: list[str] | None = None,
        metadata: dict | None = None,
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
        refreshed: bool = False,
    ) -> ConnectorCredential:
        serialized_payload = _serialize_payload(payload)
        encrypted_payload = self.cipher.encrypt(serialized_payload)
        credential = await self.repository.create_credential_version(
            session,
            organization_id=connection.organization_id,
            connection_id=connection.id,
            auth_type=payload.auth_type.value,
            encrypted_payload=encrypted_payload.ciphertext,
            encryption_key_id=encrypted_payload.key_id,
            encryption_algorithm=encrypted_payload.algorithm,
            secret_fingerprint=encrypted_payload.fingerprint,
            scopes=scopes or _payload_scopes(payload),
            metadata=sanitize_metadata(metadata),
            issued_at=issued_at,
            expires_at=expires_at or _payload_expires_at(payload),
            last_refreshed_at=datetime.now(tz=UTC) if refreshed else None,
        )
        await self.repository.update_connection_auth_metadata(
            session,
            connection=connection,
            auth_config=self.safe_connection_auth_config(connection, credential),
            status=ConnectorConnectionStatus.active,
            error_message=None,
        )
        return credential

    async def load_current(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> tuple[ConnectorCredential, ConnectorCredentialPayload]:
        credential = await self.repository.get_current_credential(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        if credential is None:
            raise ConnectorCredentialError("connector credential is not configured")
        if credential.status == ConnectorCredentialStatus.revoked.value:
            raise ConnectorCredentialError("connector credential has been revoked")
        if credential.status == ConnectorCredentialStatus.error.value:
            raise ConnectorCredentialError("connector credential is in error state")

        cleartext = self.cipher.decrypt(credential.encrypted_payload)
        return credential, _parse_payload(cleartext, credential.auth_type)

    async def mark_used(
        self,
        session: AsyncSession,
        *,
        credential: ConnectorCredential,
        used_at: datetime | None = None,
    ) -> ConnectorCredential:
        return await self.repository.mark_credential_status(
            session,
            credential=credential,
            status=credential.status,
            last_used_at=used_at or datetime.now(tz=UTC),
        )

    def safe_connection_auth_config(
        self,
        connection: ConnectorConnection,
        credential: ConnectorCredential,
    ) -> dict:
        expires_at = credential.expires_at.isoformat() if credential.expires_at else None
        last_refreshed_at = (
            credential.last_refreshed_at.isoformat() if credential.last_refreshed_at else None
        )
        revoked_at = credential.revoked_at.isoformat() if credential.revoked_at else None
        return {
            "auth_type": credential.auth_type,
            "provider_key": (credential.metadata_json or {}).get("provider_key"),
            "credential_id": str(credential.id),
            "credential_status": credential.status,
            "credential_version": credential.version,
            "credential_fingerprint": credential.secret_fingerprint,
            "encryption_key_id": credential.encryption_key_id,
            "encryption_algorithm": credential.encryption_algorithm,
            "scopes": list(credential.scopes_json or []),
            "expires_at": expires_at,
            "last_refreshed_at": last_refreshed_at,
            "revoked_at": revoked_at,
            "external_account_id": connection.external_account_id,
        }


def _serialize_payload(payload: ConnectorCredentialPayload) -> str:
    return json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


def _parse_payload(cleartext: str, auth_type: str) -> ConnectorCredentialPayload:
    raw_payload = json.loads(cleartext)
    if auth_type == ConnectorAuthType.oauth2.value:
        return OAuthCredentialPayload.model_validate(raw_payload)
    if auth_type == ConnectorAuthType.api_token.value:
        return ApiTokenCredentialPayload.model_validate(raw_payload)
    if auth_type == ConnectorAuthType.service_account.value:
        return ServiceAccountCredentialPayload.model_validate(raw_payload)
    raise ConnectorCredentialError("connector credential auth type is unsupported")


class CredentialVault:
    """Thin synchronous wrapper used by the sync engine to decrypt stored credentials.

    The engine holds a resolved ConnectorCredential ORM object (already fetched from
    the DB) and needs the decrypted dict to pass to the adapter.  This class provides
    that without requiring another async DB round-trip.
    """

    def __init__(self, *, cipher: CredentialCipher | None = None) -> None:
        self.cipher = cipher or CredentialCipher()

    def decrypt(self, credential: ConnectorCredential) -> dict:
        """Decrypt a ConnectorCredential and return its payload as a plain dict."""
        if not credential.encrypted_payload:
            raise ConnectorCredentialError("credential has no stored payload")
        try:
            cleartext = self.cipher.decrypt(credential.encrypted_payload)
        except Exception as exc:
            raise ConnectorCredentialError(f"credential decryption failed: {exc}") from exc
        payload = _parse_payload(cleartext, credential.auth_type)
        return payload.model_dump()


def _payload_scopes(payload: ConnectorCredentialPayload) -> list[str]:
    if isinstance(payload, OAuthCredentialPayload):
        return payload.scopes
    return []


def _payload_expires_at(payload: ConnectorCredentialPayload) -> datetime | None:
    if isinstance(payload, OAuthCredentialPayload):
        return payload.expires_at
    return None
