"""Provider router for dynamic LLM provider selection.

Supports model ID format: provider/model (e.g., "openai/gpt-4o", "anthropic/claude-sonnet-4-5")
"""

import os
from typing import Optional
from dataclasses import dataclass

from nanocode.llm.registry import ModelRegistry, get_registry


PROVIDER_DEFAULTS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model_param": "model",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model_param": "model",
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1",
        "api_key_env": "GOOGLE_API_KEY",
        "model_param": "model",
    },
    "cohere": {
        "base_url": "https://api.cohere.ai/v1",
        "api_key_env": "COHERE_API_KEY",
        "model_param": "model",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "model_param": "model",
    },
    "together": {
        "base_url": "https://api.together.ai/v1",
        "api_key_env": "TOGETHER_API_KEY",
        "model_param": "model",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "model_param": "model",
    },
    "deepinfra": {
        "base_url": "https://api.deepinfra.com/v1",
        "api_key_env": "DEEPINFRA_API_KEY",
        "model_param": "model",
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/v1",
        "api_key_env": "FIREWORKS_API_KEY",
        "model_param": "model",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "api_key_env": None,
        "model_param": "model",
    },
    "lm-studio": {
        "base_url": "http://localhost:1234/v1",
        "api_key_env": None,
        "model_param": "model",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "model_param": "model",
    },
    "azure": {
        "base_url": None,
        "api_key_env": "AZURE_OPENAI_API_KEY",
        "model_param": "model",
    },
    "vertex": {
        "base_url": None,
        "api_key_env": "GOOGLE_APPLICATION_CREDENTIALS",
        "model_param": "model",
    },
}


@dataclass
class ParsedModelID:
    """Parsed model ID components."""

    provider: str
    model: str


@dataclass
class ProviderConfig:
    """Configuration for a provider."""

    provider: str
    base_url: str
    api_key: Optional[str]
    model: str


class ProviderRouter:
    """Routes LLM requests to the appropriate provider based on model ID."""

    def __init__(self, registry: ModelRegistry = None):
        self.registry = registry or get_registry()
        self._explicit_providers: dict[str, dict] = {}

    def add_explicit_provider(self, provider: str, config: dict):
        """Add an explicitly configured provider."""
        self._explicit_providers[provider] = config

    def parse_model_id(self, model_id: str) -> ParsedModelID:
        """Parse model ID into provider and model name.

        Examples:
            "gpt-4o" -> provider="openai", model="gpt-4o"
            "openai/gpt-4o" -> provider="openai", model="gpt-4o"
            "claude-sonnet-4-5" -> provider="anthropic", model="claude-sonnet-4-5"
            "anthropic/claude-sonnet-4-5" -> provider="anthropic", model="claude-sonnet-4-5"
        """
        if "/" in model_id:
            provider, model = model_id.split("/", 1)
            return ParsedModelID(provider=provider, model=model)

        # Try to infer provider from model name patterns
        inferred = self._infer_provider_from_model(model_id)
        return ParsedModelID(provider=inferred, model=model_id)

    def _infer_provider_from_model(self, model_id: str) -> str:
        """Infer provider from model name patterns."""
        model_lower = model_id.lower()

        # Known model patterns
        if (
            model_lower.startswith("gpt-")
            or model_lower.startswith("o1")
            or model_lower.startswith("o3")
        ):
            return "openai"
        if (
            model_lower.startswith("claude-")
            or model_lower.startswith("haiku")
            or model_lower.startswith("sonnet")
        ):
            return "anthropic"
        if model_lower.startswith("gemini-") or model_lower.startswith("gemma-"):
            return "google"
        if (
            model_lower.startswith("llama-")
            or model_lower.startswith("mistral-")
            or model_lower.startswith("qwen-")
        ):
            return "ollama"
        if model_lower.startswith("mixtral-") or model_lower.startswith("codestral"):
            return "mistral"

        # Default to openai for unknown models
        return "openai"

    def get_provider_config(
        self,
        model_id: str,
        default_provider: str = "openai",
    ) -> ProviderConfig:
        """Get provider configuration for a model ID.

        Resolution order:
        1. Explicit config in _explicit_providers
        2. From models.dev registry if available
        3. From PROVIDER_DEFAULTS
        """
        parsed = self.parse_model_id(model_id)

        # Check explicit providers first
        if parsed.provider in self._explicit_providers:
            config = self._explicit_providers[parsed.provider]
            return ProviderConfig(
                provider=parsed.provider,
                base_url=config.get("base_url", ""),
                api_key=config.get("api_key"),
                model=parsed.model,
            )

        # Check models.dev registry
        model_info = self.registry.get_model_by_full_id(model_id)
        if model_info and model_info.api_endpoint:
            api_key = self._get_api_key(parsed.provider)
            return ProviderConfig(
                provider=parsed.provider,
                base_url=model_info.api_endpoint,
                api_key=api_key,
                model=parsed.model,
            )

        # Fall back to defaults
        defaults = PROVIDER_DEFAULTS.get(parsed.provider, PROVIDER_DEFAULTS["openai"])

        base_url = defaults.get("base_url", "")
        if parsed.provider == "opencode":
            # Special handling for OpenCode Zen
            base_url = "https://opencode.ai/zen/v1"

        api_key = self._get_api_key(parsed.provider) or defaults.get("api_key_env")

        return ProviderConfig(
            provider=parsed.provider,
            base_url=base_url,
            api_key=api_key,
            model=parsed.model,
        )

    def _get_api_key(self, provider: str) -> Optional[str]:
        """Get API key from environment."""
        # Check explicit config first
        if provider in self._explicit_providers:
            config = self._explicit_providers[provider]
            if config.get("api_key"):
                return config["api_key"]

        # Try common environment variables
        env_vars = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "cohere": "COHERE_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "together": "TOGETHER_API_KEY",
            "groq": "GROQ_API_KEY",
            "deepinfra": "DEEPINFRA_API_KEY",
            "fireworks": "FIREWORKS_API_KEY",
            "ollama": None,
            "lm-studio": None,
            "openrouter": "OPENROUTER_API_KEY",
            "opencode": "OPENCODE_ZEN_API_KEY",
        }

        env_var = env_vars.get(provider)
        if env_var:
            return os.getenv(env_var)

        return None

    def is_provider_available(self, model_id: str) -> bool:
        """Check if a provider is available (has API key or is local)."""
        config = self.get_provider_config(model_id)

        # Local providers (ollama, lm-studio) don't need API keys
        if config.provider in ("ollama", "lm-studio"):
            return True

        # Check if we can connect or have an API key
        return config.api_key is not None or config.api_key == "public"


# Global router instance
_router: Optional[ProviderRouter] = None


def get_router() -> ProviderRouter:
    """Get the global provider router instance."""
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router
