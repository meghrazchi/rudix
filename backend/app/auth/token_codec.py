from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.auth.errors import AuthenticationError
from app.core.config import settings

TOKEN_USE_ACCESS = "access"
TOKEN_USE_REFRESH = "refresh"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _sign(message: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_app_access_token(
    *,
    subject: str,
    session_id: str | None = None,
    role: str = "member",
    organization_id: str | None = None,
    email: str | None = None,
    expires_in_seconds: int | None = None,
    token_id: str | None = None,
) -> str:
    return _create_signed_token(
        subject=subject,
        session_id=session_id,
        role=role,
        organization_id=organization_id,
        email=email,
        expires_in_seconds=expires_in_seconds,
        default_ttl_seconds=settings.app_auth_access_token_ttl_seconds,
        token_use=TOKEN_USE_ACCESS,
        token_id=token_id,
    )


def create_app_refresh_token(
    *,
    subject: str,
    session_id: str | None = None,
    role: str = "member",
    organization_id: str | None = None,
    email: str | None = None,
    expires_in_seconds: int | None = None,
    token_id: str | None = None,
) -> str:
    return _create_signed_token(
        subject=subject,
        session_id=session_id,
        role=role,
        organization_id=organization_id,
        email=email,
        expires_in_seconds=expires_in_seconds,
        default_ttl_seconds=settings.app_auth_refresh_token_ttl_seconds,
        token_use=TOKEN_USE_REFRESH,
        token_id=token_id,
    )


def _create_signed_token(
    *,
    subject: str,
    session_id: str | None,
    role: str,
    organization_id: str | None,
    email: str | None,
    expires_in_seconds: int | None,
    default_ttl_seconds: int,
    token_use: str,
    token_id: str | None,
) -> str:
    issued_at = datetime.now(UTC)
    ttl_seconds = expires_in_seconds or default_ttl_seconds
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    resolved_session_id = session_id or uuid4().hex

    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": subject,
        "iss": settings.app_auth_issuer,
        "aud": settings.app_auth_audience,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "token_use": token_use,
        "jti": token_id or uuid4().hex,
        "session_id": resolved_session_id,
        "role": role,
    }
    if organization_id is not None:
        payload["org_id"] = organization_id
    if email is not None:
        payload["email"] = email

    encoded_header = _b64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = _sign(signing_input, settings.app_auth_secret.get_secret_value())
    return f"{signing_input}.{signature}"


def decode_app_access_token(token: str) -> dict[str, Any]:
    return _decode_signed_token(
        token=token,
        expected_token_use=TOKEN_USE_ACCESS,
        allow_missing_token_use=True,
    )


def decode_app_refresh_token(token: str) -> dict[str, Any]:
    return _decode_signed_token(
        token=token,
        expected_token_use=TOKEN_USE_REFRESH,
        allow_missing_token_use=False,
    )


def _decode_signed_token(
    *,
    token: str,
    expected_token_use: str,
    allow_missing_token_use: bool,
) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise AuthenticationError("Invalid token format") from exc

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = _sign(signing_input, settings.app_auth_secret.get_secret_value())
    if not hmac.compare_digest(expected_signature, encoded_signature):
        raise AuthenticationError("Invalid token signature")

    try:
        header_raw = json.loads(_b64url_decode(encoded_header))
        payload_raw = json.loads(_b64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("Invalid token payload") from exc

    if not isinstance(header_raw, dict) or not isinstance(payload_raw, dict):
        raise AuthenticationError("Invalid token payload")

    header = header_raw
    payload = payload_raw

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise AuthenticationError("Unsupported token header")

    if payload.get("iss") != settings.app_auth_issuer:
        raise AuthenticationError("Invalid token issuer")
    if payload.get("aud") != settings.app_auth_audience:
        raise AuthenticationError("Invalid token audience")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthenticationError("Token subject is missing")

    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise AuthenticationError("Token expiration is invalid")
    now_ts = datetime.now(UTC).timestamp()
    if now_ts >= exp + settings.app_auth_clock_skew_seconds:
        raise AuthenticationError("Token has expired")

    token_use = payload.get("token_use")
    if token_use is None and allow_missing_token_use:
        return dict(payload)
    if token_use != expected_token_use:
        raise AuthenticationError("Invalid token type")

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise AuthenticationError("Token session is missing")

    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti.strip():
        raise AuthenticationError("Token identifier is missing")

    return dict(payload)
