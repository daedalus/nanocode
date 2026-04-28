"""Ollama local LLM provider."""

import json
import os
from collections.abc import AsyncIterator

import httpx

from nanocode.llm.base import LLMBase, LLMResponse, Message, ToolCall


class OllamaLLM(LLMBase):
    """Ollama local LLM provider."""

    def __init__(
        self, base_url: str = None, model: str = "llama2", proxy: str = None, **kwargs
    ):
        super().__init__(None, base_url, model, proxy=proxy, **kwargs)
        self.base_url = base_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )

    async def chat(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> LLMResponse:
        """Send a chat completion request."""
        messages = self._normalize_messages(messages)

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            **kwargs,
        }

        if tools:
            payload["tools"] = tools

        response = await self._client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = await response.json()

        tool_calls = []
        if tc_data := data.get("tool_calls"):
            for tc in tc_data:
                args_str = tc.get("function", {}).get("arguments", "{}")
                try:
                    arguments = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(
                    ToolCall(
                        name=tc.get("function", {}).get("name", ""),
                        arguments=arguments,
                    )
                )

        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            tool_calls=tool_calls,
            finish_reason=data.get("done"),
        )

    def get_tool_schema(self) -> list[dict]:
        """Get Ollama tool format."""
        return []
