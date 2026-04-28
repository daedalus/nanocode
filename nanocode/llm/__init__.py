"""LLM abstraction layer for multi-provider support."""

from nanocode.llm.base import LLMBase, Message
from nanocode.llm.connectors.anthropic import AnthropicLLM
from nanocode.llm.connectors.ollama import OllamaLLM
from nanocode.llm.connectors.openai import OpenAILLM
from nanocode.llm.router import ProviderConfig, get_router


def create_llm(provider: str, **config) -> LLMBase:
    """Factory function to create LLM instances."""
    providers = {
        "openai": OpenAILLM,
        "anthropic": AnthropicLLM,
        "ollama": OllamaLLM,
        "lm-studio": OpenAILLM,
        # OpenAI-compatible APIs (use OpenAILLM)
        "opencode": OpenAILLM,
        "openrouter": OpenAILLM,
    }

    if provider not in providers:
        raise ValueError(
            f"Unknown provider: {provider}. Available: {list(providers.keys())}"
        )

    llm_class = providers.get(provider)
    if not llm_class:
        raise ValueError(
            f"Unknown provider: {provider}. Available: {list(providers.keys())}"
        )
    return llm_class(**config)


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

    if provider_config.provider == "anthropic":
        llm = AnthropicLLM(
            api_key=provider_config.api_key,
            model=provider_config.model,
            max_tokens=provider_config.max_tokens,
        )
    elif provider_config.provider == "ollama":
        llm = OllamaLLM(
            base_url=provider_config.base_url,
            model=provider_config.model,
            max_tokens=provider_config.max_tokens,
        )
    elif provider_config.provider == "lm-studio":
        llm = OpenAILLM(
            base_url=provider_config.base_url,
            api_key=provider_config.api_key or "dummy",
            model=provider_config.model,
            max_tokens=provider_config.max_tokens,
        )
    else:
        llm = OpenAILLM(
            base_url=provider_config.base_url,
            api_key=provider_config.api_key or "dummy",
            model=provider_config.model,
            max_tokens=provider_config.max_tokens,
            context_limit=getattr(provider_config, 'context_limit', None),
        )

    return llm, provider_config
