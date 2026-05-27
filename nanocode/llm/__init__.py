"""LLM abstraction layer for multi-provider support.

Connector resolution:
  1. Look up ProviderProfile for the given provider name
  2. Use profile.api_mode to select the connector class
  3. Instantiate with provider-specific defaults (base_url, auth, etc.)
"""

from nanocode.llm.base import LLMBase, Message
from nanocode.llm.connectors.anthropic import AnthropicLLM
from nanocode.llm.connectors.ollama import OllamaLLM
from nanocode.llm.connectors.openai import OpenAILLM
from nanocode.llm.router import ProviderConfig, get_router

# Connector registry: api_mode → connector class
_CONNECTOR_FOR_MODE: dict[str, type[LLMBase]] = {
    "chat_completions": OpenAILLM,
    "anthropic_messages": AnthropicLLM,
}

# Connector registry: provider name → connector class (backward compat)
_EXPLICIT_PROVIDERS: dict[str, type[LLMBase]] = {
    "openai": OpenAILLM,
    "anthropic": AnthropicLLM,
    "ollama": OllamaLLM,
    "lm-studio": OpenAILLM,
    "opencode": OpenAILLM,
    "openrouter": OpenAILLM,
}


def create_llm(provider: str, **config) -> LLMBase:
    """Factory function to create LLM instances.

    Resolves the connector class via:
      1. ProviderProfile lookup (using api_mode)
      2. Backward-compat explicit provider name

    config keys are passed as kwargs to the connector constructor.
    """
    # Check backward-compat explicit providers first
    if provider in _EXPLICIT_PROVIDERS:
        llm_class = _EXPLICIT_PROVIDERS[provider]
        return llm_class(**config)

    # Try profile-based resolution
    profile = _resolve_profile(provider)
    if profile is not None:
        llm_class = _CONNECTOR_FOR_MODE.get(profile.api_mode)
        if llm_class is not None:
            resolved = dict(config)
            resolved.setdefault("api_key", config.get("api_key"))
            if profile.base_url and "base_url" not in resolved:
                resolved["base_url"] = profile.base_url
            if profile.default_max_tokens and "max_tokens" not in resolved:
                resolved["max_tokens"] = profile.default_max_tokens
            return llm_class(**resolved)

    raise ValueError(
        f"Unknown provider: {provider}. "
        f"Available explicit: {list(_EXPLICIT_PROVIDERS.keys())}"
    )


def _resolve_profile(provider: str):
    """Try to resolve a provider name to a ProviderProfile."""
    try:
        from nanocode.llm.profiles import get_provider_profile
        return get_provider_profile(provider)
    except Exception:
        return None


def register_connector(api_mode: str, connector_cls: type[LLMBase]) -> None:
    """Register a connector class for a given api_mode."""
    _CONNECTOR_FOR_MODE[api_mode] = connector_cls


def register_explicit_provider(name: str, connector_cls: type[LLMBase]) -> None:
    """Register a connector class for a specific provider name."""
    _EXPLICIT_PROVIDERS[name] = connector_cls


async def create_llm_from_model_id(
    model_id: str,
    default_provider: str = "openai",
    explicit_providers: dict[str, dict] = None,
) -> tuple[LLMBase, "ProviderConfig"]:
    """Create an LLM from a model ID using the provider router.

    Supports "provider/model" format (e.g., "openai/gpt-4o", "anthropic/claude-sonnet-4-5").

    Args:
        model_id: Model identifier in "provider/model" format or just model name
        default_provider: Fallback provider if not inferrable
        explicit_providers: Optional explicit provider configs

    Returns:
        Tuple of (LLM instance, ProviderConfig)
    """
    router = get_router()

    if explicit_providers:
        for provider, config in explicit_providers.items():
            router.add_explicit_provider(provider, config)

    provider_config = router.get_provider_config(model_id, default_provider)

    llm = create_llm(
        provider_config.get("name") or default_provider,
        base_url=provider_config.get("base_url"),
        api_key=provider_config.get("api_key") or "dummy",
        model=provider_config.get("model"),
        max_tokens=provider_config.get("max_tokens"),
        context_limit=provider_config.get("context_limit"),
    )

    return llm, provider_config
