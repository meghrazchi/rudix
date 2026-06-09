"""Resend email provider (https://resend.com)."""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.domains.email.providers.base import AbstractEmailProvider, EmailMessage, SendResult

_logger = get_logger("email.provider.resend")
_RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailProvider(AbstractEmailProvider):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "resend"

    async def send(self, message: EmailMessage) -> SendResult:
        payload: dict[str, object] = {
            "from": f"{message.from_name} <{message.from_address}>",
            "to": [message.to_address],
            "subject": message.subject,
            "html": message.html_body,
        }
        if message.text_body:
            payload["text"] = message.text_body
        if message.reply_to:
            payload["reply_to"] = message.reply_to

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    _RESEND_API_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                if response.status_code in (200, 201):
                    data = response.json()
                    return SendResult(success=True, provider_message_id=data.get("id"))
                detail = response.text[:512]
                _logger.warning(
                    "email.resend.send_error",
                    status_code=response.status_code,
                    detail=detail,
                    to=message.to_address,
                )
                return SendResult(
                    success=False,
                    error_detail=f"HTTP {response.status_code}: {detail}",
                )
        except Exception as exc:
            _logger.warning("email.resend.send_error", error=str(exc), to=message.to_address)
            return SendResult(success=False, error_detail=str(exc)[:512])
