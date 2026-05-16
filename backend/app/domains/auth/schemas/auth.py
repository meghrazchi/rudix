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
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    role: str
    organization_id: str | None = None
    organization_name: str | None = None


class AuthRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int


class AuthLogoutResponse(BaseModel):
    success: bool = True
