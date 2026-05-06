class ChunkingService:
    """Chunk creation with overlap and metadata."""

    async def chunk(self, **_: object) -> list[dict]:
        raise NotImplementedError
