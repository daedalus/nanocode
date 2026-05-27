"""OpenAI-compatible LLM provider with event streaming.

Fully matches opencode architecture: LLM.stream() returns async generator of events.
"""

import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from nanocode.llm.base import LLMBase, Message, ToolCall
from nanocode.llm.events import (
    EventType,
    FinishStepEvent,
    ReasoningDeltaEvent,
    ReasoningEndEvent,
    ReasoningStartEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from nanocode.llm.router import OUTPUT_TOKEN_MAX

logger = logging.getLogger("nanocode.openai")


class OpenAILLM(LLMBase):
    """OpenAI-compatible LLM provider with event streaming."""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = "gpt-4",
        proxy: str = None,
        context_limit: int = None,
        **kwargs,
    ):
        super().__init__(api_key, base_url, model, proxy=proxy, **kwargs)
        self.base_url = base_url or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "dummy")
        self.context_limit = context_limit

        if self.api_key and self.api_key.startswith("${") and self.api_key.endswith("}"):
            env_var = self.api_key[2:-1]
            self.api_key = os.getenv(env_var, self.api_key)

        self._transport = None

    @property
    def _get_transport(self):
        if self._transport is None:
            from nanocode.llm.transports import get_transport
            self._transport = get_transport("chat_completions")
        return self._transport

    async def chat_stream(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream events (matches opencode's LLM.stream())."""
        messages = self._normalize_messages(messages)
        message_dicts = [m.to_dict() for m in messages]

        transport = self._get_transport
        headers = transport.build_headers(self.api_key)

        # Resolve max_tokens: kwargs > self.max_tokens > OUTPUT_TOKEN_MAX
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        if not max_tokens:
            max_tokens = OUTPUT_TOKEN_MAX

        payload = transport.build_kwargs(
            model=self.model,
            messages=message_dicts,
            tools=tools,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )

        # Yield start event
        yield StreamEvent(type=EventType.START)

        # Accumulate tool calls by index
        accumulated_tool_calls = {}

        async with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        ) as response:
            async for line in response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue

                data = line[6:]
                if data == "[DONE]":
                    break

                try:
                    event = json.loads(data)
                    choice = event.get("choices", [{}])[0]
                    delta = choice.get("delta", {})

                    # Handle reasoning (for models that support it)
                    reasoning = delta.get("reasoning", "") or delta.get("reasoning", "")
                    if reasoning:
                        yield ReasoningDeltaEvent(
                            id="reasoning_0",
                            text=reasoning,
                        )

                    # Handle text content
                    if "content" in delta:
                        content = delta["content"]
                        if content:
                            logger.debug(f"Yielding TextDelta: {content[:50]}...")
                            yield TextDeltaEvent(text=content)

                    # Handle tool calls - accumulate by index
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if "id" in tc:
                                accumulated_tool_calls[idx]["id"] = tc["id"]
                            if "function" in tc:
                                func = tc["function"]
                                if "name" in func:
                                    accumulated_tool_calls[idx]["name"] = func["name"]
                                if "arguments" in func:
                                    accumulated_tool_calls[idx]["arguments"] += func["arguments"]

                    # Handle finish - yield accumulated tool calls
                    if choice.get("finish_reason"):
                        for idx, tc_data in accumulated_tool_calls.items():
                            args_str = tc_data["arguments"]
                            try:
                                arguments = json.loads(args_str) if args_str else {}
                            except json.JSONDecodeError:
                                arguments = {}
                            yield ToolCallEvent(
                                tool_call_id=tc_data["id"],
                                tool_name=tc_data["name"],
                                input=arguments,
                            )
                        yield FinishStepEvent(
                            finish_reason=choice["finish_reason"],
                            usage=event.get("usage", {}),
                        )

                except (json.JSONDecodeError, IndexError, KeyError) as e:
                    logger.debug(f"Failed to parse SSE line: {e}")
                    continue

    def get_tool_schema(self) -> list[dict]:
        """Get OpenAI function calling format."""
        return []

    def supports_functions(self) -> bool:
        return True
