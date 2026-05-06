class LLMService:
    """Answer generation service."""

    async def generate_answer(self, prompt: str) -> str:
        raise NotImplementedError
