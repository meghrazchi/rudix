from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime


class RefreshTokenStore:
    """In-memory revoked refresh-token registry for single-process runtime."""

    def __init__(self) -> None:
        self._revoked: dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _fingerprint(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _now_epoch() -> int:
        return int(datetime.now(UTC).timestamp())

    def _prune(self, now_epoch: int) -> None:
        expired_keys = [key for key, expires_at in self._revoked.items() if expires_at <= now_epoch]
        for key in expired_keys:
            self._revoked.pop(key, None)

    def revoke(self, token: str, *, expires_at_epoch: int) -> None:
        fingerprint = self._fingerprint(token)
        with self._lock:
            now_epoch = self._now_epoch()
            self._prune(now_epoch)
            self._revoked[fingerprint] = max(expires_at_epoch, now_epoch)

    def is_revoked(self, token: str) -> bool:
        fingerprint = self._fingerprint(token)
        with self._lock:
            now_epoch = self._now_epoch()
            self._prune(now_epoch)
            expires_at = self._revoked.get(fingerprint)
            return expires_at is not None and expires_at > now_epoch


refresh_token_store = RefreshTokenStore()
