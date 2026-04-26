"""Base classes for LLM providers."""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx
from httpx import HTTPStatusError

from nanocode.retry import (
    ProviderOverloadedError,
    RateLimitError,
    RetryConfig,
    retry_with_backoff,
)
from nanocode.tools import ToolCall


logger = logging.getLogger(__name__)


class Message:
    """Represents a message in the conversation."""

    def __init__(
        self,
        role: str,
        content: Any,
        tool_calls: list[ToolCall] = None,
        tool_call_id: str = None,
    ):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id

    def to_dict(self) -> dict:
        """Convert to provider-specific format."""
        # When content is empty or a list, convert to string for OpenAI compatibility
        content = self.content
        if content is None or (isinstance(content, list) and not content):
            content = ""

        result = {"role": self.role, "content": content}
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
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
                args_str = func.get("arguments", "{}")
                try:
                    arguments = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(
                    ToolCall(
                        name=func.get("name", ""),
                        arguments=arguments,
                        id=tc.get("id"),
                    )
                )

        # Extract tool_call_id from content parts if present (for tool role messages)
        tool_call_id = data.get("tool_call_id")
        content = data.get("content", "")
        if tool_call_id is None and isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_call_id = part.get("tool_call_id")
                    break

        return cls(
            role=data.get("role", "user"),
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )


class LLMResponse:
    """Standardized LLM response."""

    def __init__(
        self,
        content: str,
        tool_calls: list[ToolCall] = None,
        finish_reason: str = None,
        thinking: str = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason
        self.thinking = thinking

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMBase(ABC):
    """Abstract base class for LLM providers."""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None,
        retry_config: RetryConfig = None,
        user_agent: str = None,
        proxy: str = None,
        debug: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or os.getenv("API_KEY")
        self.base_url = base_url
        self.model = model
        self.max_tokens = kwargs.pop("max_tokens", None)
        self.extra_kwargs = kwargs
        self.retry_config = retry_config or RetryConfig.default()
        self.user_agent = user_agent or "nanocode/1.0"
        self.debug = debug
        self.proxy = proxy

    @abstractmethod
    async def chat(
        self, messages: list, tools: list[dict] = None, **kwargs
    ) -> LLMResponse:
        """Send a chat completion request."""
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

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        headers: dict = None,
        json: dict = None,
        on_retry: callable = None,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with retry logic."""

        if headers is None:
            headers = {}
        if "User-Agent" not in headers:
            headers["User-Agent"] = self.user_agent

        async def make_request():
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    timeout=120.0,
                    **kwargs,
                )

                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    error = RateLimitError(
                        f"Rate limited: {response.text[:200]}",
                        retry_after=float(retry_after) if retry_after else None,
                    )
                    raise error

                try:
                    data = response.json()
                    if data.get("error"):
                        error_msg = data["error"].get("message", "")
                        if (
                            "rate limit" in error_msg.lower()
                            or "free_usage" in error_msg.lower()
                        ):
                            error = RateLimitError(f"Rate limited: {error_msg}")
                            raise error
                except Exception:
                    logger.debug("Failed to extract error details from response")
                    pass

                if (
                    response.status_code == 500
                    or response.status_code == 503
                    or "overloaded" in response.text.lower()
                ):
                    raise ProviderOverloadedError(
                        f"Provider overloaded ({response.status_code}): {response.text[:200]}"
                    )

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        print(f"[DEBUG] Raw error JSON: {error_data}")
                        raw_error = (
                            error_data.get("error", {})
                            .get("metadata", {})
                            .get("raw", "")
                        )
                        if raw_error:
                            try:
                                raw_json = json.loads(raw_error)
                                error_msg = raw_json.get("error", {}).get(
                                    "message", raw_error
                                )
                            except Exception:
                                error_msg = error_data.get("error", {}).get(
                                    "message", response.text[:300]
                                )
                        else:
                            error_msg = error_data.get("error", {}).get(
                                "message", response.text[:300]
                            )
                    except Exception:
                        error_msg = response.text[:300]
                    print(f"[DEBUG] Error msg extracted: {error_msg}")
                    raise HTTPStatusError(
                        f"{response.status_code} {response.reason_phrase}: {error_msg}",
                        request=response.request,
                        response=response,
                    )

                return response

        if self.retry_config.max_retries > 0:
            return await retry_with_backoff(
                make_request, self.retry_config, on_retry=on_retry
            )
        else:
            return await make_request()

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
