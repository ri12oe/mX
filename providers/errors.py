"""Provider-neutral errors (design.md §6).

Adapters translate their SDK's exceptions into these, so the API layer never
sees SDK types. The API maps them to HTTP status codes before streaming starts,
or to an SSE `error` event (using `code`) after.
"""


class ProviderError(Exception):
    """Base class for any failure talking to a model provider."""

    code = "provider_error"


class ProviderAuthError(ProviderError):
    """The provider rejected our API key (missing, wrong, or revoked)."""

    code = "provider_auth"


class ProviderRateLimitError(ProviderError):
    """Too many requests, or the spend limit was reached."""

    code = "provider_rate_limited"


class ProviderUnavailableError(ProviderError):
    """Timeout, network failure, or the provider is overloaded/down."""

    code = "provider_unavailable"


class ProviderBadRequestError(ProviderError):
    """The provider rejected the request itself (e.g. too long, bad image)."""

    code = "provider_bad_request"


class ProviderRefusalError(ProviderError):
    """The model's safety classifiers declined the request (a normal 200 reply
    with stop_reason "refusal"), and no fallback model rescued it."""

    code = "provider_refused"

    def __init__(self, message: str, category: str | None = None) -> None:
        super().__init__(message)
        self.category = category


class UnknownProviderError(ProviderError):
    """PRIMARY_PROVIDER names an adapter that doesn't exist."""

    code = "provider_unknown"
