from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.config import Environment, settings


class CredentialEncryptionError(RuntimeError):
    """Raised when connector credential encryption or decryption fails."""


@dataclass(frozen=True)
class EncryptedCredentialPayload:
    ciphertext: str
    key_id: str
    algorithm: str
    fingerprint: str


class CredentialCipher:
    algorithm = "fernet-sha256-v1"

    def __init__(self, *, secret: SecretStr | str | None = None, key_id: str | None = None) -> None:
        resolved_secret = self._resolve_secret(secret)
        self._secret = resolved_secret
        self.key_id = (key_id or settings.connector_credential_encryption_key_id).strip()
        if not self.key_id:
            raise CredentialEncryptionError("connector credential encryption key id is required")
        self._fernet = Fernet(_derive_fernet_key(resolved_secret))
        self._fingerprint_key = hashlib.sha256(
            f"connector-credential-fingerprint:{resolved_secret}".encode()
        ).digest()

    def encrypt(self, cleartext: str) -> EncryptedCredentialPayload:
        ciphertext = self._fernet.encrypt(cleartext.encode("utf-8")).decode("ascii")
        return EncryptedCredentialPayload(
            ciphertext=ciphertext,
            key_id=self.key_id,
            algorithm=self.algorithm,
            fingerprint=self.fingerprint(cleartext),
        )

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise CredentialEncryptionError("connector credential could not be decrypted") from exc

    def fingerprint(self, cleartext: str) -> str:
        return hmac.new(
            self._fingerprint_key,
            cleartext.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _resolve_secret(secret: SecretStr | str | None) -> str:
        if isinstance(secret, SecretStr):
            value = secret.get_secret_value()
        elif isinstance(secret, str):
            value = secret
        elif settings.connector_credential_encryption_key is not None:
            value = settings.connector_credential_encryption_key.get_secret_value()
        elif settings.environment in {Environment.development, Environment.test}:
            value = settings.app_auth_secret.get_secret_value()
        else:
            raise CredentialEncryptionError(
                "connector_credential_encryption_key is required outside development/test"
            )

        cleaned = value.strip()
        if not cleaned:
            raise CredentialEncryptionError("connector credential encryption secret is empty")
        return cleaned


def _derive_fernet_key(secret: str) -> bytes:
    raw_secret = secret.encode("utf-8")
    try:
        Fernet(raw_secret)  # type: ignore[misc]
    except Exception:
        return base64.urlsafe_b64encode(hashlib.sha256(raw_secret).digest())
    return raw_secret
