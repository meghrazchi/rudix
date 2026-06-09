"""Abstract email provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EmailMessage:
    to_address: str
    subject: str
    html_body: str
    from_address: str
    from_name: str
    reply_to: str | None = None
    text_body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class SendResult:
    success: bool
    provider_message_id: str | None = None
    error_detail: str | None = None


class AbstractEmailProvider(ABC):
    @abstractmethod
    async def send(self, message: EmailMessage) -> SendResult:
        """Send a single transactional email. Never raise — return SendResult."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...
