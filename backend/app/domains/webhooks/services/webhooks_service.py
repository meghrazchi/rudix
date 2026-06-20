from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from app.domains.webhooks.schemas.webhooks import (
    WebhookCreatedResponse,
    WebhookDeliveryResponse,
    WebhookResponse,
)
from app.models.webhook import Webhook, WebhookDelivery

_SECRET_PREFIX = "whsec_"
_SECRET_RANDOM_BYTES = 32
_PREFIX_DISPLAY_LENGTH = 16


class WebhooksService:
    @staticmethod
    def generate_raw_secret() -> str:
        random_part = secrets.token_urlsafe(_SECRET_RANDOM_BYTES)
        return f"{_SECRET_PREFIX}{random_part}"

    @staticmethod
    def hash_secret(raw_secret: str) -> str:
        return hashlib.sha256(raw_secret.encode()).hexdigest()

    @staticmethod
    def secret_prefix(raw_secret: str) -> str:
        return raw_secret[:_PREFIX_DISPLAY_LENGTH]

    @staticmethod
    def sign_payload(raw_secret: str, body: bytes, timestamp: int | None = None) -> tuple[str, int]:
        """Return (signature_hex, timestamp_used). Header: X-Rudix-Signature-256."""
        ts = timestamp if timestamp is not None else int(time.time())
        message = f"{ts}.".encode() + body
        sig = hmac.new(raw_secret.encode(), message, hashlib.sha256).hexdigest()
        return sig, ts

    @staticmethod
    def to_webhook_response(webhook: Webhook) -> WebhookResponse:
        return WebhookResponse(
            id=str(webhook.id),
            organization_id=str(webhook.organization_id),
            name=webhook.name,
            description=webhook.description,
            url=webhook.url,
            secret_prefix=webhook.secret_prefix,
            event_types=webhook.event_types if isinstance(webhook.event_types, list) else [],
            status=webhook.status,
            retry_policy=webhook.retry_policy if isinstance(webhook.retry_policy, dict) else {},
            created_by_id=str(webhook.created_by_id) if webhook.created_by_id else None,
            created_at=webhook.created_at,
            updated_at=webhook.updated_at,
        )

    @classmethod
    def to_webhook_created_response(
        cls, webhook: Webhook, raw_secret: str
    ) -> WebhookCreatedResponse:
        base = cls.to_webhook_response(webhook)
        return WebhookCreatedResponse(**base.model_dump(), raw_secret=raw_secret)

    @staticmethod
    def to_delivery_response(delivery: WebhookDelivery) -> WebhookDeliveryResponse:
        return WebhookDeliveryResponse(
            id=str(delivery.id),
            webhook_id=str(delivery.webhook_id),
            organization_id=str(delivery.organization_id),
            event_type=delivery.event_type,
            payload=delivery.payload if isinstance(delivery.payload, dict) else {},
            status=delivery.status,
            http_status_code=delivery.http_status_code,
            response_body=delivery.response_body,
            attempt_count=delivery.attempt_count,
            next_retry_at=delivery.next_retry_at,
            error_message=delivery.error_message,
            created_at=delivery.created_at,
            updated_at=delivery.updated_at,
        )
