"""Every HTTP error the chat routers raise resolves to a stable code (R05-01, 0.4.0 deferral).

The scan reads the sources of ``app/interfaces/http/chat*.py`` and the chat application
layer, finds every ``HTTPException``, ``_safe_http_error`` and ``ChatPipelineError`` call, and
checks that its ``detail`` resolves through ``code_for`` to a registered or structured code, never to the
status fallback (``NOT_FOUND``, ``FORBIDDEN``, ...).
"""

from __future__ import annotations

import ast
import importlib
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import status

from app.core.error_codes import (
    DETAIL_ERROR_CODES,
    DETAIL_ERROR_PATTERNS,
    STATUS_ERROR_CODES,
    code_for,
)

_BACKEND = Path(__file__).resolve().parents[1]
_SOURCES = sorted((_BACKEND / "app" / "interfaces" / "http").glob("chat*.py")) + sorted(
    (_BACKEND / "app" / "application" / "chat").rglob("*.py")
)
_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True)
class RaisedError:
    location: str
    status_code: int
    detail: Any


def _module_for(path: Path) -> Any:
    relative = path.relative_to(_BACKEND).with_suffix("")
    return importlib.import_module(".".join(relative.parts))


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _status_code(node: ast.expr | None) -> int:
    assert node is not None, "status_code must be passed by keyword"
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        assert node.value.id == "status", ast.unparse(node)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # HTTP_422_UNPROCESSABLE_ENTITY
            return int(getattr(status, node.attr))
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    raise AssertionError(f"unsupported status_code expression: {ast.unparse(node)}")


def _is_forwarded(node: ast.expr | None) -> bool:
    """True for a status that is not a literal (a helper forwarding its own parameter)."""
    if node is None or isinstance(node, ast.Constant):
        return False
    return not (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "status"
    )


def _render(node: ast.JoinedStr, module: Any) -> str:
    """Render an f-string detail: module constants by value, any other name as a UUID."""
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
            continue
        assert isinstance(value, ast.FormattedValue)
        expr = value.value
        if isinstance(expr, ast.Name) and hasattr(module, expr.id):
            parts.append(str(getattr(module, expr.id)))
        else:
            parts.append(_PLACEHOLDER)
    return "".join(parts)


def _detail(node: ast.expr | None, module: Any, location: str) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return _render(node, module)
    if isinstance(node, ast.Dict):
        return {
            key.value: value.value if isinstance(value, ast.Constant) else ast.unparse(value)
            for key, value in zip(node.keys, node.values, strict=True)
            if isinstance(key, ast.Constant)
        }
    raise AssertionError(f"{location}: detail is not a literal: {ast.unparse(node or ast.Pass())}")


def _raised_errors() -> list[RaisedError]:
    found: list[RaisedError] = []
    for path in _SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module: Any = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name not in {"HTTPException", "_safe_http_error", "ChatPipelineError"}:
                continue
            if module is None:
                module = _module_for(path)
            location = f"{path.relative_to(_BACKEND)}:{node.lineno}"
            status_code = _keyword(node, "status_code")
            if _is_forwarded(status_code):
                continue  # a helper forwarding its parameters (``_safe_http_error`` and co.)
            if name == "HTTPException":
                detail: Any = _detail(_keyword(node, "detail"), module, location)
            else:
                code = _keyword(node, "code")
                assert isinstance(code, ast.Constant), f"{location}: code must be a literal"
                detail = {"code": code.value}
            found.append(RaisedError(location, _status_code(status_code), detail))
    return found


_RAISED = _raised_errors()


def test_scan_finds_the_chat_router_errors() -> None:
    locations = {error.location.split(":")[0] for error in _RAISED}
    for module in ("chat_sessions", "chat_shares", "chat_feedback", "chat_answer_shares"):
        assert f"app/interfaces/http/{module}.py" in locations
    assert len(_RAISED) >= 40


@pytest.mark.parametrize("error", _RAISED, ids=lambda error: error.location)
def test_every_chat_http_error_has_a_registered_or_structured_code(error: RaisedError) -> None:
    code = code_for(error.status_code, error.detail)
    assert code not in set(STATUS_ERROR_CODES.values()) | {"BAD_REQUEST", "ERROR"}, (
        f"{error.location}: detail {error.detail!r} falls back to the status code {code}"
    )


def test_structured_chat_codes_keep_their_lower_snake_names() -> None:
    structured = {
        error.detail["code"]
        for error in _RAISED
        if isinstance(error.detail, dict) and "code" in error.detail
    }
    assert {"document_not_found", "chat_session_not_found", "message_not_found"} <= structured
    assert all(code == code.lower() for code in structured)
    assert code_for(404, {"code": "document_not_found", "message": "Document not found"}) == (
        "document_not_found"
    )


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("No relevant answer found", "NO_RELEVANT_ANSWER_FOUND"),
        ("No indexed files found", "NO_INDEXED_FILES_FOUND"),
        ("Request could not be processed", "REQUEST_COULD_NOT_BE_PROCESSED"),
        ("A valid password is required to access this share link.", "SHARE_LINK_PASSWORD_REQUIRED"),
        (
            "You are not in the allowed-users list for this share link.",
            "SHARE_LINK_USER_NOT_ALLOWED",
        ),
        (
            "allowed_user_ids must not be empty when access_mode is 'specific_users'.",
            "SHARE_ALLOWED_USER_IDS_REQUIRED",
        ),
        ("Maximum of 10 active share links per session reached.", "CHAT_SHARE_LIMIT_REACHED"),
        ("Maximum of 10 active share links per answer reached.", "ANSWER_SHARE_LIMIT_REACHED"),
        (
            f"Chat pipeline for session {_PLACEHOLDER} is not implemented in scaffold.",
            "CHAT_MESSAGE_CREATE_NOT_IMPLEMENTED",
        ),
    ],
)
def test_chat_detail_codes(detail: str, expected: str) -> None:
    assert code_for(400, detail) == expected


def test_registry_codes_are_upper_snake_and_unique_per_detail() -> None:
    codes = list(DETAIL_ERROR_CODES.values()) + [code for _, code in DETAIL_ERROR_PATTERNS]
    assert all(code == code.upper() and " " not in code for code in codes)
    assert code_for(501, "Chat pipeline for session is not implemented") == "NOT_IMPLEMENTED"
