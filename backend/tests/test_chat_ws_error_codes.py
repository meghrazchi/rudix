"""Every WebSocket safe_error_code the chat transport emits must be a declared ChatWSSafeErrorCode.

Since R05-01 (S3) the codes come from ``chat.py`` (the connection loop) and the WebSocket
adapter of the pipeline (``app/application/chat/transports/ws.py``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.domains.chat.schemas.chat_ws import ChatWSSafeErrorCode

_APP = Path(__file__).resolve().parents[1] / "app"
_CHAT_SOURCES = (
    _APP / "interfaces" / "http" / "chat.py",
    _APP / "application" / "chat" / "transports" / "ws.py",
)
_CODE_PATTERN = re.compile(r'(?:safe_error_code=|emit_error\()"([a-z_]+)"')


def _emitted_codes() -> set[str]:
    return {
        code
        for source in _CHAT_SOURCES
        for code in _CODE_PATTERN.findall(source.read_text(encoding="utf-8"))
    }


def test_every_emitted_ws_error_code_is_declared() -> None:
    emitted = _emitted_codes()
    declared = set(get_args(ChatWSSafeErrorCode))

    assert emitted, "expected chat.py to emit at least one safe_error_code"
    assert emitted <= declared, f"undeclared WS error codes: {sorted(emitted - declared)}"


def test_plan_limit_exceeded_is_emitted_and_declared() -> None:
    emitted = _emitted_codes()

    assert "plan_limit_exceeded" in emitted
    assert "plan_limit_exceeded" in get_args(ChatWSSafeErrorCode)
