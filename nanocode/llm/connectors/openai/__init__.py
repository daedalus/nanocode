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

    async def _handle_stream_line(
        self, line: str, accumulated_tool_calls: dict
    ) -> AsyncGenerator[StreamEvent, None]:
        """Handle a single SSE line from the stream."""
        if not line or not line.startswith("data: "):
            return
        data = line[6:]
        if data == "[DONE]":
            return

        import json
        try:
            event = json.loads(data)
            choices = event.get("choices")
            if not choices:
                return
            choice = choices[0]
            delta = choice.get("delta", {})

            reasoning = delta.get("reasoning", "") or delta.get("reasoning", "")
            if reasoning:
                yield ReasoningDeltaEvent(id="reasoning_0", text=reasoning)

            if "content" in delta and delta["content"]:
                yield TextDeltaEvent(text=delta["content"])

            if "tool_calls" in delta:
                for tc in delta["tool_calls"]:
                    self._accumulate_tool_call(tc, accumulated_tool_calls)

            if choice.get("finish_reason"):
                for idx, tc_data in accumulated_tool_calls.items():
                    args_str = tc_data["arguments"]
                    try:
                        arguments = json.loads(args_str) if args_str else {}
                    except json.JSONDecodeError:
                        arguments = {}
                    yield ToolCallEvent(tool_call_id=tc_data["id"], tool_name=tc_data["name"], input=arguments)
                yield FinishStepEvent(finish_reason=choice["finish_reason"], usage=event.get("usage", {}))
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.debug(f"Failed to parse SSE line: {e}")

    def _accumulate_tool_call(self, tc: dict, accumulated_tool_calls: dict):
        """Accumulate a tool call delta by index."""
        idx = tc.get("index", 0)
        if idx not in accumulated_tool_calls:
            accumulated_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
        if "id" in tc:
            accumulated_tool_calls[idx]["id"] = tc["id"]
        if "function" in tc:
            func = tc["function"]
            if "name" in func:
                accumulated_tool_calls[idx]["name"] = func["name"]
            if "arguments" in func:
                accumulated_tool_calls[idx]["arguments"] += func["arguments"]

    async def chat_stream(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream events (matches opencode's LLM.stream())."""
        messages = self._normalize_messages(messages)
        message_dicts = [m.to_dict() for m in messages]

        transport = self._get_transport
        headers = transport.build_headers(self.api_key)

        max_tokens = kwargs.pop("max_tokens", self.max_tokens) or OUTPUT_TOKEN_MAX
        payload = transport.build_kwargs(model=self.model, messages=message_dicts, tools=tools, max_tokens=max_tokens, stream=True, **kwargs)

        yield StreamEvent(type=EventType.START)
        accumulated_tool_calls = {}

        async with self._client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=headers) as response:
            async for line in response.aiter_lines():
                async for event in self._handle_stream_line(line, accumulated_tool_calls):
                    yield event

    def get_tool_schema(self) -> list[dict]:
        """Get OpenAI function calling format."""
        return []

    def supports_functions(self) -> bool:
        return True
