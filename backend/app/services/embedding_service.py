class EmbeddingService:
    """Embedding generation wrapper."""

    async def embed_texts(self, _: list[str]) -> list[list[float]]:
        raise NotImplementedError
