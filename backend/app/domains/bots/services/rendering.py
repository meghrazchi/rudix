from __future__ import annotations

from urllib.parse import quote

from app.core.config import settings
from app.domains.bots.schemas.bots import BotAskResponse, BotCitationLinkResponse, BotErrorResponse
from app.domains.chat.schemas.chat import ChatCitationResponse, ChatQueryResponse


class BotResponseRenderer:
    def loading_text(self) -> str:
        return "Rudix is searching the permitted sources for an answer."

    def error_response(
        self,
        *,
        provider: str,
        code: str,
        message: str,
        thread_id: str | None = None,
    ) -> BotAskResponse:
        return BotAskResponse(
            ok=False,
            provider=provider,  # type: ignore[arg-type]
            response_type="ephemeral",
            text=message,
            thread_id=thread_id,
            error=BotErrorResponse(code=code, message=message),
        )

    def answer_response(
        self,
        *,
        provider: str,
        thread_id: str | None,
        chat_response: ChatQueryResponse,
    ) -> BotAskResponse:
        citations = [
            self._citation_link(citation, index=index)
            for index, citation in enumerate(chat_response.citations, start=1)
        ]
        citation_text = ""
        if citations:
            citation_lines = [
                f"[{index}] {citation.label}: {citation.url}"
                for index, citation in enumerate(citations, start=1)
            ]
            citation_text = "\n\nSources:\n" + "\n".join(citation_lines)

        return BotAskResponse(
            ok=True,
            provider=provider,  # type: ignore[arg-type]
            response_type="in_channel",
            text=f"{chat_response.answer}{citation_text}",
            loading_text=self.loading_text(),
            thread_id=thread_id,
            chat_session_id=chat_response.chat_session_id,
            message_id=chat_response.message_id,
            not_found=chat_response.not_found,
            citations=citations,
        )

    def _citation_link(
        self,
        citation: ChatCitationResponse,
        *,
        index: int,
    ) -> BotCitationLinkResponse:
        filename = citation.filename or "Source"
        page_suffix = f", p. {citation.page_number}" if citation.page_number is not None else ""
        label = f"{filename}{page_suffix}"
        base_url = str(settings.frontend_base_url).rstrip("/")
        document_id = quote(citation.document_id, safe="")
        chunk_id = quote(citation.chunk_id, safe="")
        url = f"{base_url}/documents/{document_id}?chunk_id={chunk_id}&citation={index}"
        return BotCitationLinkResponse(
            label=label,
            document_id=citation.document_id,
            chunk_id=citation.chunk_id,
            filename=citation.filename,
            page_number=citation.page_number,
            url=url,
        )
