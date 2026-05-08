from __future__ import annotations

import json
from typing import Any, TypedDict

_ERROR_STORAGE_PREFIX = "RUDIX_ERR_V1::"


class DocumentErrorDetails(TypedDict):
    stage: str
    code: str
    category: str
    retryable: bool
    message: str


def build_document_error_details(
    *,
    stage: str,
    code: str,
    category: str,
    retryable: bool,
    message: str,
) -> DocumentErrorDetails:
    normalized_message = (message or "Processing failed").strip() or "Processing failed"
    return {
        "stage": stage.strip() or "unknown",
        "code": code.strip() or "UNEXPECTED_ERROR",
        "category": category.strip() or "unexpected",
        "retryable": bool(retryable),
        "message": normalized_message,
    }


def encode_document_error(details: DocumentErrorDetails) -> str:
    return f"{_ERROR_STORAGE_PREFIX}{json.dumps(details, separators=(',', ':'), sort_keys=True)}"


def decode_document_error(raw_error_message: str | None) -> tuple[str | None, DocumentErrorDetails | None]:
    if raw_error_message is None:
        return None, None
    if not raw_error_message.startswith(_ERROR_STORAGE_PREFIX):
        return raw_error_message, None

    payload = raw_error_message[len(_ERROR_STORAGE_PREFIX) :]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return "Processing failed", None

    if not isinstance(data, dict):
        return "Processing failed", None

    details = build_document_error_details(
        stage=str(data.get("stage", "unknown")),
        code=str(data.get("code", "UNEXPECTED_ERROR")),
        category=str(data.get("category", "unexpected")),
        retryable=bool(data.get("retryable", False)),
        message=str(data.get("message", "Processing failed")),
    )
    return details["message"], details


def details_from_exception(exc: Exception) -> DocumentErrorDetails:
    raw_details: Any = getattr(exc, "error_details", None)
    if isinstance(raw_details, dict):
        return build_document_error_details(
            stage=str(raw_details.get("stage", "unknown")),
            code=str(raw_details.get("code", "UNEXPECTED_ERROR")),
            category=str(raw_details.get("category", "unexpected")),
            retryable=bool(raw_details.get("retryable", False)),
            message=str(raw_details.get("message", str(exc) or "Processing failed")),
        )

    message = str(exc).strip() or "Processing failed"
    return build_document_error_details(
        stage="unknown",
        code="UNEXPECTED_ERROR",
        category="unexpected",
        retryable=False,
        message=message,
    )
