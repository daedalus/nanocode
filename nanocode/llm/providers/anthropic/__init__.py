"""Anthropic Claude LLM provider."""

import os
from collections.abc import AsyncIterator

import httpx

from nanocode.llm.base import LLMBase, LLMResponse, Message, ToolCall


class AnthropicLLM(LLMBase):
    """Anthropic Claude provider."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-3-5-sonnet-20241022",
        proxy: str = None,
        **kwargs,
    ):
        super().__init__(api_key, None, model, proxy=proxy, **kwargs)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

    async def chat(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> LLMResponse:
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

        async with httpx.AsyncClient(proxy=self.proxy) as client:
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
                tool_calls.append(
                    ToolCall(name=tc.get("name", ""), arguments=tc.get("input", {}), id=tc.get("id"))
                )

        content_parts = []
        thinking = None
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=block.get("name", ""), arguments=block.get("input", {}), id=block.get("id")
                    )
                )
            elif block.get("type") == "thinking":
                thinking = block.get("thinking", "")

        return LLMResponse(
            content="\n".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=data.get("stop_reason"),
            thinking=thinking,
        )

    async def chat_stream(
        self, messages: list[Message], tools: list[dict] = None, **kwargs
    ) -> AsyncIterator[str]:
        """Stream is not fully supported for Claude with tools."""
        response = await self.chat(messages, tools, **kwargs)
        yield response.content

    def get_tool_schema(self) -> list[dict]:
        """Get Anthropic tool format."""
        return []
