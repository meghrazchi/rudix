from pydantic import BaseModel, ConfigDict, Field


class AuthenticatedPrincipal(BaseModel):
    """Normalized authenticated principal returned by auth providers."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    organization_id: str | None = None
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    auth_provider: str
