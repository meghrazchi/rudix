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
    """Request was rejected because a rate limit or quota was hit."""


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
