#!/usr/bin/env python
"""Find model parameters from models.dev registry."""

import asyncio
import sys

from nanocode.llm.registry import get_registry


async def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <provider> <model>")
        print(f"Example: {sys.argv[0]} opencode big-pickle")
        sys.exit(1)

    provider_id = sys.argv[1]
    model_id = sys.argv[2]

    registry = get_registry()
    await registry.load()

    provider = registry._providers.get(provider_id)
    if not provider:
        print(f"Provider '{provider_id}' not found")
        available = list(registry._providers.keys())
        print(f"Available providers: {', '.join(available[:20])}...")
        sys.exit(1)

    model_info = provider.models.get(model_id)
    if not model_info:
        print(f"Model '{model_id}' not found in provider '{provider_id}'")
        available = list(provider.models.keys())[:20]
        print(f"Available models: {', '.join(available)}...")
        sys.exit(1)

    print(f"Model: {model_info.id}")
    print(f"Name: {model_info.name}")
    print(f"Provider: {model_info.provider_id}")
    print(f"API Endpoint: {model_info.api_endpoint}")
    print(f"Context Limit: {model_info.context_limit:,}")
    print(f"Input Cost: ${model_info.input_cost}/M")
    print(f"Output Cost: ${model_info.output_cost}/M")
    print(f"Supports Tools: {model_info.supports_tools}")
    print(f"Supports Vision: {model_info.supports_vision}")
    print(f"Supports Streaming: {model_info.supports_streaming}")
    print(f"Is Free: {model_info.is_free}")


if __name__ == "__main__":
    asyncio.run(main())