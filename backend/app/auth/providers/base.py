from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal


class BaseAuthProvider(ABC):
    @abstractmethod
    async def authenticate(
        self,
        request: Request,
        session: AsyncSession,
    ) -> AuthenticatedPrincipal:
        raise NotImplementedError
