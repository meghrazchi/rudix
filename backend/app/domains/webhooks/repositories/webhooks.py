from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import Webhook, WebhookDelivery

_DELIVERIES_PAGE_SIZE = 50


class WebhooksRepository:
    async def list_webhooks(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[Webhook]:
        result = await db_session.execute(
            select(Webhook)
            .where(Webhook.organization_id == organization_id)
            .order_by(Webhook.created_at.desc())
        )
        return list(result.scalars())

    async def get_webhook(
        self,
        db_session: AsyncSession,
        *,
        webhook_id: UUID,
        organization_id: UUID,
    ) -> Webhook | None:
        result = await db_session.execute(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_webhook(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None,
        url: str,
        secret_prefix: str,
        secret_hash: str,
        event_types: list[str],
        retry_policy: dict,
        created_by_id: UUID | None,
    ) -> Webhook:
        webhook = Webhook(
            organization_id=organization_id,
            name=name,
            description=description,
            url=url,
            secret_prefix=secret_prefix,
            secret_hash=secret_hash,
            event_types=event_types,
            status="active",
            retry_policy=retry_policy,
            created_by_id=created_by_id,
        )
        db_session.add(webhook)
        await db_session.flush()
        return webhook

    async def update_webhook(
        self,
        db_session: AsyncSession,
        *,
        webhook: Webhook,
        name: str | None,
        description: str | None,
        url: str | None,
        event_types: list[str] | None,
        status: str | None,
        retry_policy: dict | None,
        secret_prefix: str | None = None,
        secret_hash: str | None = None,
    ) -> Webhook:
        if name is not None:
            webhook.name = name
        if description is not None:
            webhook.description = description
        if url is not None:
            webhook.url = url
        if event_types is not None:
            webhook.event_types = event_types
        if status is not None:
            webhook.status = status
        if retry_policy is not None:
            webhook.retry_policy = retry_policy
        if secret_prefix is not None:
            webhook.secret_prefix = secret_prefix
        if secret_hash is not None:
            webhook.secret_hash = secret_hash
        await db_session.flush()
        return webhook

    async def delete_webhook(
        self,
        db_session: AsyncSession,
        *,
        webhook: Webhook,
    ) -> None:
        await db_session.delete(webhook)
        await db_session.flush()

    async def create_delivery(
        self,
        db_session: AsyncSession,
        *,
        webhook_id: UUID,
        organization_id: UUID,
        event_type: str,
        payload: dict,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            webhook_id=webhook_id,
            organization_id=organization_id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempt_count=0,
        )
        db_session.add(delivery)
        await db_session.flush()
        return delivery

    async def update_delivery(
        self,
        db_session: AsyncSession,
        *,
        delivery: WebhookDelivery,
        status: str,
        http_status_code: int | None = None,
        response_body: str | None = None,
        error_message: str | None = None,
        attempt_count: int | None = None,
    ) -> WebhookDelivery:
        delivery.status = status
        if http_status_code is not None:
            delivery.http_status_code = http_status_code
        if response_body is not None:
            delivery.response_body = response_body[:4096]
        if error_message is not None:
            delivery.error_message = error_message[:2048]
        if attempt_count is not None:
            delivery.attempt_count = attempt_count
        await db_session.flush()
        return delivery

    async def list_deliveries(
        self,
        db_session: AsyncSession,
        *,
        webhook_id: UUID,
        organization_id: UUID,
        limit: int = _DELIVERIES_PAGE_SIZE,
    ) -> list[WebhookDelivery]:
        result = await db_session.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.webhook_id == webhook_id,
                WebhookDelivery.organization_id == organization_id,
            )
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())
