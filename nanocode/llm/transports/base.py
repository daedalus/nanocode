"""Abstract base for provider transports.

A transport owns the data path for one api_mode:
  build_headers → convert_messages → convert_tools → build_kwargs → normalize_response

It does NOT own: client construction, streaming, credential refresh,
prompt caching, interrupt handling, or retry logic.  Those stay on LLMBase.
"""

from abc import ABC, abstractmethod
from typing import Any

from nanocode.llm.transports.types import NormalizedResponse


class ProviderTransport(ABC):
    """Base class for provider-specific format conversion and normalization."""

    @property
    @abstractmethod
    def api_mode(self) -> str:
        """The api_mode string this transport handles (e.g. 'anthropic_messages')."""
        ...

    def build_headers(self, api_key: str) -> dict[str, str]:
        """Build auth headers for the provider API.

        Default implementation: Bearer token auth.  Override for providers
        with custom auth schemes (e.g. x-api-key).
        """
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @abstractmethod
    def convert_messages(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> Any:
        """Convert OpenAI-format messages to provider-native format.

        Returns provider-specific structure (e.g. (system, messages) for
        Anthropic, or the messages list unchanged for chat_completions).
        """
        ...

    @abstractmethod
    def convert_tools(self, tools: list[dict[str, Any]]) -> Any:
        """Convert OpenAI-format tool definitions to provider-native format."""
        ...

    @abstractmethod
    def build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params,
    ) -> dict[str, Any]:
        """Build the complete API call kwargs dict.

        This is the primary entry point — it typically calls convert_messages()
        and convert_tools() internally, then adds model-specific config.

        Returns a dict ready to be passed to the provider's SDK or as a JSON
        payload body.
        """
        ...

    @abstractmethod
    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        """Normalize a raw provider response to NormalizedResponse.

        *response* is a parsed JSON dict (or SDK response object).
        """
        ...

    def validate_response(self, response: Any) -> bool:
        """Optional: check if the raw response is structurally valid."""
        return True

    def extract_cache_stats(self, response: Any) -> dict[str, int] | None:
        """Optional: extract provider-specific cache hit/creation stats."""
        return None

    def map_finish_reason(self, raw_reason: str) -> str:
        """Map provider-specific stop reason to OpenAI equivalent."""
        return raw_reason
