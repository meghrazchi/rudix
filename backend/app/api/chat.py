from fastapi import APIRouter, HTTPException, status

from app.schemas.chat import ChatMessageRequest, ChatMessageResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
async def create_chat_message(session_id: str, _: ChatMessageRequest) -> ChatMessageResponse:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Chat pipeline for session {session_id} is not implemented in scaffold.",
    )
