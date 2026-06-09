"""Console provider — logs email content instead of sending. Safe for development/test."""

from __future__ import annotations

from app.core.logging import get_logger
from app.domains.email.providers.base import AbstractEmailProvider, EmailMessage, SendResult

_logger = get_logger("email.provider.console")


class ConsoleEmailProvider(AbstractEmailProvider):
    @property
    def provider_name(self) -> str:
        return "console"

    async def send(self, message: EmailMessage) -> SendResult:
        _logger.info(
            "email.console.send",
            to=message.to_address,
            subject=message.subject,
            from_address=message.from_address,
        )
        return SendResult(success=True, provider_message_id=None)
