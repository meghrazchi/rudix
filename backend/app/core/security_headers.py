"""Pure ASGI middleware that adds baseline security headers to HTTP responses."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_TYPE_OPTIONS = (b"x-content-type-options", b"nosniff")
REFERRER_POLICY = (b"referrer-policy", b"strict-origin-when-cross-origin")
FRAME_OPTIONS = (b"x-frame-options", b"DENY")
HSTS = (b"strict-transport-security", b"max-age=31536000")


class SecurityHeadersMiddleware:
    """Add security headers when a response does not already set them."""

    def __init__(self, app: ASGIApp, *, hsts_enabled: bool) -> None:
        self.app = app
        self._defaults: list[tuple[bytes, bytes]] = [
            CONTENT_TYPE_OPTIONS,
            REFERRER_POLICY,
            FRAME_OPTIONS,
        ]
        if hsts_enabled:
            self._defaults.append(HSTS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                headers.extend(item for item in self._defaults if item[0] not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
