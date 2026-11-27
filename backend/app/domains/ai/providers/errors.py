from __future__ import annotations


class ProviderError(Exception):
    """Base class for all AI provider errors."""


class ProviderUnavailableError(ProviderError):
    """Provider is unreachable or returned a 5xx error."""


class ProviderTimeoutError(ProviderError):
    """Provider did not respond within the configured timeout."""


class UnsupportedCapabilityError(ProviderError):
    """Provider or model does not support the requested capability."""


class InvalidProviderResponseError(ProviderError):
    """Provider returned a response that cannot be parsed or used."""


class ProviderQuotaExceededError(ProviderError):
    """Request was rejected because a rate limit or quota was hit.

    ``retry_after_seconds`` is the provider's ``Retry-After`` when it sent one (R06-06);
    embedding batches then pause together for that long.
    """

    def __init__(self, *args: object, retry_after_seconds: float | None = None) -> None:
        super().__init__(*args)
        self.retry_after_seconds = retry_after_seconds


def retry_after_from_headers(headers: object) -> float | None:
    """Seconds from ``retry-after-ms`` or ``retry-after`` (numeric form only)."""
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        raw = get(name)
        if raw is None:
            continue
        try:
            value = float(str(raw).strip()) * scale
        except ValueError:
            continue
        if value >= 0:
            return value
    return None


class ProviderPolicyBlockedError(ProviderError):
    """Request was blocked by provider content policy."""


class ProviderInternalError(ProviderError):
    """Provider reported an internal error."""


class CloudFallbackDisabledError(ProviderError):
    """Fallback to a cloud provider is disabled by org governance policy."""


class ProviderNotAllowedError(ProviderError):
    """The requested provider is not in the org's allowed-provider list."""


class ModelProfileNotAllowedError(ProviderError):
    """The resolved model profile is blocked by org governance policy."""
