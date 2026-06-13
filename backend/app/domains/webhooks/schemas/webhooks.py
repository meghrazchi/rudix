from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.webhook import WEBHOOK_EVENT_TYPES

DEFAULT_RETRY_POLICY = {"max_attempts": 5, "backoff_seconds": 60}

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_HOSTS = frozenset({
    "localhost",
    "localhost.",
    "0.0.0.0",
    "::1",
    "[::1]",
})
_BLOCKED_HOST_PREFIXES = (
    "127.",
    "10.",
    "169.254.",
    "192.168.",
)
_BLOCKED_HOST_RANGES_172 = range(16, 32)


def _is_ssrf_risk(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except Exception:
        return True
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return True
    host = (parsed.hostname or "").lower().strip("[]")
    if not host:
        return True
    if host in _BLOCKED_HOSTS:
        return True
    for prefix in _BLOCKED_HOST_PREFIXES:
        if host.startswith(prefix):
            return True
    # 172.16.0.0–172.31.0.0
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
                if second in _BLOCKED_HOST_RANGES_172:
                    return True
            except ValueError:
                pass
    return False


class CreateWebhookRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    url: str = Field(min_length=1, max_length=2048)
    event_types: list[str] = Field(default_factory=list)
    retry_policy: dict = Field(default_factory=lambda: dict(DEFAULT_RETRY_POLICY))

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if _is_ssrf_risk(value):
            raise ValueError(
                "URL must use http or https and must not target a private or loopback address"
            )
        return value

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str]) -> list[str]:
        unknown = [e for e in values if e not in WEBHOOK_EVENT_TYPES]
        if unknown:
            raise ValueError(f"unknown event types: {unknown}")
        return list(dict.fromkeys(values))

    @field_validator("retry_policy")
    @classmethod
    def validate_retry_policy(cls, value: dict) -> dict:
        max_attempts = value.get("max_attempts", 5)
        backoff_seconds = value.get("backoff_seconds", 60)
        if not isinstance(max_attempts, int) or not (1 <= max_attempts <= 10):
            raise ValueError("retry_policy.max_attempts must be an integer between 1 and 10")
        if not isinstance(backoff_seconds, int) or not (1 <= backoff_seconds <= 3600):
            raise ValueError("retry_policy.backoff_seconds must be an integer between 1 and 3600")
        return {"max_attempts": max_attempts, "backoff_seconds": backoff_seconds}


class UpdateWebhookRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    event_types: list[str] | None = None
    status: str | None = None
    retry_policy: dict | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _is_ssrf_risk(value):
            raise ValueError(
                "URL must use http or https and must not target a private or loopback address"
            )
        return value

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        unknown = [e for e in values if e not in WEBHOOK_EVENT_TYPES]
        if unknown:
            raise ValueError(f"unknown event types: {unknown}")
        return list(dict.fromkeys(values))

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in {"active", "disabled"}:
            raise ValueError("status must be 'active' or 'disabled'")
        return value

    @field_validator("retry_policy")
    @classmethod
    def validate_retry_policy(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        max_attempts = value.get("max_attempts", 5)
        backoff_seconds = value.get("backoff_seconds", 60)
        if not isinstance(max_attempts, int) or not (1 <= max_attempts <= 10):
            raise ValueError("retry_policy.max_attempts must be an integer between 1 and 10")
        if not isinstance(backoff_seconds, int) or not (1 <= backoff_seconds <= 3600):
            raise ValueError("retry_policy.backoff_seconds must be an integer between 1 and 3600")
        return {"max_attempts": max_attempts, "backoff_seconds": backoff_seconds}


class WebhookResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str | None
    url: str
    secret_prefix: str
    event_types: list[str]
    status: str
    retry_policy: dict
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime


class WebhookCreatedResponse(WebhookResponse):
    """Returned only at creation / secret rotation — raw secret shown exactly once."""
    raw_secret: str


class WebhookListResponse(BaseModel):
    items: list[WebhookResponse]
    total: int


class WebhookDeliveryResponse(BaseModel):
    id: str
    webhook_id: str
    organization_id: str
    event_type: str
    payload: dict
    status: str
    http_status_code: int | None
    response_body: str | None
    attempt_count: int
    next_retry_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class WebhookDeliveryListResponse(BaseModel):
    items: list[WebhookDeliveryResponse]
    total: int
