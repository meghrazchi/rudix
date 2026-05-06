class PromptService:
    """Prompt construction utilities."""

    async def build_prompt(self, **_: object) -> str:
        raise NotImplementedError
