class RerankService:
    """Optional result reranking service."""

    async def rerank(self, _: list[dict]) -> list[dict]:
        raise NotImplementedError
