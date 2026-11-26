"""Login, token refresh, and the abstract authenticated Locust user."""

from __future__ import annotations

import time
from typing import Any

from locust import HttpUser, between

from common.config import API_PREFIX, LoadConfig, load_config

LOGIN_PATH = f"{API_PREFIX}/auth/login"
REFRESH_PATH = f"{API_PREFIX}/auth/token/refresh"
# Refresh when fewer than this many seconds of access-token lifetime remain.
REFRESH_MARGIN_SECONDS = 60.0


class AuthError(RuntimeError):
    """Raised when the load account cannot log in; the message never contains secrets."""


class TokenSession:
    """Keeps an access token fresh for one Locust user.

    Login is ``POST /api/v1/auth/login``. Refresh is ``POST /api/v1/auth/token/refresh``,
    which reads the ``rudix_refresh_token`` cookie the login response set on the same HTTP
    session. When refresh fails (for example a ``Secure`` cookie over plain HTTP), the user
    logs in again.
    """

    def __init__(self, client: Any, config: LoadConfig) -> None:
        self._client = client
        self._config = config
        self.access_token: str | None = None
        self.expires_at: float = 0.0

    def headers(self) -> dict[str, str]:
        self.ensure_fresh()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if self._config.org_id:
            headers["X-Organization-ID"] = self._config.org_id
        return headers

    def ensure_fresh(self) -> None:
        if self.access_token is None:
            self.login()
        elif time.monotonic() >= self.expires_at - REFRESH_MARGIN_SECONDS:
            if not self.refresh():
                self.login()

    def _store(self, body: dict[str, Any]) -> None:
        self.access_token = str(body["access_token"])
        self.expires_at = time.monotonic() + float(body.get("expires_in", 3600))

    def login(self) -> None:
        if not self._config.email or not self._config.password:
            raise AuthError("RUDIX_LOAD_EMAIL and RUDIX_LOAD_PASSWORD must be set")
        payload = {"email": self._config.email, "password": self._config.password}
        with self._client.post(
            LOGIN_PATH, json=payload, name=f"POST {LOGIN_PATH}", catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"login returned HTTP {response.status_code}")
                raise AuthError(f"login failed with HTTP {response.status_code}")
            self._store(response.json())

    def refresh(self) -> bool:
        with self._client.post(
            REFRESH_PATH, json={}, name=f"POST {REFRESH_PATH}", catch_response=True
        ) as response:
            if response.status_code != 200:
                # A failed refresh falls back to login; do not count it as an error.
                response.success()
                return False
            self._store(response.json())
            return True


CONFIG = load_config()


class AuthenticatedUser(HttpUser):
    """Base class: logs in on start and exposes ``auth_headers()``."""

    abstract = True
    host = CONFIG.base_url
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.config = CONFIG
        self.tokens = TokenSession(self.client, CONFIG)
        self.tokens.login()

    def auth_headers(self) -> dict[str, str]:
        return self.tokens.headers()
