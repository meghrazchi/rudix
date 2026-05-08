class AuthenticationError(Exception):
    """Raised when a request cannot be authenticated."""


class AuthorizationError(Exception):
    """Raised when an authenticated principal lacks required permissions."""
