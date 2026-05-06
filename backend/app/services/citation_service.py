class CitationService:
    """Citation extraction and formatting."""

    async def build_citations(self, **_: object) -> list[dict]:
        raise NotImplementedError
