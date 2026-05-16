class UsageService:
    """Usage and cost metric tracking."""

    async def track(self, **_: object) -> None:
        raise NotImplementedError
