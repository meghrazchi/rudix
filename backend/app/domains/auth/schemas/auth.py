from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("email must be a valid address")
        return normalized


class AuthRefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1, max_length=8192)


class AuthLogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1, max_length=8192)


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    role: str
    organization_id: str | None = None
    organization_name: str | None = None
    session_id: str


class AuthRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    role: str
    organization_id: str | None = None
    organization_name: str | None = None
    session_id: str


class AuthCurrentSessionResponse(BaseModel):
    session_id: str
    user_id: str
    email: str
    role: str
    organization_id: str | None = None
    organization_name: str | None = None
    access_token_expires_in: int


class AuthActiveSessionResponse(BaseModel):
    session_id: str
    device_name: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = None


class AuthActiveSessionListResponse(BaseModel):
    items: list[AuthActiveSessionResponse]
    total: int


class AuthLogoutResponse(BaseModel):
    success: bool = True


class AuthEffectivePermissionsResponse(BaseModel):
    permissions: list[str]
    role: str
    custom_role_id: str | None = None
