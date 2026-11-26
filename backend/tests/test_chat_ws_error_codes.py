"""Every WebSocket safe_error_code emitted by chat.py must be a declared ChatWSSafeErrorCode."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.domains.chat.schemas.chat_ws import ChatWSSafeErrorCode

_CHAT_SOURCE = Path(__file__).resolve().parents[1] / "app" / "interfaces" / "http" / "chat.py"
_CODE_PATTERN = re.compile(r'safe_error_code="([a-z_]+)"')


def test_every_emitted_ws_error_code_is_declared() -> None:
    emitted = set(_CODE_PATTERN.findall(_CHAT_SOURCE.read_text(encoding="utf-8")))
    declared = set(get_args(ChatWSSafeErrorCode))

    assert emitted, "expected chat.py to emit at least one safe_error_code"
    assert emitted <= declared, f"undeclared WS error codes: {sorted(emitted - declared)}"


def test_plan_limit_exceeded_is_emitted_and_declared() -> None:
    emitted = set(_CODE_PATTERN.findall(_CHAT_SOURCE.read_text(encoding="utf-8")))

    assert "plan_limit_exceeded" in emitted
    assert "plan_limit_exceeded" in get_args(ChatWSSafeErrorCode)
