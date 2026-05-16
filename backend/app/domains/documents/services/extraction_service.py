class ExtractionService:
    """Text extraction for PDF, TXT, and DOCX."""

    async def extract_text(self, **_: object) -> list[dict]:
        raise NotImplementedError
