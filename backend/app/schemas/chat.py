from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    stream: bool = False


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    page_number: int | None = None
    score: float | None = None


class ChatMessageResponse(BaseModel):
    session_id: str
    message_id: str
    role: Literal["assistant"] = "assistant"
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime
