"""Transactional email and collaboration bot settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    SecretStr,
)

if TYPE_CHECKING:
    pass


class EmailBotsSettings(BaseModel):
    # Product analytics transport and admin-safe summaries.
    # Frontend pages emit safe events to the backend; Matomo is optional and
    # configured on the client side for browser-side pageview tracking.
    # Transactional email (F251)
    email_enabled: bool = False
    email_provider: str = Field(default="console", pattern=r"^(console|smtp|resend|postmark)$")
    email_from_address: str = Field(default="noreply@example.com", min_length=5, max_length=255)
    email_from_name: str = Field(default="Rudix", min_length=1, max_length=120)
    email_reply_to: str | None = Field(default=None, max_length=255)
    email_max_retries: int = Field(default=3, ge=0, le=10)
    contact_receiver_email: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    smtp_host: str = Field(default="localhost", min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    resend_api_key: SecretStr | None = None
    postmark_server_token: SecretStr | None = None
    # Slack / Microsoft Teams bot transport (F261).
    feature_enable_collaboration_bots: bool = True
    bot_slack_signing_secret: SecretStr | None = None
    bot_slack_client_id: str | None = Field(default=None, min_length=1, max_length=255)
    bot_slack_client_secret: SecretStr | None = None
    bot_slack_oauth_redirect_uri: AnyHttpUrl | None = None
    bot_slack_oauth_scopes: str = Field(
        default="app_mentions:read,chat:write,commands,users:read,users:read.email",
        min_length=1,
        max_length=512,
    )
    bot_teams_shared_secret: SecretStr | None = None
    bot_process_events_async: bool = True
    bot_delivery_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
