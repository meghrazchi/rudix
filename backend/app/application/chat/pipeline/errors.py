"""Safe errors of the chat pipeline (R05-01)."""

from typing import Any

from fastapi import HTTPException


def _safe_http_error(*, status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


class ChatPipelineError(Exception):
    """A refusal of the pipeline with a safe code; transports map it to their protocol."""

    def __init__(
        self,
        *,
        code: str,
        status_code: int,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.payload = payload

    def to_http_exception(self) -> HTTPException:
        return _safe_http_error(status_code=self.status_code, code=self.code, message=self.message)
