from __future__ import annotations

from functools import lru_cache

from app.auth.providers.app_provider import AppAuthProvider
from app.auth.providers.base import BaseAuthProvider
from app.auth.providers.jwt_jwks_provider import JwtJwksAuthProvider
from app.core.config import AuthProvider, settings


@lru_cache(maxsize=1)
def get_auth_provider() -> BaseAuthProvider:
    if settings.auth_provider == AuthProvider.app:
        return AppAuthProvider()

    if settings.auth_provider in {AuthProvider.clerk, AuthProvider.supabase}:
        return JwtJwksAuthProvider()

    # internal_jwt and api_key are future-pluggable providers.
    return JwtJwksAuthProvider()
