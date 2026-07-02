from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TEAM_SIZE_OPTIONS = {"1-10", "11-50", "51-250", "251-1000", "1000+", "custom"}


class PublicContactSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=2, max_length=100)
    work_email: str = Field(min_length=5, max_length=255)
    company: str = Field(min_length=2, max_length=120)
    role_title: str = Field(min_length=2, max_length=120)
    use_case: str = Field(min_length=2, max_length=160)
    team_size: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=10, max_length=4000)
    consent_accepted: bool
    captcha_token: str | None = Field(default=None, max_length=2048)
    source: str = Field(
        default="public_contact_page",
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )

    @field_validator("work_email")
    @classmethod
    def validate_work_email(cls, value: str) -> str:
        normalized = value.lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError("work_email must be a valid email address")
        return normalized

    @field_validator("team_size")
    @classmethod
    def validate_team_size(cls, value: str) -> str:
        return value if value in _TEAM_SIZE_OPTIONS else "custom"

    @model_validator(mode="after")
    def validate_consent(self) -> PublicContactSubmissionRequest:
        if not self.consent_accepted:
            raise ValueError("consent_accepted must be true")
        return self


class PublicContactSubmissionResponse(BaseModel):
    submission_id: str
    status: Literal["received"] = "received"
    email_status: Literal["sent"]
