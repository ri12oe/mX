"""Model provider layer. See providers/base.py for the interface."""
from providers.base import Message, ModelProvider, ModelResponse
from providers.errors import UnknownProviderError

__all__ = ["Message", "ModelProvider", "ModelResponse", "create_provider"]


def create_provider(name: str, *, api_key: str, model: str) -> ModelProvider:
    """Build the adapter named by PRIMARY_PROVIDER.

    Adapters are added here as they're built (Anthropic: Week 2, task 5).
    """
    raise UnknownProviderError(f"No provider adapter named {name!r} yet.")
