"""Anthropic Claude LLM provider."""

import json
import os
from collections.abc import AsyncIterator

from nanocode.llm.base import LLMBase, LLMResponse, ToolCall
from nanocode.llm.events import (
    EventType,
    FinishStepEvent,
    ReasoningDeltaEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolCallEvent,
)

API_BASE = "https://api.anthropic.com/v1/messages"


class AnthropicLLM(LLMBase):
    """Anthropic Claude provider."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-5",
        proxy: str = None,
        **kwargs,
    ):
        super().__init__(api_key, None, model, proxy=proxy, **kwargs)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._transport = None

    @property
    def _get_transport(self):
        if self._transport is None:
            from nanocode.llm.transports import get_transport
            self._transport = get_transport("anthropic_messages")
        return self._transport

    async def chat(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> LLMResponse:
        """Send a chat completion request."""
        message_dicts = [
            m.to_dict() if hasattr(m, "to_dict") else m
            for m in self._normalize_messages(messages)
        ]

        transport = self._get_transport
        headers = transport.build_headers(self.api_key)

        base_url = kwargs.pop("base_url", API_BASE)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        if not max_tokens:
            max_tokens = 4096

        payload = transport.build_kwargs(
            model=self.model,
            messages=message_dicts,
            tools=tools,
            max_tokens=max_tokens,
            **kwargs,
        )

        response = await self._client.post(
            base_url,
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        nr = transport.normalize_response(data)

        tool_calls = []
        if nr.tool_calls:
            for tc in nr.tool_calls:
                tool_calls.append(
                    ToolCall(
                        name=tc.name,
                        arguments=json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments,
                        id=tc.id,
                    )
                )

        return LLMResponse(
            content=nr.content or "",
            tool_calls=tool_calls,
            finish_reason=nr.finish_reason,
            thinking=nr.reasoning,
        )

    async def chat_stream(
        self, messages: list, tools: list[dict] = None, **kwargs
    ):
        """Stream events from Anthropic. Falls back to chat() collecting."""
        resp = await self.chat(messages, tools, **kwargs)
        yield StreamEvent(type=EventType.START)
        if resp.thinking:
            yield ReasoningDeltaEvent(id="reasoning_0", text=resp.thinking)
        if resp.content:
            yield TextDeltaEvent(text=resp.content)
        for tc in resp.tool_calls:
            yield ToolCallEvent(
                tool_call_id=tc.id or "",
                tool_name=tc.name,
                input=tc.arguments,
            )
        yield FinishStepEvent(
            finish_reason=resp.finish_reason or "",
        )

    def get_tool_schema(self) -> list[dict]:
        """Get Anthropic tool format."""
        return []
