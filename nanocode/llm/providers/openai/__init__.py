"""OpenAI-compatible LLM provider."""

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from nanocode.llm.base import LLMBase, LLMResponse, Message, ToolCall
from nanocode.llm.stream_parser import parse_stream_events


@dataclass
class StreamEvent:
    """Event from streaming response."""
    type: str
    content: str | None = None
    tool_id: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    finish_reason: str | None = None
    usage: dict | None = None


class OpenAILLM(LLMBase):
    """OpenAI-compatible LLM provider."""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = "gpt-4",
        proxy: str = None,
        **kwargs,
    ):
        super().__init__(api_key, base_url, model, proxy=proxy, **kwargs)
        self.base_url = base_url or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "dummy")
        if self.api_key and self.api_key.startswith("${") and self.api_key.endswith("}"):
            env_var = self.api_key[2:-1]
            self.api_key = os.getenv(env_var, self.api_key)

    async def chat(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> LLMResponse:
        """Send a chat completion request."""
        messages = self._normalize_messages(messages)

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            **kwargs,
        }

        # Add max_tokens - default to 4096 for OpenRouter to avoid 402
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if not max_tokens:
            max_tokens = 4096
        payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools

        def on_retry(error: Exception, attempt: int):
            print(f"\n  \033[93mRate limited, retrying (attempt {attempt})...\033[0m")

        def on_retry(error: Exception, attempt: int):
            print(f"\n  \033[93mRate limited, retrying (attempt {attempt})...\033[0m")

        response = await self._request_with_retry(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            on_retry=on_retry,
        )
        data = response.json()

        if "choices" not in data:
            error_msg = data.get("error", {}).get("message", str(data))
            raise RuntimeError(f"LLM API error: {error_msg}")

        choice = data["choices"][0]
        msg_data = choice["message"]

        tool_calls = []
        if tc_data := msg_data.get("tool_calls"):
            for tc in tc_data:
                func = tc.get("function", {})
                tool_calls.append(
                    ToolCall(
                        name=func.get("name", ""),
                        arguments=json.loads(func.get("arguments", "{}")),
                        id=tc.get("id"),
                    )
                )

        return LLMResponse(
            content=msg_data.get("content", ""),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            thinking=msg_data.get("reasoning"),
        )

    async def chat_stream(
        self, messages: list[Message], tools: list[dict] = None, **kwargs
    ) -> AsyncIterator[StreamEvent]:
        """Stream chat completion responses with tool call support.

        Yields StreamEvent objects for text, tool calls, and metadata.
        """
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(proxy=self.proxy) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120.0,
            ) as response:
                async for event in parse_stream_events(response):
                    if event["type"] == "text":
                        yield StreamEvent(type="text", content=event["content"])
                    elif event["type"] == "tool_start":
                        yield StreamEvent(
                            type="tool_start",
                            tool_id=event["id"],
                            tool_name=event["name"],
                        )
                    elif event["type"] == "tool_delta":
                        yield StreamEvent(
                            type="tool_delta",
                            tool_id=event["id"],
                            content=event["delta"],
                        )
                    elif event["type"] == "tool_end":
                        yield StreamEvent(type="tool_end", tool_id=event["id"])
                    elif event["type"] == "tool_call":
                        yield StreamEvent(
                            type="tool_call",
                            tool_id=event["id"],
                            tool_name=event["name"],
                            tool_args=event["arguments"],
                        )
                    elif event["type"] == "finish":
                        yield StreamEvent(
                            type="finish", finish_reason=event["reason"]
                        )
                    elif event["type"] == "usage":
                        yield StreamEvent(type="usage", usage=event["usage"])

    def get_tool_schema(self) -> list[dict]:
        """Get OpenAI function calling format."""
        return []
