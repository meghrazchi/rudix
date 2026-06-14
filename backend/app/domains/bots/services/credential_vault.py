from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.bots.schemas.bots import BotCredentialResponse
from app.domains.connectors.services.credential_crypto import CredentialCipher
from app.models.bot import BotInstallation


class BotCredentialError(RuntimeError):
    """Raised when a bot credential cannot be used safely."""


class BotTokenPayload(BaseModel):
    provider: str
    bot_token: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)


class BotCredentialVault:
    def __init__(self, *, cipher: CredentialCipher | None = None) -> None:
        self._cipher = cipher or CredentialCipher()

    async def store_bot_token(
        self,
        session: AsyncSession,
        *,
        installation: BotInstallation,
        bot_token: str,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> BotInstallation:
        payload = BotTokenPayload(
            provider=installation.provider,
            bot_token=bot_token.strip(),
            scopes=_normalize_scopes(scopes),
        )
        serialized = json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        encrypted = self._cipher.encrypt(serialized)
        installation.encrypted_bot_token = encrypted.ciphertext
        installation.bot_token_key_id = encrypted.key_id
        installation.bot_token_algorithm = encrypted.algorithm
        installation.bot_token_fingerprint = encrypted.fingerprint
        installation.bot_token_scopes_json = payload.scopes
        installation.bot_token_expires_at = expires_at
        session.add(installation)
        await session.flush()
        await session.refresh(installation)
        return installation

    async def clear_bot_token(
        self,
        session: AsyncSession,
        *,
        installation: BotInstallation,
    ) -> BotInstallation:
        installation.encrypted_bot_token = None
        installation.bot_token_key_id = None
        installation.bot_token_algorithm = None
        installation.bot_token_fingerprint = None
        installation.bot_token_scopes_json = []
        installation.bot_token_expires_at = None
        session.add(installation)
        await session.flush()
        await session.refresh(installation)
        return installation

    def load_bot_token(self, installation: BotInstallation) -> BotTokenPayload | None:
        if not installation.encrypted_bot_token:
            return None
        try:
            cleartext = self._cipher.decrypt(installation.encrypted_bot_token)
            payload = BotTokenPayload.model_validate_json(cleartext)
        except Exception as exc:
            raise BotCredentialError("bot credential could not be decrypted") from exc
        if payload.provider != installation.provider:
            raise BotCredentialError("bot credential provider mismatch")
        return payload

    def metadata(self, installation: BotInstallation) -> BotCredentialResponse:
        return BotCredentialResponse(
            configured=bool(installation.encrypted_bot_token),
            fingerprint=installation.bot_token_fingerprint,
            encryption_key_id=installation.bot_token_key_id,
            encryption_algorithm=installation.bot_token_algorithm,
            scopes=list(installation.bot_token_scopes_json or []),
            expires_at=installation.bot_token_expires_at,
        )


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized: list[str] = []
    for scope in scopes:
        cleaned = str(scope).strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized
