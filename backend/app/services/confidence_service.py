class ConfidenceService:
    """Confidence scoring service."""

    async def score(self, **_: object) -> float:
        raise NotImplementedError
