"""Tests for nanocode.llm.transports."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from nanocode.llm.transports import (
    NormalizedResponse,
    ToolCall,
    Usage,
    build_tool_call,
    get_transport,
    map_finish_reason,
    register_transport,
)
from nanocode.llm.transports.base import ProviderTransport

# ── Helpers ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the transport registry before and after each test."""
    import nanocode.llm.transports as reg

    _PARENT = "nanocode.llm.transports"
    for modname in list(sys.modules.keys()):
        if modname.startswith(_PARENT + ".") and "test" not in modname:
            del sys.modules[modname]
    reg._REGISTRY.clear()
    reg._discovered = False
    yield
    for modname in list(sys.modules.keys()):
        if modname.startswith(_PARENT + ".") and "test" not in modname:
            del sys.modules[modname]
    reg._REGISTRY.clear()
    reg._discovered = False


# ── Types ───────────────────────────────────────────────────────────

class TestToolCall:
    def test_minimal(self):
        tc = ToolCall(id="call_1", name="get_weather", arguments="{}")
        assert tc.id == "call_1"
        assert tc.name == "get_weather"
        assert tc.arguments == "{}"

    def test_with_provider_data(self):
        tc = ToolCall(
            id="call_1", name="search", arguments='{"q":"hello"}',
            provider_data={"extra_content": {"thought_signature": "abc"}},
        )
        assert tc.provider_data["extra_content"]["thought_signature"] == "abc"

    def test_function_property(self):
        tc = ToolCall(id="c1", name="f", arguments="{}")
        assert tc.function is tc
        assert tc.function.name == "f"

    def test_call_id_property(self):
        tc = ToolCall(id="c1", name="f", arguments="{}",
                      provider_data={"call_id": "call_X"})
        assert tc.call_id == "call_X"

    def test_call_id_none_when_no_provider_data(self):
        tc = ToolCall(id="c1", name="f", arguments="{}")
        assert tc.call_id is None


class TestUsage:
    def test_defaults(self):
        u = Usage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0
        assert u.cached_tokens == 0

    def test_with_values(self):
        u = Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30, cached_tokens=5)
        assert u.prompt_tokens == 10
        assert u.completion_tokens == 20
        assert u.total_tokens == 30
        assert u.cached_tokens == 5


class TestNormalizedResponse:
    def test_minimal(self):
        nr = NormalizedResponse(content=None, tool_calls=None, finish_reason="stop")
        assert nr.content is None
        assert nr.tool_calls is None
        assert nr.finish_reason == "stop"
        assert nr.reasoning is None
        assert nr.usage is None

    def test_with_content_and_tool_calls(self):
        tc = ToolCall(id="c1", name="f", arguments="{}")
        nr = NormalizedResponse(
            content="Hello", tool_calls=[tc], finish_reason="tool_calls",
        )
        assert nr.content == "Hello"
        assert len(nr.tool_calls) == 1
        assert nr.tool_calls[0].name == "f"

    def test_with_reasoning(self):
        nr = NormalizedResponse(
            content="Answer", tool_calls=None, finish_reason="stop",
            reasoning="Let me think...",
        )
        assert nr.reasoning == "Let me think..."

    def test_with_usage(self):
        u = Usage(prompt_tokens=5, completion_tokens=10)
        nr = NormalizedResponse(
            content="Hi", tool_calls=None, finish_reason="stop", usage=u,
        )
        assert nr.usage.prompt_tokens == 5

    def test_reasoning_content_property(self):
        nr = NormalizedResponse(
            content="Hi", tool_calls=None, finish_reason="stop",
            provider_data={"reasoning_content": "thinking..."},
        )
        assert nr.reasoning_content == "thinking..."

    def test_reasoning_content_none_when_no_provider_data(self):
        nr = NormalizedResponse(content="Hi", tool_calls=None, finish_reason="stop")
        assert nr.reasoning_content is None


