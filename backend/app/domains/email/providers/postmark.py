"""Postmark email provider (https://postmarkapp.com)."""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.domains.email.providers.base import AbstractEmailProvider, EmailMessage, SendResult

_logger = get_logger("email.provider.postmark")
_POSTMARK_API_URL = "https://api.postmarkapp.com/email"


class PostmarkEmailProvider(AbstractEmailProvider):
    def __init__(self, server_token: str) -> None:
        self._server_token = server_token

    @property
    def provider_name(self) -> str:
        return "postmark"

    async def send(self, message: EmailMessage) -> SendResult:
        payload: dict[str, object] = {
            "From": f"{message.from_name} <{message.from_address}>",
            "To": message.to_address,
            "Subject": message.subject,
            "HtmlBody": message.html_body,
            "MessageStream": "outbound",
        }
        if message.text_body:
            payload["TextBody"] = message.text_body
        if message.reply_to:
            payload["ReplyTo"] = message.reply_to

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    _POSTMARK_API_URL,
                    json=payload,
                    headers={
                        "X-Postmark-Server-Token": self._server_token,
                        "Accept": "application/json",
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    return SendResult(
                        success=True,
                        provider_message_id=data.get("MessageID"),
                    )
                detail = response.text[:512]
                _logger.warning(
                    "email.postmark.send_error",
                    status_code=response.status_code,
                    detail=detail,
                    to=message.to_address,
                )
                return SendResult(
                    success=False,
                    error_detail=f"HTTP {response.status_code}: {detail}",
                )
        except Exception as exc:
            _logger.warning("email.postmark.send_error", error=str(exc), to=message.to_address)
            return SendResult(success=False, error_detail=str(exc)[:512])
