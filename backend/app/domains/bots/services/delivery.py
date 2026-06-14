from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.bots.schemas.bots import BotAskResponse
from app.domains.bots.services.adapters import BotAskEvent
from app.domains.bots.services.credential_vault import BotCredentialError, BotCredentialVault
from app.models.bot import BotInstallation

_logger = get_logger("bots.delivery")

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


@dataclass(frozen=True)
class BotDeliveryResult:
    delivered: bool
    provider: str
    target: str
    status_code: int | None = None
    error_code: str | None = None


class BotDeliveryService:
    def __init__(
        self,
        *,
        credential_vault: BotCredentialVault | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._credential_vault = credential_vault or BotCredentialVault()
        self._timeout_seconds = timeout_seconds or settings.bot_delivery_timeout_seconds

    async def deliver_response(
        self,
        *,
        installation: BotInstallation | None,
        event: BotAskEvent,
        response: BotAskResponse,
    ) -> BotDeliveryResult:
        if event.provider == "slack":
            return await self._deliver_slack_response(
                installation=installation,
                event=event,
                response=response,
            )
        if event.provider == "teams":
            return await self._deliver_teams_response(
                installation=installation,
                event=event,
                response=response,
            )
        return BotDeliveryResult(
            delivered=False,
            provider=event.provider,
            target="unknown",
            error_code="unsupported_provider",
        )

    async def _deliver_slack_response(
        self,
        *,
        installation: BotInstallation | None,
        event: BotAskEvent,
        response: BotAskResponse,
    ) -> BotDeliveryResult:
        payload = _slack_message_payload(response)
        if event.response_url:
            return await self._post_json(
                url=event.response_url,
                payload=payload,
                headers={},
                provider="slack",
                target="response_url",
            )

        if installation is None or not event.channel_id:
            return BotDeliveryResult(
                delivered=False,
                provider="slack",
                target="chat.postMessage",
                error_code="missing_delivery_target",
            )
        token = self._load_token(installation)
        if token is None:
            return BotDeliveryResult(
                delivered=False,
                provider="slack",
                target="chat.postMessage",
                error_code="missing_bot_token",
            )
        chat_payload = {
            "channel": event.channel_id,
            "text": response.text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if event.thread_id:
            chat_payload["thread_ts"] = event.thread_id
        result = await self._post_json(
            url=_SLACK_POST_MESSAGE_URL,
            payload=chat_payload,
            headers={"Authorization": f"Bearer {token}"},
            provider="slack",
            target="chat.postMessage",
        )
        return result

    async def _deliver_teams_response(
        self,
        *,
        installation: BotInstallation | None,
        event: BotAskEvent,
        response: BotAskResponse,
    ) -> BotDeliveryResult:
        if installation is None or not event.service_url or not event.conversation_id:
            return BotDeliveryResult(
                delivered=False,
                provider="teams",
                target="conversation.reply",
                error_code="missing_delivery_target",
            )
        token = self._load_token(installation)
        if token is None:
            return BotDeliveryResult(
                delivered=False,
                provider="teams",
                target="conversation.reply",
                error_code="missing_bot_token",
            )
        base_url = event.service_url.rstrip("/")
        conversation_id = quote(event.conversation_id, safe="")
        if event.activity_id:
            activity_id = quote(event.activity_id, safe="")
            path = f"/v3/conversations/{conversation_id}/activities/{activity_id}"
        else:
            path = f"/v3/conversations/{conversation_id}/activities"
        return await self._post_json(
            url=f"{base_url}{path}",
            payload={"type": "message", "text": response.text},
            headers={"Authorization": f"Bearer {token}"},
            provider="teams",
            target="conversation.reply",
        )

    async def _post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        provider: str,
        target: str,
    ) -> BotDeliveryResult:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as exc:
                _logger.warning(
                    "bot_delivery_unreachable",
                    provider=provider,
                    target=target,
                    error_type=exc.__class__.__name__,
                )
                return BotDeliveryResult(
                    delivered=False,
                    provider=provider,
                    target=target,
                    error_code="delivery_unreachable",
                )
        if response.is_error:
            _logger.warning(
                "bot_delivery_rejected",
                provider=provider,
                target=target,
                status_code=response.status_code,
            )
            return BotDeliveryResult(
                delivered=False,
                provider=provider,
                target=target,
                status_code=response.status_code,
                error_code="delivery_rejected",
            )

        if provider == "slack" and target == "chat.postMessage":
            try:
                data = response.json()
            except ValueError:
                data = {}
            if isinstance(data, dict) and data.get("ok") is False:
                return BotDeliveryResult(
                    delivered=False,
                    provider=provider,
                    target=target,
                    status_code=response.status_code,
                    error_code=_safe_slack_error(data.get("error")),
                )

        return BotDeliveryResult(
            delivered=True,
            provider=provider,
            target=target,
            status_code=response.status_code,
        )

    def _load_token(self, installation: BotInstallation) -> str | None:
        try:
            payload = self._credential_vault.load_bot_token(installation)
        except BotCredentialError:
            return None
        if payload is None:
            return None
        token = payload.bot_token.strip()
        return token or None


def _slack_message_payload(response: BotAskResponse) -> dict[str, object]:
    payload: dict[str, object] = {
        "response_type": response.response_type,
        "text": response.text,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if response.thread_id:
        payload["thread_ts"] = response.thread_id
    return payload


def _safe_slack_error(value: object) -> str:
    if not isinstance(value, str):
        return "slack_delivery_failed"
    cleaned = value.strip().lower().replace("-", "_")
    return cleaned[:64] if cleaned else "slack_delivery_failed"
