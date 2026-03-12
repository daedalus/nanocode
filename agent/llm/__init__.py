"""LLM abstraction layer for multi-provider support."""

from abc import ABC, abstractmethod
from typing import Any, Optional, AsyncIterator
import json
import os

import httpx


class ToolCall:
    """Represents a tool call from the LLM."""
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = arguments
        self.id = f"call_{name}_{hash(str(arguments))}"

    def __repr__(self):
        return f"ToolCall({self.name}, {self.arguments})"


class Message:
    """Represents a message in the conversation."""
    def __init__(self, role: str, content: Any, tool_calls: list[ToolCall] = None, tool_call_id: str = None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id

    def to_dict(self) -> dict:
        """Convert to provider-specific format."""
        result = {"role": self.role, "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [
                {"id": tc.id, "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        """Create from provider response."""
        tool_calls = []
        if tool_calls_data := data.get("tool_calls"):
            for tc in tool_calls_data:
                func = tc.get("function", {})
                tool_calls.append(ToolCall(func.get("name", ""), json.loads(func.get("arguments", "{}"))))
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
        )


class LLMResponse:
    """Standardized LLM response."""
    def __init__(self, content: str, tool_calls: list[ToolCall] = None, finish_reason: str = None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMBase(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None, **kwargs):
        self.api_key = api_key or os.getenv("API_KEY")
        self.base_url = base_url
        self.model = model
        self.extra_kwargs = kwargs

    @abstractmethod
    async def chat(self, messages: list, tools: list[dict] = None, **kwargs) -> LLMResponse:
        """Send a chat completion request."""
        pass

    @abstractmethod
    async def chat_stream(self, messages: list, tools: list[dict] = None, **kwargs) -> AsyncIterator[str]:
        """Stream chat completion responses."""
        pass

    @abstractmethod
    def get_tool_schema(self) -> list[dict]:
        """Get the tool schema format for this provider."""
        pass

    def supports_functions(self) -> bool:
        """Check if provider supports function calling."""
        return True

    def supports_json_mode(self) -> bool:
        """Check if provider supports JSON mode."""
        return False

    def _normalize_messages(self, messages: list) -> list[Message]:
        """Normalize messages to Message objects."""
        normalized = []
        for m in messages:
            if isinstance(m, Message):
                normalized.append(m)
            elif isinstance(m, dict):
                normalized.append(Message.from_dict(m))
            elif isinstance(m, str):
                normalized.append(Message("user", m))
        return normalized


class OpenAILLM(LLMBase):
    """OpenAI-compatible LLM provider."""

    def __init__(self, api_key: str = None, base_url: str = None, model: str = "gpt-4", **kwargs):
        super().__init__(api_key, base_url, model, **kwargs)
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "dummy")

    async def chat(self, messages: list, tools: list[dict] = None, **kwargs) -> LLMResponse:
        """Send a chat completion request."""
        messages = self._normalize_messages(messages)
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.base_url and "openai" not in self.base_url:
            headers["Content-Type"] = "application/json"

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            **kwargs,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        msg_data = choice["message"]

        tool_calls = []
        if tc_data := msg_data.get("tool_calls"):
            for tc in tc_data:
                func = tc.get("function", {})
                tool_calls.append(ToolCall(
                    name=func.get("name", ""),
                    arguments=json.loads(func.get("arguments", "{}"))
                ))

        return LLMResponse(
            content=msg_data.get("content", ""),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
        )

    async def chat_stream(self, messages: list[Message], tools: list[dict] = None, **kwargs) -> AsyncIterator[str]:
        """Stream chat completion responses."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.base_url and "openai" not in self.base_url:
            headers["Content-Type"] = "application/json"

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120.0,
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if content := chunk["choices"][0].get("delta", {}).get("content"):
                            yield content

    def get_tool_schema(self) -> list[dict]:
        """Get OpenAI function calling format."""
        return []


class AnthropicLLM(LLMBase):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str = None, model: str = "claude-3-5-sonnet-20241022", **kwargs):
        super().__init__(api_key, None, model, **kwargs)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

    async def chat(self, messages: list, tools: list[dict] = None, **kwargs) -> LLMResponse:
        """Send a chat completion request."""
        messages = self._normalize_messages(messages)
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        system_msg = None
        formatted_messages = []
        for msg in messages:
            if msg.role == "system":
                system_msg = msg.content
            else:
                formatted_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            **kwargs,
        }
        if system_msg:
            payload["system"] = system_msg

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        tool_calls = []
        if tc_data := data.get("tool_calls", []):
            for tc in tc_data:
                tool_calls.append(ToolCall(
                    name=tc.get("name", ""),
                    arguments=tc.get("input", {})
                ))

        content_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    name=block.get("name", ""),
                    arguments=block.get("input", {})
                ))

        return LLMResponse(
            content="\n".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=data.get("stop_reason"),
        )

    async def chat_stream(self, messages: list[Message], tools: list[dict] = None, **kwargs) -> AsyncIterator[str]:
        """Stream is not fully supported for Claude with tools."""
        response = await self.chat(messages, tools, **kwargs)
        yield response.content

    def get_tool_schema(self) -> list[dict]:
        """Get Anthropic tool format."""
        return []


