"""Build the active email provider from application settings."""

from __future__ import annotations

from app.core.config import settings
from app.domains.email.providers.base import AbstractEmailProvider


def build_email_provider() -> AbstractEmailProvider:
    from app.domains.email.providers.console import ConsoleEmailProvider
    from app.domains.email.providers.postmark import PostmarkEmailProvider
    from app.domains.email.providers.resend import ResendEmailProvider
    from app.domains.email.providers.smtp import SMTPEmailProvider

    provider_type = settings.email_provider

    if provider_type == "smtp":
        password = (
            settings.smtp_password.get_secret_value() if settings.smtp_password else None
        )
        return SMTPEmailProvider(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=password,
            use_tls=settings.smtp_use_tls,
            timeout_seconds=settings.smtp_timeout_seconds,
        )

    if provider_type == "resend":
        if settings.resend_api_key is None:
            raise ValueError("resend_api_key is required when email_provider=resend")
        return ResendEmailProvider(api_key=settings.resend_api_key.get_secret_value())

    if provider_type == "postmark":
        if settings.postmark_server_token is None:
            raise ValueError(
                "postmark_server_token is required when email_provider=postmark"
            )
        return PostmarkEmailProvider(
            server_token=settings.postmark_server_token.get_secret_value()
        )

    return ConsoleEmailProvider()
