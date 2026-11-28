"""Session-hint cookie and cookie Origin check for the auth router (R07-09).

The session hint is a non-secret ``"1"`` cookie that tells the frontend proxy a refresh
cookie probably exists, so a signed-out request for an app route can be redirected to the
login page before any shell HTML is rendered. It carries no token, claim or role and grants
nothing: every protected API call still needs a valid bearer token.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings
from app.core.error_codes import CSRF_ORIGIN_REJECTED, CSRF_ORIGIN_REJECTED_MESSAGE
from app.core.logging import get_logger
from app.core.metrics_auth_session import record_csrf_origin_rejection

SESSION_HINT_COOKIE_VALUE = "1"

logger = get_logger("events.auth_cookies")


def session_hint_cookie_enabled() -> bool:
    return bool(settings.app_auth_session_hint_cookie_enabled)


def set_session_hint_cookie(response: Response) -> None:
    if not session_hint_cookie_enabled():
        return
    response.set_cookie(
        key=settings.app_auth_session_hint_cookie_name,
        value=SESSION_HINT_COOKIE_VALUE,
        httponly=True,
        secure=bool(settings.app_auth_cookie_secure),
        samesite=settings.app_auth_cookie_same_site,  # type: ignore[arg-type]
        max_age=settings.app_auth_refresh_token_ttl_seconds,
        path="/",
        domain=settings.app_auth_session_hint_cookie_domain,
    )


def clear_session_hint_cookie(response: Response) -> None:
    if not session_hint_cookie_enabled():
        return
    response.delete_cookie(
        key=settings.app_auth_session_hint_cookie_name,
        path="/",
        secure=bool(settings.app_auth_cookie_secure),
        httponly=True,
        samesite=settings.app_auth_cookie_same_site,  # type: ignore[arg-type]
        domain=settings.app_auth_session_hint_cookie_domain,
    )


def with_session_hint_cleared(exc: HTTPException) -> HTTPException:
    """Attach a hint-clearing ``Set-Cookie`` to a failed refresh response.

    FastAPI drops the injected ``Response`` when a handler raises, so the header has to
    travel on the exception. The refresh cookie itself is left as it is today.
    """
    if not session_hint_cookie_enabled():
        return exc
    carrier = Response()
    clear_session_hint_cookie(carrier)
    headers = dict(exc.headers or {})
    headers["set-cookie"] = carrier.headers["set-cookie"]
    exc.headers = headers
    return exc


def _normalize_origin(origin: str) -> str:
    parsed = urlsplit(origin.strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".lower()
    return origin.strip().rstrip("/").lower()


def allowed_cookie_origins() -> frozenset[str]:
    """``CORS_ORIGINS`` normalised the same way as the CORS middleware in ``app.main``."""
    return frozenset(_normalize_origin(str(origin)) for origin in settings.cors_origins)


def enforce_cookie_request_origin(request: Request, *, endpoint: str) -> None:
    """Reject cross-site cookie requests when cookies are ``SameSite=None``.

    With ``lax``/``strict`` the browser already withholds the cookies on cross-site POSTs,
    so nothing is checked and behaviour is unchanged.
    """
    if settings.app_auth_cookie_same_site != "none":
        return
    origin = request.headers.get("origin")
    if origin is None or not origin.strip():
        reason = "missing"
    elif _normalize_origin(origin) not in allowed_cookie_origins():
        reason = "foreign"
    else:
        return
    record_csrf_origin_rejection(endpoint=endpoint, reason=reason)
    logger.warning(
        "auth.csrf_origin_rejected",
        endpoint=endpoint,
        reason=reason,
        request_id=request.headers.get("x-request-id"),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": CSRF_ORIGIN_REJECTED, "message": CSRF_ORIGIN_REJECTED_MESSAGE},
    )