class TestBuildToolCall:
    def test_with_dict_arguments(self):
        tc = build_tool_call("c1", "search", {"q": "hello"})
        assert tc.id == "c1"
        assert tc.name == "search"
        assert json.loads(tc.arguments) == {"q": "hello"}

    def test_with_string_arguments(self):
        tc = build_tool_call("c1", "search", '{"q":"hello"}')
        assert tc.arguments == '{"q":"hello"}'

    def test_with_provider_fields(self):
        tc = build_tool_call("c1", "f", {}, extra_field="val")
        assert tc.provider_data == {"extra_field": "val"}

    def test_no_provider_data_when_no_extra_args(self):
        tc = build_tool_call("c1", "f", {})
        assert tc.provider_data is None


class TestMapFinishReason:
    def test_known_reason(self):
        result = map_finish_reason("tool_use", {"tool_use": "tool_calls"})
        assert result == "tool_calls"

    def test_unknown_reason(self):
        result = map_finish_reason("bogus", {"stop": "stop"})
        assert result == "stop"

    def test_none_reason(self):
        result = map_finish_reason(None, {})
        assert result == "stop"


# ── Registry ────────────────────────────────────────────────────────

class FakeTransport(ProviderTransport):
    @property
    def api_mode(self):
        return "fake"
    def convert_messages(self, messages, **kwargs):
        return messages
    def convert_tools(self, tools):
        return tools
    def build_kwargs(self, model, messages, tools=None, **params):
        return {"model": model, "messages": messages}
    def normalize_response(self, response, **kwargs):
        return NormalizedResponse(content="ok", tool_calls=None, finish_reason="stop")


class TestRegistry:
    def test_register_and_get(self):
        register_transport("fake", FakeTransport)
        t = get_transport("fake")
        assert t is not None
        assert isinstance(t, FakeTransport)

    def test_get_nonexistent_returns_none(self):
        t = get_transport("no-such-transport")
        assert t is None

    def test_discovery_imports_chat_completions(self):
        with patch.dict(sys.modules, {}):
            reg = sys.modules.get("nanocode.llm.transports")
            if reg:
                reg._discovered = False
                reg._REGISTRY.clear()
        t = get_transport("chat_completions")
        assert t is not None
        assert t.api_mode == "chat_completions"

    def test_discovery_imports_anthropic(self):
        with patch.dict(sys.modules, {}):
            reg = sys.modules.get("nanocode.llm.transports")
            if reg:
                reg._discovered = False
                reg._REGISTRY.clear()
        t = get_transport("anthropic_messages")
        assert t is not None
        assert t.api_mode == "anthropic_messages"


# ── ChatCompletionsTransport ────────────────────────────────────────

