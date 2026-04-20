"""OpenAI-compatible LLM provider."""

import json
import logging
import os

# Configure logging for this module (file only, defer to main.py for proper config)
logger = logging.getLogger("nanocode.openai")

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

        # DEBUG: Print request details
        # DEBUG: Print each message in detail
        print(f"\n[DEBUG] OpenAI Request:")
        print(f"  URL: {self.base_url}/chat/completions")
        print(f"  Model: {payload['model']}")
        print(f"  Messages: {len(payload['messages'])}")
        for i, m in enumerate(payload['messages']):
            msg_role = m.get('role', '?')
            msg_content = str(m.get('content', ''))
            print(f"    [{i}] {msg_role}: {msg_content[:100]}...")
            if m.get('tool_calls'):
                print(f"        tool_calls: {json.dumps(m['tool_calls'])[:500]}")
            if msg_role == 'tool':
                print(f"        tool_call_id: {m.get('tool_call_id')}")
        if payload.get('tools'):
            print(f"  Tools: {len(payload['tools'])} provided")
        if 'max_tokens' in payload:
            print(f"  max_tokens: {payload['max_tokens']}")

        # Add max_tokens - default to 4096 for OpenRouter to avoid 402
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if not max_tokens:
            max_tokens = 4096
        payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools

        def on_retry(error: Exception, attempt: int):
            print(f"\n  \033[93mRate limited, retrying (attempt {attempt})...\033[0m")

        # DEBUG: Log full request payload
        logger.debug(f"[OpenAI] Request payload: {json.dumps(payload)}")
        print(f"\n[DEBUG] OpenAI Request payload:")
        print(f"  URL: {self.base_url}/chat/completions")
        print(f"  Model: {payload['model']}")
        print(f"  Message order:")
        for i, m in enumerate(payload['messages']):
            role = m.get('role', '?')
            content = str(m.get('content', ''))
            tc = m.get('tool_calls')
            tid = m.get('tool_call_id')
            print(f"    [{i}] {role}: {content} tool_calls={bool(tc)} tool_call_id={tid}")
        print(f"  Full messages JSON: {json.dumps(payload['messages'], indent=2)}")
        if payload.get('tools'):
            print(f"  Tools: {len(payload['tools'])} (first: {payload['tools'][0].get('name', 'unknown')})")
        print(f"  max_tokens: {payload.get('max_tokens')}")
        
        response = await self._request_with_retry(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            on_retry=on_retry,
        )
        
        # Debug: Print status code
        status_code = response.status_code
        print(f"[DEBUG] HTTP Response status: {status_code}")
        
        data = response.json()

        # DEBUG: Print raw response on error
        if response.status_code != 200:
            print(f"[DEBUG] OpenAI Raw response: status={response.status_code}, data={data}")
            logger.error(f"[OpenAI] API Error: status={response.status_code}, data={data}")
        # DEBUG: Print response
        if "error" in data:
            print(f"[DEBUG] OpenAI Error: {data}")
            logger.error(f"[OpenAI] API Error: {data}")
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
