from datetime import datetime

from pydantic import BaseModel, Field

from app.domains.chat.schemas.chat import ChatSessionMessageResponse


class CreateChatShareRequest(BaseModel):
    expires_in_hours: int | None = Field(
        default=None,
        ge=1,
        le=8760,
        description="Hours until the share link expires. Omit for no expiry.",
    )


class ChatShareResponse(BaseModel):
    share_id: str
    session_id: str
    token: str
    created_at: datetime
    expires_at: datetime | None = None
    is_revoked: bool
    shared_by_user_id: str


class ChatShareListResponse(BaseModel):
    items: list[ChatShareResponse]
    total: int


class SharedSessionResponse(BaseModel):
    session_id: str
    title: str | None = None
    shared_at: datetime
    messages: list[ChatSessionMessageResponse]
    total_messages: int
