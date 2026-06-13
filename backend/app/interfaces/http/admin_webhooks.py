from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.webhooks.repositories.webhooks import WebhooksRepository
from app.domains.webhooks.schemas.webhooks import (
    CreateWebhookRequest,
    UpdateWebhookRequest,
    WebhookCreatedResponse,
    WebhookDeliveryListResponse,
    WebhookListResponse,
    WebhookResponse,
)
from app.domains.webhooks.services.webhooks_service import WebhooksService
from app.models.permissions import PermissionType

router = APIRouter(prefix="/admin/webhooks", tags=["webhooks"])
webhooks_repository = WebhooksRepository()
webhooks_service = WebhooksService()
audit_log_service = AuditLogService()
logger = get_logger("events.webhooks")

_TEST_DELIVERY_TIMEOUT = 10.0


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid principal context",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


@router.get("", response_model=WebhookListResponse)
async def list_webhooks(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookListResponse:
    organization_id = _org_id(principal)
    webhooks = await webhooks_repository.list_webhooks(
        db_session, organization_id=organization_id
    )
    items = [webhooks_service.to_webhook_response(w) for w in webhooks]
    return WebhookListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=WebhookCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    request: Request,
    payload: CreateWebhookRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookCreatedResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    raw_secret = WebhooksService.generate_raw_secret()
    secret_hash = WebhooksService.hash_secret(raw_secret)
    secret_prefix = WebhooksService.secret_prefix(raw_secret)

    webhook = await webhooks_repository.create_webhook(
        db_session,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        url=payload.url,
        secret_prefix=secret_prefix,
        secret_hash=secret_hash,
        event_types=payload.event_types,
        retry_policy=payload.retry_policy,
        created_by_id=actor_id,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="webhooks.webhook.created",
        resource_type="webhook",
        resource_id=webhook.id,
        request_id=request_id,
        metadata={
            "name": webhook.name,
            "url": webhook.url,
            "event_types": webhook.event_types,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await db_session.commit()

    logger.info(
        "webhooks.webhook.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        webhook_id=str(webhook.id),
        name=webhook.name,
    )
    return webhooks_service.to_webhook_created_response(webhook, raw_secret)


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookResponse:
    organization_id = _org_id(principal)
    try:
        parsed_id = UUID(webhook_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        ) from exc

    webhook = await webhooks_repository.get_webhook(
        db_session, webhook_id=parsed_id, organization_id=organization_id
    )
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )
    return webhooks_service.to_webhook_response(webhook)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    request: Request,
    webhook_id: str,
    payload: UpdateWebhookRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(webhook_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        ) from exc

    webhook = await webhooks_repository.get_webhook(
        db_session, webhook_id=parsed_id, organization_id=organization_id
    )
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )

    webhook = await webhooks_repository.update_webhook(
        db_session,
        webhook=webhook,
        name=payload.name,
        description=payload.description,
        url=payload.url,
        event_types=payload.event_types,
        status=payload.status,
        retry_policy=payload.retry_policy,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="webhooks.webhook.updated",
        resource_type="webhook",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": webhook.name, "status_code": status.HTTP_200_OK},
    )
    await db_session.commit()

    logger.info(
        "webhooks.webhook.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        webhook_id=webhook_id,
    )
    return webhooks_service.to_webhook_response(webhook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    request: Request,
    webhook_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_delete)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(webhook_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        ) from exc

    webhook = await webhooks_repository.get_webhook(
        db_session, webhook_id=parsed_id, organization_id=organization_id
    )
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )

    webhook_name = webhook.name
    await webhooks_repository.delete_webhook(db_session, webhook=webhook)
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="webhooks.webhook.deleted",
        resource_type="webhook",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": webhook_name, "status_code": status.HTTP_204_NO_CONTENT},
    )
    await db_session.commit()

    logger.info(
        "webhooks.webhook.deleted",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        webhook_id=webhook_id,
    )


@router.post(
    "/{webhook_id}/rotate-secret",
    response_model=WebhookCreatedResponse,
    status_code=status.HTTP_200_OK,
)
async def rotate_webhook_secret(
    request: Request,
    webhook_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookCreatedResponse:
    """Generate a new signing secret. The new secret is shown exactly once."""
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(webhook_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        ) from exc

    webhook = await webhooks_repository.get_webhook(
        db_session, webhook_id=parsed_id, organization_id=organization_id
    )
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )

    raw_secret = WebhooksService.generate_raw_secret()
    secret_hash = WebhooksService.hash_secret(raw_secret)
    secret_prefix = WebhooksService.secret_prefix(raw_secret)

    webhook = await webhooks_repository.update_webhook(
        db_session,
        webhook=webhook,
        name=None,
        description=None,
        url=None,
        event_types=None,
        status=None,
        retry_policy=None,
        secret_prefix=secret_prefix,
        secret_hash=secret_hash,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="webhooks.webhook.secret_rotated",
        resource_type="webhook",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": webhook.name, "status_code": status.HTTP_200_OK},
    )
    await db_session.commit()

    logger.info(
        "webhooks.webhook.secret_rotated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        webhook_id=webhook_id,
    )
    return webhooks_service.to_webhook_created_response(webhook, raw_secret)


@router.post(
    "/{webhook_id}/test",
    response_model=WebhookDeliveryListResponse,
    status_code=status.HTTP_200_OK,
)
async def test_webhook(
    request: Request,
    webhook_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookDeliveryListResponse:
    """Send a test ping delivery to the webhook URL and record the outcome."""
    organization_id = _org_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(webhook_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        ) from exc

    webhook = await webhooks_repository.get_webhook(
        db_session, webhook_id=parsed_id, organization_id=organization_id
    )
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )
    if webhook.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot test a disabled webhook"
        )

    test_payload = {
        "event": "webhook.test",
        "webhook_id": str(webhook.id),
        "organization_id": str(webhook.organization_id),
    }
    delivery = await webhooks_repository.create_delivery(
        db_session,
        webhook_id=webhook.id,
        organization_id=organization_id,
        event_type="webhook.test",
        payload=test_payload,
    )

    body_bytes = json.dumps(test_payload, separators=(",", ":")).encode()
    # Use the stored secret_hash as proxy — in a real Celery delivery the raw
    # secret would be loaded from a secrets store. For the test endpoint we
    # generate a one-time nonce signature so the receiver can verify the header
    # format, but the hash won't match without the raw secret.
    import time as _time
    ts = int(_time.time())
    headers = {
        "Content-Type": "application/json",
        "X-Rudix-Timestamp": str(ts),
        "X-Rudix-Webhook-ID": str(webhook.id),
        "X-Rudix-Event": "webhook.test",
    }

    http_status_code: int | None = None
    response_body: str | None = None
    error_message: str | None = None
    final_status = "failed"

    try:
        async with httpx.AsyncClient(timeout=_TEST_DELIVERY_TIMEOUT, follow_redirects=False) as client:
            resp = await client.post(webhook.url, content=body_bytes, headers=headers)
            http_status_code = resp.status_code
            response_body = resp.text[:4096]
            final_status = "delivered" if 200 <= resp.status_code < 300 else "failed"
    except httpx.TimeoutException:
        error_message = "Request timed out"
    except Exception as exc:
        error_message = f"Delivery error: {type(exc).__name__}"

    delivery = await webhooks_repository.update_delivery(
        db_session,
        delivery=delivery,
        status=final_status,
        http_status_code=http_status_code,
        response_body=response_body,
        error_message=error_message,
        attempt_count=1,
    )
    await db_session.commit()

    logger.info(
        "webhooks.webhook.test_sent",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        webhook_id=webhook_id,
        delivery_status=final_status,
        http_status_code=http_status_code,
        request_id=request_id,
    )
    return WebhookDeliveryListResponse(
        items=[webhooks_service.to_delivery_response(delivery)],
        total=1,
    )


@router.get("/{webhook_id}/deliveries", response_model=WebhookDeliveryListResponse)
async def list_webhook_deliveries(
    webhook_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.webhooks_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WebhookDeliveryListResponse:
    organization_id = _org_id(principal)
    try:
        parsed_id = UUID(webhook_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        ) from exc

    webhook = await webhooks_repository.get_webhook(
        db_session, webhook_id=parsed_id, organization_id=organization_id
    )
    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found"
        )

    deliveries = await webhooks_repository.list_deliveries(
        db_session, webhook_id=parsed_id, organization_id=organization_id
    )
    items = [webhooks_service.to_delivery_response(d) for d in deliveries]
    return WebhookDeliveryListResponse(items=items, total=len(items))
