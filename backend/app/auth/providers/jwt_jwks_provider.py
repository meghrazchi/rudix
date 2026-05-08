from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError
from app.auth.models import AuthenticatedPrincipal
from app.auth.providers.base import BaseAuthProvider


class JwtJwksAuthProvider(BaseAuthProvider):
    """
    Placeholder for future Clerk/Supabase JWT + JWKS verification.

    This provider is intentionally isolated so token verification logic can be
    added without changing route handlers or authorization dependencies.
    """

    async def authenticate(self, request: Request, session: AsyncSession) -> AuthenticatedPrincipal:
        del request, session
        raise AuthenticationError("Selected auth provider is not implemented yet")
