"""Stage 4: verified-answer shortcut (R05-01: pass-through; B2 adds the exact match behind
``CHAT_VERIFIED_ANSWER_SHORTCUT_ENABLED``)."""

from app.application.chat.pipeline.context import ChatContext


class ShortcutStage:
    name = "shortcut"
    runs_when_terminal = True
    optional = True

    async def run(self, ctx: ChatContext) -> None:
        return None
