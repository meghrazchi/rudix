"""SMTP email provider using Python's smtplib (async via executor)."""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial

from app.core.logging import get_logger
from app.domains.email.providers.base import AbstractEmailProvider, EmailMessage, SendResult

_logger = get_logger("email.provider.smtp")


class SMTPEmailProvider(AbstractEmailProvider):
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "smtp"

    def _send_sync(self, message: EmailMessage) -> SendResult:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.subject
        msg["From"] = f"{message.from_name} <{message.from_address}>"
        msg["To"] = message.to_address
        if message.reply_to:
            msg["Reply-To"] = message.reply_to
        message_id = f"<{uuid.uuid4().hex}@rudix>"
        msg["Message-ID"] = message_id

        if message.text_body:
            msg.attach(MIMEText(message.text_body, "plain", "utf-8"))
        msg.attach(MIMEText(message.html_body, "html", "utf-8"))

        try:
            smtp_cls = smtplib.SMTP_SSL if (self._use_tls and self._port == 465) else smtplib.SMTP
            with smtp_cls(self._host, self._port, timeout=self._timeout) as server:
                if self._use_tls and self._port != 465:
                    server.starttls()
                if self._username and self._password:
                    server.login(self._username, self._password)
                server.sendmail(message.from_address, [message.to_address], msg.as_string())
            return SendResult(success=True, provider_message_id=message_id)
        except Exception as exc:
            _logger.warning("email.smtp.send_error", error=str(exc), to=message.to_address)
            return SendResult(success=False, error_detail=str(exc)[:512])

    async def send(self, message: EmailMessage) -> SendResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._send_sync, message))