class TestChatCompletionsTransport:
    def _get_transport(self):
        t = get_transport("chat_completions")
        assert t is not None
        return t

    def test_api_mode(self):
        t = self._get_transport()
        assert t.api_mode == "chat_completions"

    def test_build_headers(self):
        t = self._get_transport()
        headers = t.build_headers("sk-test")
        assert headers["Authorization"] == "Bearer sk-test"
        assert headers["Content-Type"] == "application/json"

    def test_build_kwargs_basic(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
        )
        assert kwargs["model"] == "gpt-4"
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
        assert kwargs["stream"] is True

    def test_build_kwargs_with_tools(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
            tools=[{"function": {"name": "get_weather", "parameters": {"type": "object"}}}],
        )
        assert "tools" in kwargs
        assert kwargs["tools"][0]["function"]["name"] == "get_weather"

    def test_build_kwargs_with_temperature(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
        assert kwargs["temperature"] == 0.7

    def test_build_kwargs_with_max_tokens(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
            max_tokens=4096,
        )
        assert kwargs["max_tokens"] == 4096

    def test_build_kwargs_developer_role_swap(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "o1-preview",
            [{"role": "system", "content": "You are helpful"},
             {"role": "user", "content": "hi"}],
        )
        assert kwargs["messages"][0]["role"] == "developer"

    def test_build_kwargs_no_dev_swap_non_developer_model(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "system", "content": "You are helpful"}],
        )
        assert kwargs["messages"][0]["role"] == "system"

    def test_build_kwargs_sanitizes_internal_fields(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi", "_internal_flag": "yes", "tool_name": "search"}],
        )
        msg = kwargs["messages"][0]
        assert "_internal_flag" not in msg
        assert "tool_name" not in msg

    def test_build_kwargs_with_extra_body_additions(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
            extra_body_additions={"custom_field": "val"},
        )
        assert kwargs["extra_body"]["custom_field"] == "val"

    def test_build_kwargs_with_request_overrides(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
            request_overrides={"service_tier": "auto"},
        )
        assert kwargs["service_tier"] == "auto"

    def test_build_kwargs_with_request_overrides_extra_body(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "gpt-4",
            [{"role": "user", "content": "hi"}],
            request_overrides={"extra_body": {"metadata": {"user": "test"}}},
        )
        assert kwargs["extra_body"]["metadata"]["user"] == "test"

    def test_normalize_response_text(self):
        t = self._get_transport()
        resp = {
            "choices": [
                {
                    "index": 0,
                    "message": {"content": "Hello world"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        nr = t.normalize_response(resp)
        assert nr.content == "Hello world"
        assert nr.finish_reason == "stop"
        assert nr.tool_calls is None
        assert nr.usage.prompt_tokens == 10
        assert nr.usage.completion_tokens == 20

    def test_normalize_response_tool_calls(self):
        t = self._get_transport()
        resp = {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "get_weather", "arguments": '{"loc":"NYC"}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        nr = t.normalize_response(resp)
        assert nr.content is None
        assert nr.finish_reason == "tool_calls"
        assert len(nr.tool_calls) == 1
        assert nr.tool_calls[0].id == "call_1"
        assert nr.tool_calls[0].name == "get_weather"
        assert json.loads(nr.tool_calls[0].arguments) == {"loc": "NYC"}

    def test_normalize_response_reasoning(self):
        t = self._get_transport()
        resp = {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "content": "Answer",
                        "reasoning": "Let me think...",
                        "reasoning_content": "Step by step...",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        nr = t.normalize_response(resp)
        assert nr.reasoning == "Let me think..."
        assert nr.reasoning_content == "Step by step..."

    def test_normalize_response_empty_choices(self):
        t = self._get_transport()
        resp = {"choices": []}
        nr = t.normalize_response(resp)
        assert nr.content is None
        assert nr.finish_reason == "stop"

    def test_normalize_response_no_choices(self):
        t = self._get_transport()
        resp = {}
        nr = t.normalize_response(resp)
        assert nr.content is None
        assert nr.finish_reason == "stop"

    def test_validate_response_valid(self):
        t = self._get_transport()
        assert t.validate_response({"choices": [{}]}) is True

    def test_validate_response_none(self):
        t = self._get_transport()
        assert t.validate_response(None) is False

    def test_validate_response_no_choices(self):
        t = self._get_transport()
        assert t.validate_response({"choices": []}) is False

    def test_extract_cache_stats_present(self):
        t = self._get_transport()
        resp = {
            "usage": {
                "prompt_tokens_details": {"cached_tokens": 50, "cache_write_tokens": 10},
            }
        }
        stats = t.extract_cache_stats(resp)
        assert stats == {"cached_tokens": 50, "creation_tokens": 10}

    def test_extract_cache_stats_none(self):
        t = self._get_transport()
        assert t.extract_cache_stats({}) is None
        assert t.extract_cache_stats({"usage": {}}) is None

    def test_convert_messages_passthrough(self):
        t = self._get_transport()
        msgs = [{"role": "user", "content": "hi"}]
        result = t.convert_messages(msgs)
        assert result is msgs

    def test_convert_messages_sanitize_tool_name(self):
        t = self._get_transport()
        msgs = [{"role": "tool", "tool_call_id": "c1", "content": "result", "tool_name": "search"}]
        result = t.convert_messages(msgs)
        assert "tool_name" not in result[0]

    def test_convert_messages_sanitize_internal_keys(self):
        t = self._get_transport()
        msgs = [{"role": "user", "content": "hi", "_my_flag": True}]
        result = t.convert_messages(msgs)
        assert "_my_flag" not in result[0]

    def test_convert_tools_identity(self):
        t = self._get_transport()
        tools = [{"function": {"name": "f"}}]
        result = t.convert_tools(tools)
        assert result is tools


# ── AnthropicTransport ──────────────────────────────────────────────

class TestAnthropicTransport:
    def _get_transport(self):
        t = get_transport("anthropic_messages")
        assert t is not None
        return t

    def test_api_mode(self):
        t = self._get_transport()
        assert t.api_mode == "anthropic_messages"

    def test_build_headers(self):
        t = self._get_transport()
        headers = t.build_headers("sk-ant-test")
        assert headers["x-api-key"] == "sk-ant-test"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_convert_messages_basic(self):
        t = self._get_transport()
        result = t.convert_messages([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ])
        assert result["system"] == "You are helpful"
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "assistant"

    def test_convert_messages_tool_result(self):
        t = self._get_transport()
        result = t.convert_messages([
            {"role": "user", "content": "What's the weather?"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "get_weather", "arguments": '{"loc":"NYC"}'}},
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "Sunny"},
        ])
        assert result["system"] is None
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "assistant"
        assert result["messages"][1]["content"][0]["type"] == "tool_use"
        assert result["messages"][2]["role"] == "user"
        assert result["messages"][2]["content"][0]["type"] == "tool_result"

    def test_convert_messages_multiple_system_parts(self):
        t = self._get_transport()
        result = t.convert_messages([
            {"role": "system", "content": "Part 1"},
            {"role": "system", "content": "Part 2"},
            {"role": "user", "content": "Hi"},
        ])
        assert "Part 1" in result["system"]
        assert "Part 2" in result["system"]
        assert len(result["messages"]) == 1

    def test_convert_tools(self):
        t = self._get_transport()
        tools = [{
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {
                    "type": "object",
                    "properties": {"loc": {"type": "string"}},
                    "required": ["loc"],
                },
            }
        }]
        result = t.convert_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["input_schema"]["properties"]["loc"]["type"] == "string"
        assert result[0]["input_schema"]["required"] == ["loc"]

    def test_build_kwargs_basic(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "claude-sonnet-4-5",
            [{"role": "user", "content": "Hi"}],
        )
        assert kwargs["model"] == "claude-sonnet-4-5"
        assert kwargs["messages"][0]["role"] == "user"
        assert kwargs["max_tokens"] == 4096

    def test_build_kwargs_with_system(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "claude-sonnet-4-5",
            [{"role": "system", "content": "Be helpful"},
             {"role": "user", "content": "Hi"}],
        )
        assert kwargs["system"] == "Be helpful"

    def test_build_kwargs_with_tools(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "claude-sonnet-4-5",
            [{"role": "user", "content": "Hi"}],
            tools=[{"function": {"name": "get_weather", "parameters": {"type": "object", "properties": {}}}}],
        )
        assert "tools" in kwargs
        assert kwargs["tools"][0]["name"] == "get_weather"

    def test_build_kwargs_with_temperature(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "claude-sonnet-4-5",
            [{"role": "user", "content": "Hi"}],
            temperature=0.5,
        )
        assert kwargs["temperature"] == 0.5

    def test_build_kwargs_custom_max_tokens(self):
        t = self._get_transport()
        kwargs = t.build_kwargs(
            "claude-sonnet-4-5",
            [{"role": "user", "content": "Hi"}],
            max_tokens=8192,
        )
        assert kwargs["max_tokens"] == 8192

    def test_normalize_response_dict_text(self):
        t = self._get_transport()
        resp = {
            "content": [{"type": "text", "text": "Hello world"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 25},
        }
        nr = t.normalize_response(resp)
        assert nr.content == "Hello world"
        assert nr.finish_reason == "stop"
        assert nr.tool_calls is None
        assert nr.usage.prompt_tokens == 10
        assert nr.usage.completion_tokens == 25

    def test_normalize_response_dict_thinking(self):
        t = self._get_transport()
        resp = {
            "content": [
                {"type": "thinking", "thinking": "Let me think about this..."},
                {"type": "text", "text": "Here is my answer"},
            ],
            "stop_reason": "end_turn",
        }
        nr = t.normalize_response(resp)
        assert nr.reasoning == "Let me think about this..."
        assert nr.content == "Here is my answer"

    def test_normalize_response_dict_tool_use(self):
        t = self._get_transport()
        resp = {
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"loc": "NYC"}},
            ],
            "stop_reason": "tool_use",
        }
        nr = t.normalize_response(resp)
        assert nr.content is None
        assert nr.finish_reason == "tool_calls"
        assert len(nr.tool_calls) == 1
        assert nr.tool_calls[0].id == "tu_1"
        assert nr.tool_calls[0].name == "get_weather"
        assert json.loads(nr.tool_calls[0].arguments) == {"loc": "NYC"}

    def test_normalize_response_dict_stop_reason_mapping(self):
        t = self._get_transport()
        for input_reason, expected in [
            ("end_turn", "stop"),
            ("tool_use", "tool_calls"),
            ("max_tokens", "length"),
            ("stop_sequence", "stop"),
            ("refusal", "content_filter"),
            ("model_context_window_exceeded", "length"),
            ("unknown_reason", "stop"),
        ]:
            resp = {"content": [], "stop_reason": input_reason}
            nr = t.normalize_response(resp)
            assert nr.finish_reason == expected, f"{input_reason} → {expected}"

    def test_validate_response_valid(self):
        t = self._get_transport()
        assert t.validate_response({"content": [{"type": "text", "text": "hi"}]}) is True

    def test_validate_response_none(self):
        t = self._get_transport()
        assert t.validate_response(None) is False

    def test_validate_response_no_content(self):
        t = self._get_transport()
        assert t.validate_response({}) is False

    def test_validate_response_empty_content_with_end_turn(self):
        t = self._get_transport()
        assert t.validate_response({"content": [], "stop_reason": "end_turn"}) is True

    def test_validate_response_empty_content_without_end_turn(self):
        t = self._get_transport()
        assert t.validate_response({"content": [], "stop_reason": "tool_use"}) is False

    def test_extract_cache_stats_present(self):
        t = self._get_transport()
        resp = {"usage": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 20}}
        stats = t.extract_cache_stats(resp)
        assert stats == {"cached_tokens": 100, "creation_tokens": 20}

    def test_extract_cache_stats_none(self):
        t = self._get_transport()
        assert t.extract_cache_stats({}) is None
        assert t.extract_cache_stats({"usage": {}}) is None

    def test_extract_cache_stats_sdk_object(self):
        t = self._get_transport()
        mock_usage = MagicMock()
        mock_usage.cache_read_input_tokens = 200
        mock_usage.cache_creation_input_tokens = 50
        mock_resp = MagicMock()
        mock_resp.usage = mock_usage
        stats = t.extract_cache_stats(mock_resp)
        assert stats == {"cached_tokens": 200, "creation_tokens": 50}

    def test_normalize_response_sdk_object(self):
        t = self._get_transport()

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello from SDK"

        mock_resp = MagicMock()
        mock_resp.content = [text_block]
        mock_resp.stop_reason = "end_turn"
        mock_resp.usage = None

        nr = t.normalize_response(mock_resp)
        assert nr.content == "Hello from SDK"
        assert nr.finish_reason == "stop"

    def test_map_finish_reason(self):
        t = self._get_transport()
        assert t.map_finish_reason("end_turn") == "stop"
        assert t.map_finish_reason("tool_use") == "tool_calls"
        assert t.map_finish_reason("bogus") == "stop"


# ── ProviderTransport ABC ───────────────────────────────────────────

class TestProviderTransportABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ProviderTransport()

    def test_default_methods(self):
        class MinimalTransport(ProviderTransport):
            @property
            def api_mode(self):
                return "minimal"
            def convert_messages(self, messages, **kwargs):
                return messages
            def convert_tools(self, tools):
                return tools
            def build_kwargs(self, model, messages, tools=None, **params):
                return {}
            def normalize_response(self, response, **kwargs):
                return NormalizedResponse(content="", tool_calls=None, finish_reason="stop")

        t = MinimalTransport()
        assert t.validate_response(None) is True
        assert t.extract_cache_stats(None) is None
        assert t.map_finish_reason("anything") == "anything"
        headers = t.build_headers("sk-test")
        assert headers["Authorization"] == "Bearer sk-test"
