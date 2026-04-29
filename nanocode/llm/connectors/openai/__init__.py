"""OpenAI-compatible LLM provider with event streaming.

Fully matches opencode architecture: LLM.stream() returns async generator of events.
"""

import json
import logging
import os
from typing import AsyncGenerator, Optional, Dict, Any, List

import httpx

from nanocode.llm.base import LLMBase, Message, ToolCall
from nanocode.llm.router import OUTPUT_TOKEN_MAX
from nanocode.llm.events import (
    StreamEvent, EventType,
    TextDeltaEvent, ToolCallEvent, FinishStepEvent,
    ReasoningDeltaEvent, ReasoningStartEvent, ReasoningEndEvent,
    StreamEvent,
)

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

    async def chat_stream(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream events (matches opencode's LLM.stream())."""
        messages = self._normalize_messages(messages)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            **kwargs,
        }

        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if not max_tokens:
            max_tokens = OUTPUT_TOKEN_MAX
        payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools

        # Yield start event
        yield StreamEvent(type=EventType.START)

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
                    # Note: API may return 'reasoning' (not 'reasoning')
                    reasoning = delta.get("reasoning", "") or delta.get("reasoning", "")
                    if reasoning:
                        yield ReasoningDeltaEvent(
                            id="reasoning_0",
                            text=reasoning,
                        )

                    # Handle text content
                    if "content" in delta:
                        content = delta["content"]
                        if content:  # Only yield if non-empty
                            logger.debug(f"Yielding TextDelta: {content[:50]}...")
                            yield TextDeltaEvent(text=content)

                    # Handle tool calls
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            if "function" in tc:
                                func = tc["function"]
                                args_str = func.get("arguments", "{}")
                                try:
                                    arguments = json.loads(args_str) if args_str else {}
                                except json.JSONDecodeError:
                                    arguments = {}

                                yield ToolCallEvent(
                                    tool_call_id=tc.get("id", ""),
                                    tool_name=func.get("name", ""),
                                    input=arguments,
                                )

                    # Handle finish
                    if choice.get("finish_reason"):
                        yield FinishStepEvent(
                            finish_reason=choice["finish_reason"],
                            usage=event.get("usage", {}),
                        )

                except (json.JSONDecodeError, IndexError, KeyError) as e:
                    logger.debug(f"Failed to parse SSE line: {e}")
                    continue

    def get_tool_schema(self) -> List[dict]:
        """Get OpenAI function calling format."""
        return []

    def supports_functions(self) -> bool:
        return True
