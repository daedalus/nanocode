"""OpenAI Chat Completions transport.

Handles the default api_mode ('chat_completions') used by OpenAI-compatible
providers.  Messages and tools are already in OpenAI format — the main work
is in build_kwargs (max_tokens, reasoning, extra_body) and normalize_response.
"""

from __future__ import annotations

import copy
from typing import Any

from nanocode.llm.transports.base import ProviderTransport
from nanocode.llm.transports.types import (
    NormalizedResponse,
    Usage,
    build_tool_call,
)

# Models that use "developer" role instead of "system"
DEVELOPER_ROLE_MODELS = [
    "o1",
    "o3",
    "o4",
    "gpt-5",
    "codex",
]


class ChatCompletionsTransport(ProviderTransport):
    """Transport for api_mode='chat_completions'."""

    @property
    def api_mode(self) -> str:
        return "chat_completions"

    def convert_messages(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> list[dict[str, Any]]:
        """Sanitize messages for strict Chat Completions providers.

        Strips internal fields that strict providers reject:
        - tool_name on tool-result messages
        - _-prefixed internal scaffolding keys
        """
        needs_sanitize = False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if "tool_name" in msg:
                needs_sanitize = True
                break
            if any(isinstance(k, str) and k.startswith("_") for k in msg):
                needs_sanitize = True
                break

        if not needs_sanitize:
            return messages

        sanitized = copy.deepcopy(messages)
        for msg in sanitized:
            if not isinstance(msg, dict):
                continue
            msg.pop("tool_name", None)
            for key in [k for k in msg if isinstance(k, str) and k.startswith("_")]:
                msg.pop(key, None)
        return sanitized

    def convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Tools are already in OpenAI format — identity."""
        return tools

    def build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params,
    ) -> dict[str, Any]:
        """Build chat.completions.create() payload.

        params (all optional):
            max_tokens: int | None
            temperature: float | None
            reasoning_config: dict | None — {enabled: bool, effort: str}
            provider_profile: ProviderProfile | None
            extra_body_additions: dict | None
            request_overrides: dict | None
            stream: bool — include stream: True (default: True)
        """
        sanitized = self.convert_messages(messages)

        # Developer role swap for reasoning models
        model_lower = (model or "").lower()
        if (
            sanitized
            and isinstance(sanitized[0], dict)
            and sanitized[0].get("role") == "system"
            and any(p in model_lower for p in DEVELOPER_ROLE_MODELS)
        ):
            sanitized = list(sanitized)
            sanitized[0] = {**sanitized[0], "role": "developer"}

        payload: dict[str, Any] = {
            "model": model,
            "messages": sanitized,
            "stream": params.get("stream", True),
        }

        # Temperature
        temperature = params.get("temperature")
        if temperature is not None:
            payload["temperature"] = temperature

        # Max tokens
        max_tokens = params.get("max_tokens")
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # Tools
        if tools:
            payload["tools"] = self.convert_tools(tools)

        # Provider profile extras
        profile = params.get("provider_profile")
        if profile is not None:
            extra_body: dict[str, Any] = {}
            profile_body = profile.build_extra_body(
                session_id=params.get("session_id"),
                model=model,
                base_url=params.get("base_url"),
                reasoning_config=params.get("reasoning_config"),
            )
            if profile_body:
                extra_body.update(profile_body)

            extras, top_level = profile.build_api_kwargs_extras(
                reasoning_config=params.get("reasoning_config"),
                supports_reasoning=params.get("supports_reasoning", False),
                model=model,
                session_id=params.get("session_id"),
            )
            payload.update(top_level)
            if extras:
                extra_body.update(extras)

            if profile.fixed_temperature is not None:
                payload["temperature"] = profile.fixed_temperature

            if extra_body:
                payload["extra_body"] = extra_body

        # extra_body additions (merged into existing extra_body)
        additions = params.get("extra_body_additions")
        if additions:
            current = payload.get("extra_body", {})
            current.update(additions)
            payload["extra_body"] = current

        # Request overrides last
        overrides = params.get("request_overrides")
        if overrides:
            for k, v in overrides.items():
                if k == "extra_body" and isinstance(v, dict):
                    existing = payload.get("extra_body", {})
                    existing.update(v)
                    payload["extra_body"] = existing
                else:
                    payload[k] = v

        # Catch-all: pass through any params not explicitly handled
        _HANDLED = {
            "stream", "temperature", "max_tokens", "reasoning_config",
            "provider_profile", "extra_body_additions", "request_overrides",
            "session_id", "base_url", "supports_reasoning",
        }
        for k, v in params.items():
            if k not in _HANDLED and k not in payload:
                payload[k] = v

        return payload

    def normalize_response(
        self, response: dict[str, Any], **kwargs
    ) -> NormalizedResponse:
        """Normalize OpenAI ChatCompletion dict to NormalizedResponse.

        *response* is a parsed JSON dict from the API.
        """
        choices = response.get("choices", [])
        if not choices:
            return NormalizedResponse(
                content=None,
                tool_calls=None,
                finish_reason="stop",
            )

        choice = choices[0]
        msg = choice.get("message", choice.get("delta", {}))
        finish_reason = choice.get("finish_reason") or "stop"

        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = []
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                tc_provider_data: dict[str, Any] = {}
                extra = tc.get("extra_content")
                if extra is not None:
                    tc_provider_data["extra_content"] = extra
                tool_calls.append(
                    build_tool_call(
                        id=tc.get("id"),
                        name=func.get("name", ""),
                        arguments=func.get("arguments", "{}"),
                        **tc_provider_data,
                    )
                )

        usage = None
        raw_usage = response.get("usage")
        if raw_usage:
            usage = Usage(
                prompt_tokens=raw_usage.get("prompt_tokens", 0) or 0,
                completion_tokens=raw_usage.get("completion_tokens", 0) or 0,
                total_tokens=raw_usage.get("total_tokens", 0) or 0,
            )

        reasoning = msg.get("reasoning")
        reasoning_content = msg.get("reasoning_content")

        provider_data: dict[str, Any] = {}
        if reasoning_content is not None:
            provider_data["reasoning_content"] = reasoning_content

        reasoning_details = msg.get("reasoning_details")
        if reasoning_details:
            provider_data["reasoning_details"] = reasoning_details

        return NormalizedResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning=reasoning,
            usage=usage,
            provider_data=provider_data or None,
        )

    def validate_response(self, response: dict[str, Any]) -> bool:
        if not response:
            return False
        choices = response.get("choices")
        if not choices:
            return False
        return True

    def extract_cache_stats(
        self, response: dict[str, Any]
    ) -> dict[str, int] | None:
        raw_usage = response.get("usage")
        if not raw_usage:
            return None
        details = raw_usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens", 0) or 0
        written = details.get("cache_write_tokens", 0) or 0
        if cached or written:
            return {"cached_tokens": cached, "creation_tokens": written}
        return None


# Auto-register on import
from nanocode.llm.transports import register_transport  # noqa: E402

register_transport("chat_completions", ChatCompletionsTransport)