class OllamaLLM(LLMBase):
    """Ollama local LLM provider."""

    def __init__(self, base_url: str = None, model: str = "llama2", **kwargs):
        super().__init__(None, base_url, model, **kwargs)
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def chat(self, messages: list, tools: list[dict] = None, **kwargs) -> LLMResponse:
        """Send a chat completion request."""
        messages = self._normalize_messages(messages)
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            **kwargs,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        tool_calls = []
        if tc_data := data.get("tool_calls"):
            for tc in tc_data:
                tool_calls.append(ToolCall(
                    name=tc.get("function", {}).get("name", ""),
                    arguments=json.loads(tc.get("function", {}).get("arguments", "{}"))
                ))

        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            tool_calls=tool_calls,
            finish_reason=data.get("done"),
        )

    async def chat_stream(self, messages: list[Message], tools: list[dict] = None, **kwargs) -> AsyncIterator[str]:
        """Stream chat completion responses."""
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120.0,
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        chunk = json.loads(line)
                        if content := chunk.get("message", {}).get("content"):
                            yield content

    def get_tool_schema(self) -> list[dict]:
        """Get Ollama tool format."""
        return []


def create_llm(provider: str, **config) -> LLMBase:
    """Factory function to create LLM instances."""
    providers = {
        "openai": OpenAILLM,
        "anthropic": AnthropicLLM,
        "ollama": OllamaLLM,
        "lm-studio": OpenAILLM,
    }
    
    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(providers.keys())}")
    
    return providers[provider](**config)


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
    from agent.llm.router import ProviderRouter, get_router, ProviderConfig
    
    router = get_router()
    
    if explicit_providers:
        for provider, config in explicit_providers.items():
            router.add_explicit_provider(provider, config)
    
    provider_config = router.get_provider_config(model_id, default_provider)
    
    if provider_config.provider == "anthropic":
        llm = AnthropicLLM(
            api_key=provider_config.api_key,
            model=provider_config.model,
        )
    elif provider_config.provider == "ollama":
        llm = OllamaLLM(
            base_url=provider_config.base_url,
            model=provider_config.model,
        )
    elif provider_config.provider == "lm-studio":
        llm = OpenAILLM(
            base_url=provider_config.base_url,
            api_key=provider_config.api_key or "dummy",
            model=provider_config.model,
        )
    else:
        llm = OpenAILLM(
            base_url=provider_config.base_url,
            api_key=provider_config.api_key or "dummy",
            model=provider_config.model,
        )
    
    return llm, provider_config
