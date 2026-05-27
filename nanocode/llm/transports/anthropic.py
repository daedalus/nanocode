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

    def _convert_system_msg(self, content) -> str | None:
        if content:
            return content if isinstance(content, str) else json.dumps(content)
        return None

    def _convert_tool_result(self, msg: dict) -> dict:
        return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": msg.get("tool_call_id", ""), "content": msg.get("content", "") if isinstance(msg.get("content"), str) else str(msg.get("content", ""))}]}

    def _convert_assistant_with_tools(self, msg: dict) -> dict:
        blocks: list[dict[str, Any]] = []
        content = msg.get("content", "")
        if content:
            blocks.append({"type": "text", "text": content})
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            input_val = json.loads(args) if isinstance(args, str) else (args or {})
            blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": func.get("name", ""), "input": input_val})
        return {"role": "assistant", "content": blocks}

    def convert_messages(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> dict[str, Any]:
        """Convert OpenAI-format messages to Anthropic format."""
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                part = self._convert_system_msg(msg.get("content", ""))
                if part:
                    system_parts.append(part)
            elif role == "tool":
                converted.append(self._convert_tool_result(msg))
            elif role == "assistant" and msg.get("tool_calls"):
                converted.append(self._convert_assistant_with_tools(msg))
            elif role == "user" and isinstance(msg.get("content"), list):
                converted.append({"role": "user", "content": msg["content"]})
            else:
                converted.append({"role": role, "content": msg.get("content", "")})

        return {"system": "\n\n".join(system_parts) if system_parts else None, "messages": converted}

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

        # Catch-all: pass through any params not explicitly handled
        _HANDLED = {"max_tokens", "temperature", "reasoning_config"}
        for k, v in params.items():
            if k not in _HANDLED and k not in payload:
                payload[k] = v

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

    def _normalize_blocks_dict(self, content_blocks: list) -> tuple[list[str], list[str], list]:
        """Process content blocks from dict response."""
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_list: list[ToolCall] = []
        for block in content_blocks:
            t = block.get("type", "")
            if t == "text":
                text_parts.append(block.get("text", ""))
            elif t == "thinking":
                reasoning_parts.append(block.get("thinking", ""))
            elif t == "tool_use":
                tool_calls_list.append(build_tool_call(id=block.get("id"), name=block.get("name", ""), arguments=block.get("input", {})))
        return text_parts, reasoning_parts, tool_calls_list

    def _normalize_blocks_sdk(self, content_blocks: list) -> tuple[list[str], list[str], list[dict], list]:
        """Process content blocks from SDK response."""
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        reasoning_details: list[dict] = []
        tool_calls_list: list[ToolCall] = []
        for block in content_blocks:
            t = getattr(block, "type", "")
            if t == "text":
                text_parts.append(getattr(block, "text", ""))
            elif t == "thinking":
                reasoning_parts.append(getattr(block, "thinking", ""))
                bd = self._to_plain_data(block)
                if bd:
                    reasoning_details.append(bd)
            elif t == "tool_use":
                tool_calls_list.append(build_tool_call(id=getattr(block, "id", None), name=getattr(block, "name", ""), arguments=getattr(block, "input", {})))
        return text_parts, reasoning_parts, reasoning_details, tool_calls_list

    def _build_usage_from_dict(self, raw_usage) -> None:
        if not raw_usage:
            return None
        from nanocode.llm.transports.types import Usage
        return Usage(
            prompt_tokens=raw_usage.get("input_tokens", 0) or 0,
            completion_tokens=raw_usage.get("output_tokens", 0) or 0,
            total_tokens=(raw_usage.get("input_tokens", 0) or 0) + (raw_usage.get("output_tokens", 0) or 0),
        )

    def _build_usage_from_sdk(self, raw_usage) -> None:
        if not raw_usage:
            return None
        from nanocode.llm.transports.types import Usage
        return Usage(
            prompt_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
            total_tokens=(getattr(raw_usage, "input_tokens", 0) or 0) + (getattr(raw_usage, "output_tokens", 0) or 0),
        )

    def _normalize_from_dict(self, response: dict[str, Any]) -> NormalizedResponse:
        text_parts, reasoning_parts, tool_calls_list = self._normalize_blocks_dict(response.get("content", []))
        finish_reason = self.map_finish_reason(response.get("stop_reason", ""))
        usage = self._build_usage_from_dict(response.get("usage"))
        provider_data = {"reasoning_details": [{"type": "thinking", "thinking": t} for t in reasoning_parts]} if reasoning_parts else {}
        return NormalizedResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls_list or None,
            finish_reason=finish_reason,
            reasoning="\n\n".join(reasoning_parts) if reasoning_parts else None,
            usage=usage,
            provider_data=provider_data or None,
        )

    def _normalize_from_sdk(self, response: Any) -> NormalizedResponse:
        content = getattr(response, "content", []) or []
        text_parts, reasoning_parts, reasoning_details, tool_calls_list = self._normalize_blocks_sdk(content)
        stop_reason = getattr(response, "stop_reason", "")
        finish_reason = self.map_finish_reason(stop_reason)
        usage = self._build_usage_from_sdk(getattr(response, "usage", None))
        provider_data = {"reasoning_details": reasoning_details} if reasoning_details else {}
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
