"""Anthropic Messages API transport.

Handles api_mode='anthropic_messages': converts OpenAI-format messages to
Anthropic format, builds messages.create() kwargs, and normalizes responses.
"""

from __future__ import annotations

import json
from typing import Any

from nanocode.llm.transports.base import ProviderTransport
from nanocode.llm.transports.types import (
    NormalizedResponse,
    ToolCall,
    build_tool_call,
)

# SDK response objects have attributes, not dict keys.
# Maps Anthropic stop_reason → OpenAI finish_reason.
_STOP_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "stop_sequence": "stop",
    "refusal": "content_filter",
    "model_context_window_exceeded": "length",
}


class AnthropicTransport(ProviderTransport):
    """Transport for api_mode='anthropic_messages'."""

    @property
    def api_mode(self) -> str:
        return "anthropic_messages"

    def build_headers(self, api_key: str) -> dict[str, str]:
        """Anthropic uses x-api-key header."""
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def convert_messages(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> dict[str, Any]:
        """Convert OpenAI-format messages to Anthropic (system, messages) tuple.

        Returns {"system": str | None, "messages": list[dict]}.
        """
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # System role → separate system parameter
            if role == "system":
                if content:
                    system_parts.append(content if isinstance(content, str) else json.dumps(content))
                continue

            # Tool result → tool_result block
            if role == "tool":
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": content if isinstance(content, str) else str(content),
                        }
                    ],
                })
                continue

            # Tool calls → assistant message with tool_use blocks
            if role == "assistant" and msg.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else (func.get("arguments") or {}),
                    })
                converted.append({"role": "assistant", "content": blocks})
                continue

            # User message with tool_result parts
            if role == "user" and isinstance(content, list):
                converted.append({"role": "user", "content": content})
                continue

            # Default: pass through as-is
            converted.append({"role": role, "content": content})

        return {
            "system": "\n\n".join(system_parts) if system_parts else None,
            "messages": converted,
        }

    def convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI tool schemas to Anthropic input_schema format."""
        converted = []
        for tool in tools:
            func = tool.get("function", tool)
            params = func.get("parameters", {})
            anthropic_tool = {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": {
                    "type": params.get("type", "object"),
                    "properties": params.get("properties", {}),
                },
            }
            if params.get("required"):
                anthropic_tool["input_schema"]["required"] = params["required"]
            converted.append(anthropic_tool)
        return converted

    def build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params,
    ) -> dict[str, Any]:
        """Build Anthropic messages.create() kwargs.

        Calls convert_messages and convert_tools internally.

        params (all optional):
            max_tokens: int
            reasoning_config: dict | None
            temperature: float | None
        """
        converted = self.convert_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": converted["messages"],
            "max_tokens": params.get("max_tokens", 4096),
        }

        if converted["system"]:
            payload["system"] = converted["system"]

        if tools:
            payload["tools"] = self.convert_tools(tools)

        temperature = params.get("temperature")
        if temperature is not None:
            payload["temperature"] = temperature

        return payload

    def normalize_response(
        self, response: Any, **kwargs
    ) -> NormalizedResponse:
        """Normalize Anthropic response to NormalizedResponse.

        *response* can be a dict or an SDK response object (with .content, .stop_reason).
        """
        # Handle both SDK objects and plain dicts
        if isinstance(response, dict):
            return self._normalize_from_dict(response)
        return self._normalize_from_sdk(response)

    def _normalize_from_dict(self, response: dict[str, Any]) -> NormalizedResponse:
        """Normalize from a parsed JSON dict."""
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_list: list[ToolCall] = []

        for block in response.get("content", []):
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "thinking":
                reasoning_parts.append(block.get("thinking", ""))
            elif block_type == "tool_use":
                tc_input = block.get("input", {})
                tool_calls_list.append(
                    build_tool_call(
                        id=block.get("id"),
                        name=block.get("name", ""),
                        arguments=tc_input,
                    )
                )

        finish_reason = self.map_finish_reason(
            response.get("stop_reason", "")
        )

        usage = None
        raw_usage = response.get("usage")
        if raw_usage:
            from nanocode.llm.transports.types import Usage
            usage = Usage(
                prompt_tokens=raw_usage.get("input_tokens", 0) or 0,
                completion_tokens=raw_usage.get("output_tokens", 0) or 0,
                total_tokens=(raw_usage.get("input_tokens", 0) or 0)
                + (raw_usage.get("output_tokens", 0) or 0),
            )

        provider_data: dict[str, Any] = {}
        if reasoning_parts:
            provider_data["reasoning_details"] = [
                {"type": "thinking", "thinking": t} for t in reasoning_parts
            ]

        return NormalizedResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls_list or None,
            finish_reason=finish_reason,
            reasoning="\n\n".join(reasoning_parts) if reasoning_parts else None,
            usage=usage,
            provider_data=provider_data or None,
        )

    def _normalize_from_sdk(self, response: Any) -> NormalizedResponse:
        """Normalize from an Anthropic SDK response object."""
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        reasoning_details: list[dict[str, Any]] = []
        tool_calls_list: list[ToolCall] = []

        content = getattr(response, "content", []) or []
        for block in content:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            elif block_type == "thinking":
                reasoning_parts.append(getattr(block, "thinking", ""))
                block_dict = self._to_plain_data(block)
                if block_dict:
                    reasoning_details.append(block_dict)
            elif block_type == "tool_use":
                tc_input = getattr(block, "input", {})
                tool_calls_list.append(
                    build_tool_call(
                        id=getattr(block, "id", None),
                        name=getattr(block, "name", ""),
                        arguments=tc_input,
                    )
                )

        stop_reason = getattr(response, "stop_reason", "")
        finish_reason = self.map_finish_reason(stop_reason)

        usage = None
        raw_usage = getattr(response, "usage", None)
        if raw_usage:
            from nanocode.llm.transports.types import Usage
            usage = Usage(
                prompt_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
                completion_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
                total_tokens=(getattr(raw_usage, "input_tokens", 0) or 0)
                + (getattr(raw_usage, "output_tokens", 0) or 0),
            )

        provider_data: dict[str, Any] = {}
        if reasoning_details:
            provider_data["reasoning_details"] = reasoning_details

        return NormalizedResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls_list or None,
            finish_reason=finish_reason,
            reasoning="\n\n".join(reasoning_parts) if reasoning_parts else None,
            usage=usage,
            provider_data=provider_data or None,
        )

    @staticmethod
    def _to_plain_data(obj: Any) -> dict[str, Any] | None:
        """Extract a plain dict from an SDK object, if possible."""
        if hasattr(obj, "model_dump"):
            try:
                result = obj.model_dump()
                if isinstance(result, dict):
                    return result
                return None
            except Exception:
                return None
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return None

    def validate_response(self, response: Any) -> bool:
        if response is None:
            return False
        if isinstance(response, dict):
            content_blocks = response.get("content")
        else:
            content_blocks = getattr(response, "content", None)
        if not isinstance(content_blocks, list):
            return False
        if not content_blocks:
            stop_reason = (
                response.get("stop_reason", "")
                if isinstance(response, dict)
                else getattr(response, "stop_reason", "")
            )
            return stop_reason == "end_turn"
        return True

    def extract_cache_stats(self, response: Any) -> dict[str, int] | None:
        if isinstance(response, dict):
            usage = response.get("usage")
        else:
            usage = getattr(response, "usage", None)
        if usage is None:
            return None
        cached = (
            usage.get("cache_read_input_tokens", 0)
            if isinstance(usage, dict)
            else getattr(usage, "cache_read_input_tokens", 0) or 0
        )
        written = (
            usage.get("cache_creation_input_tokens", 0)
            if isinstance(usage, dict)
            else getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        if cached or written:
            return {"cached_tokens": cached, "creation_tokens": written}
        return None

    def map_finish_reason(self, raw_reason: str) -> str:
        return _STOP_REASON_MAP.get(raw_reason, "stop")


# Auto-register on import
from nanocode.llm.transports import register_transport  # noqa: E402

register_transport("anthropic_messages", AnthropicTransport)
