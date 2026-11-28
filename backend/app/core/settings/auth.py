"""Authentication provider and session settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    SecretStr,
)

from app.core.settings.enums import (
    AuthProvider,
    Environment,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class AuthSettings(BaseModel):
    auth_provider: AuthProvider = AuthProvider.app
    app_auth_secret: SecretStr = SecretStr("dev-insecure-change-me")
    app_auth_access_token_ttl_seconds: int = Field(default=3600, ge=60, le=604800)
    app_auth_refresh_token_ttl_seconds: int = Field(default=1209600, ge=300, le=7776000)
    app_auth_issuer: str = Field(default="rudix-app", min_length=3, max_length=120)
    app_auth_audience: str = Field(default="rudix-api", min_length=3, max_length=120)
    app_auth_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    # SSO admin setup fetches IdP metadata server side. Private, loopback and
    # link-local hosts are refused unless an on-prem IdP needs them.
    sso_metadata_allow_private_hosts: bool = False
    app_auth_cookie_domain: str | None = Field(default=None, max_length=255)
    app_auth_cookie_secure: bool | None = None
    app_auth_cookie_same_site: str = Field(default="lax", min_length=3, max_length=16)
    app_auth_cookie_path: str = Field(default="/api/v1/auth", min_length=1, max_length=255)
    app_auth_login_password: SecretStr | None = None
    app_auth_auto_provision_users: bool = False
    app_auth_password_hash_memory_cost_kib: int = Field(default=65536, ge=8192, le=1048576)
    app_auth_password_hash_time_cost: int = Field(default=3, ge=1, le=10)
    app_auth_password_hash_parallelism: int = Field(default=1, ge=1, le=8)
    app_auth_password_hash_length: int = Field(default=32, ge=16, le=128)
    app_auth_password_salt_length: int = Field(default=16, ge=8, le=64)
    auth_jwks_cache_ttl_seconds: int = Field(default=300, ge=30, le=86400)
    clerk_jwks_url: AnyHttpUrl | None = None
    clerk_jwt_issuer: AnyHttpUrl | None = None
    clerk_jwt_audience: str | None = Field(default=None, min_length=1, max_length=255)
    supabase_jwks_url: AnyHttpUrl | None = None
    supabase_jwt_issuer: AnyHttpUrl | None = None
    supabase_jwt_audience: str | None = Field(default=None, min_length=1, max_length=255)
    # R07-09: a non-secret "a session may exist" cookie set and cleared with the refresh
    # cookie, readable by the frontend proxy route gate. It grants nothing on its own.
    app_auth_session_hint_cookie_enabled: bool = False
    app_auth_session_hint_cookie_name: str = Field(
        default="rudix_session_hint", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$"
    )
    app_auth_session_hint_cookie_domain: str | None = Field(default=None, max_length=255)
    # R08-11: verify-only previous signing secret for rotation overlap. Tokens and OAuth
    # state are always signed with app_auth_secret; this one is only tried on verification.
    # It is never used for connector credential encryption.
    app_auth_secret_previous: SecretStr | None = None


def validate_auth_cookies(settings: Settings) -> None:
    normalized_same_site = settings.app_auth_cookie_same_site.strip().lower()
    if normalized_same_site not in {"lax", "strict", "none"}:
        raise ValueError("app_auth_cookie_same_site must be one of: lax, strict, none")
    settings.app_auth_cookie_same_site = normalized_same_site
    settings.app_auth_cookie_path = settings.app_auth_cookie_path.strip() or "/api/v1/auth"
    if settings.app_auth_cookie_domain is not None:
        settings.app_auth_cookie_domain = settings.app_auth_cookie_domain.strip() or None
    if settings.app_auth_session_hint_cookie_domain is not None:
        settings.app_auth_session_hint_cookie_domain = (
            settings.app_auth_session_hint_cookie_domain.strip() or None
        )
    if settings.app_auth_cookie_secure is None:
        settings.app_auth_cookie_secure = settings.environment == Environment.production
    if settings.app_auth_cookie_same_site == "none" and not settings.app_auth_cookie_secure:
        raise ValueError("app_auth_cookie_secure must be true when app_auth_cookie_same_site=none")
    if settings.environment == Environment.production and not settings.app_auth_cookie_secure:
        raise ValueError("app_auth_cookie_secure must be true in production")


def validate_auth_provider(settings: Settings) -> None:
    if (
        settings.auth_provider == AuthProvider.app
        and not settings._secret_value(settings.app_auth_secret).strip()
    ):
        raise ValueError("app_auth_secret is required when auth_provider=app")
    validate_auth_secret_previous(settings)

    if settings.auth_provider == AuthProvider.clerk and settings.clerk_jwks_url is None:
        raise ValueError("clerk_jwks_url is required when auth_provider=clerk")
    if settings.auth_provider == AuthProvider.clerk and settings.clerk_jwt_issuer is None:
        raise ValueError("clerk_jwt_issuer is required when auth_provider=clerk")
    if settings.auth_provider == AuthProvider.clerk and settings.clerk_jwt_audience is None:
        raise ValueError("clerk_jwt_audience is required when auth_provider=clerk")

    if settings.auth_provider == AuthProvider.supabase and settings.supabase_jwks_url is None:
        raise ValueError("supabase_jwks_url is required when auth_provider=supabase")
    if settings.auth_provider == AuthProvider.supabase and settings.supabase_jwt_issuer is None:
        raise ValueError("supabase_jwt_issuer is required when auth_provider=supabase")
    if settings.auth_provider == AuthProvider.supabase and settings.supabase_jwt_audience is None:
        raise ValueError("supabase_jwt_audience is required when auth_provider=supabase")


def validate_auth_secret_previous(settings: Settings) -> None:
    previous = settings.app_auth_secret_previous
    if previous is None:
        return
    previous_value = settings._secret_value(previous)
    if not previous_value.strip():
        raise ValueError("app_auth_secret_previous must not be empty when set")
    if previous_value == settings._secret_value(settings.app_auth_secret):
        raise ValueError("app_auth_secret_previous must differ from app_auth_secret")
