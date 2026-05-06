class AuthService:
    """Token verification and authorization checks."""

    async def verify_token(self, _: str) -> dict:
        raise NotImplementedError
