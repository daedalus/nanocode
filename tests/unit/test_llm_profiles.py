"""Tests for nanocode.llm.profiles."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from nanocode.llm.profiles import (
    OMIT_TEMPERATURE,
    ProviderProfile,
    get_provider_profile,
    list_providers,
    register_provider,
)
from nanocode.llm.profiles.base import _profile_user_agent


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the provider registry before and after each test."""
    import nanocode.llm.profiles as reg

    _PROVIDER_MODULE_PREFIX = "nanocode.llm.profiles.providers."

    for modname in list(sys.modules.keys()):
        if modname.startswith(_PROVIDER_MODULE_PREFIX) or modname == "nanocode.llm.profiles.providers":
            del sys.modules[modname]

    reg._REGISTRY.clear()
    reg._ALIASES.clear()
    reg._discovered = False
    yield

    for modname in list(sys.modules.keys()):
        if modname.startswith(_PROVIDER_MODULE_PREFIX) or modname == "nanocode.llm.profiles.providers":
            del sys.modules[modname]

    reg._REGISTRY.clear()
    reg._ALIASES.clear()
    reg._discovered = False


class TestProviderProfile:
    def test_minimal_profile(self):
        p = ProviderProfile(name="test-provider")
        assert p.name == "test-provider"
        assert p.api_mode == "chat_completions"
        assert p.aliases == ()
        assert p.env_vars == ()
        assert p.base_url == ""
        assert p.auth_type == "api_key"
        assert p.fallback_models == ()

    def test_full_profile(self):
        p = ProviderProfile(
            name="full-test",
            aliases=("ft", "full"),
            api_mode="anthropic_messages",
            env_vars=("TEST_KEY",),
            base_url="https://api.test.com/v1",
            models_url="https://api.test.com/models",
            auth_type="oauth_device_code",
            display_name="Full Test",
            description="A full test provider",
            signup_url="https://test.com/signup",
            fallback_models=("model-a", "model-b"),
            default_max_tokens=4096,
            default_aux_model="small-model",
        )
        assert p.name == "full-test"
        assert "ft" in p.aliases
        assert p.api_mode == "anthropic_messages"
        assert "TEST_KEY" in p.env_vars
        assert p.base_url == "https://api.test.com/v1"
        assert p.auth_type == "oauth_device_code"
        assert p.display_name == "Full Test"
        assert p.fallback_models == ("model-a", "model-b")
        assert p.default_max_tokens == 4096
        assert p.default_aux_model == "small-model"

    def test_default_aux_model(self):
        p = ProviderProfile(name="test")
        assert p.default_aux_model == ""

    def test_fixed_temperature_default_none(self):
        p = ProviderProfile(name="test")
        assert p.fixed_temperature is None

    def test_supports_health_check_default(self):
        p = ProviderProfile(name="test")
        assert p.supports_health_check is True
        p2 = ProviderProfile(name="test", supports_health_check=False)
        assert p2.supports_health_check is False


class TestGetHostname:
    def test_explicit_hostname(self):
        p = ProviderProfile(name="test", hostname="api.test.com")
        assert p.get_hostname() == "api.test.com"

    def test_from_base_url(self):
        p = ProviderProfile(name="test", base_url="https://api.test.com/v1")
        assert p.get_hostname() == "api.test.com"

    def test_no_url_returns_empty(self):
        p = ProviderProfile(name="test")
        assert p.get_hostname() == ""

    def test_from_base_url_with_port(self):
        p = ProviderProfile(name="test", base_url="https://api.test.com:8080/v1")
        assert p.get_hostname() == "api.test.com"


class TestPrepareMessages:
    def test_default_pass_through(self):
        p = ProviderProfile(name="test")
        msgs = [{"role": "user", "content": "hello"}]
        result = p.prepare_messages(msgs)
        assert result is msgs

    def test_custom_override(self):
        class ReverseProfile(ProviderProfile):
            def prepare_messages(self, messages):
                return list(reversed(messages))
        p = ReverseProfile(name="reverse")
        msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        result = p.prepare_messages(msgs)
        assert result[0]["role"] == "assistant"


class TestBuildExtraBody:
    def test_default_empty(self):
        p = ProviderProfile(name="test")
        assert p.build_extra_body() == {}

    def test_with_session_id(self):
        p = ProviderProfile(name="test")
        result = p.build_extra_body(session_id="sess_123")
        assert result == {}


class TestBuildApiKwargsExtras:
    def test_default_empty(self):
        p = ProviderProfile(name="test")
        extra, top = p.build_api_kwargs_extras()
        assert extra == {}
        assert top == {}

    def test_with_reasoning_config(self):
        p = ProviderProfile(name="test")
        extra, top = p.build_api_kwargs_extras(reasoning_config={"enabled": True})
        assert extra == {}
        assert top == {}


class TestFetchModels:
    def test_no_base_url_returns_none(self):
        p = ProviderProfile(name="test")
        result = p.fetch_models()
        assert result is None

    @patch("urllib.request.urlopen")
    def test_successful_fetch(self, mock_urlopen):
        p = ProviderProfile(name="test", base_url="https://api.test.com/v1")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [{"id": "model-a"}, {"id": "model-b"}]
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = p.fetch_models(api_key="sk-test")
        assert result == ["model-a", "model-b"]

    @patch("urllib.request.urlopen")
    def test_flat_list_response(self, mock_urlopen):
        p = ProviderProfile(name="test", base_url="https://api.test.com/v1")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {"id": "model-a"}, {"id": "model-b"}
        ]).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = p.fetch_models(api_key="sk-test")
        assert result == ["model-a", "model-b"]

    @patch("urllib.request.urlopen")
    def test_fetch_failure_returns_none(self, mock_urlopen):
        p = ProviderProfile(name="test", base_url="https://api.test.com/v1")
        mock_urlopen.side_effect = Exception("timeout")
        result = p.fetch_models(api_key="sk-test", timeout=1.0)
        assert result is None

    @patch("urllib.request.urlopen")
    def test_uses_models_url_when_set(self, mock_urlopen):
        p = ProviderProfile(
            name="test",
            base_url="https://api.test.com/v1",
            models_url="https://custom.test.com/explicit/models",
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [{"id": "m1"}]}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        p.fetch_models()
        call_url = mock_urlopen.call_args[0][0].full_url
        assert "custom.test.com" in call_url
        assert "explicit/models" in call_url

    @patch("urllib.request.urlopen")
    def test_sends_bearer_auth(self, mock_urlopen):
        p = ProviderProfile(name="test", base_url="https://api.test.com/v1")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": []}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        p.fetch_models(api_key="sk-secret")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer sk-secret"

    def test_fallback_to_base_url_models(self):
        p = ProviderProfile(name="test", base_url="https://api.test.com/v1")
        url = p.models_url or p.base_url.rstrip("/") + "/models"
        assert url == "https://api.test.com/v1/models"


class TestDefaultHeaders:
    def test_default_empty(self):
        p = ProviderProfile(name="test")
        assert p.default_headers == {}

    def test_custom_headers(self):
        p = ProviderProfile(name="test", default_headers={"X-Custom": "val"})
        assert p.default_headers["X-Custom"] == "val"


class TestProfileUserAgent:
    def test_returns_string(self):
        ua = _profile_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 0

    def test_contains_nanocode(self):
        assert "nanocode" in _profile_user_agent()


class TestRegistry:
    def test_register_and_get(self):
        p = ProviderProfile(name="my-provider")
        register_provider(p)
        assert get_provider_profile("my-provider") is p

    def test_get_by_alias(self):
        p = ProviderProfile(name="canonical", aliases=("alias1", "alias2"))
        register_provider(p)
        assert get_provider_profile("alias1") is p
        assert get_provider_profile("alias2") is p

    def test_get_nonexistent_returns_none(self):
        result = get_provider_profile("no-such-provider")
        assert result is None

    def test_register_overwrites(self):
        p1 = ProviderProfile(name="same")
        p2 = ProviderProfile(name="same")
        register_provider(p1)
        register_provider(p2)
        assert get_provider_profile("same") is p2

    def test_list_providers(self):
        p1 = ProviderProfile(name="one")
        p2 = ProviderProfile(name="two")
        register_provider(p1)
        register_provider(p2)
        results = list_providers()
        names = {r.name for r in results}
        assert "one" in names
        assert "two" in names

    def test_list_providers_deduplicates(self):
        import nanocode.llm.profiles as _reg
        NAME = "_test_dedup_provider_"
        for k in list(_reg._REGISTRY.keys()):
            if k.startswith("_test_"):
                del _reg._REGISTRY[k]
        p = ProviderProfile(name=NAME)
        register_provider(p)
        register_provider(p)
        result = [x for x in list_providers() if x.name == NAME]
        assert len(result) == 1

    def test_alias_points_to_canonical(self):
        p = ProviderProfile(name="real", aliases=("nick",))
        register_provider(p)
        import nanocode.llm.profiles as reg
        assert reg._ALIASES["nick"] == "real"


class TestOMITTEMPERATURE:
    def test_is_sentinel(self):
        assert OMIT_TEMPERATURE is not None
        assert OMIT_TEMPERATURE is not True
        assert OMIT_TEMPERATURE is not False
        assert not isinstance(OMIT_TEMPERATURE, (int, float, str))

    def test_uniqueness(self):
        assert OMIT_TEMPERATURE != ""


class TestBuiltinProviderProfiles:
    def test_openai(self):
        p = get_provider_profile("openai")
        assert p is not None
        assert p.name == "openai"
        assert p.base_url == "https://api.openai.com/v1"
        assert "OPENAI_API_KEY" in p.env_vars

    def test_anthropic(self):
        p = get_provider_profile("anthropic")
        assert p is not None
        assert p.name == "anthropic"
        assert p.api_mode == "anthropic_messages"
        assert p.base_url == "https://api.anthropic.com"

    def test_ollama(self):
        p = get_provider_profile("ollama")
        assert p is not None
        assert p.name == "ollama"
        assert p.auth_type == "none"

    def test_opencode_zen(self):
        p = get_provider_profile("opencode")
        assert p is not None
        assert p.base_url == "https://opencode.ai/zen/v1"
        assert "OPENCODE_ZEN_API_KEY" in p.env_vars

    def test_opencode_go(self):
        p = get_provider_profile("opencode-go")
        assert p is not None
        assert p.base_url == "https://opencode.ai/zen/go/v1"

    def test_lm_studio(self):
        p = get_provider_profile("lm-studio")
        assert p is not None
        assert p.auth_type == "none"

    def test_aliases_resolve(self):
        assert get_provider_profile("claude").name == "anthropic"
        assert get_provider_profile("zen").name == "opencode"
        assert get_provider_profile("go").name == "opencode-go"


class TestAnthropicProfileFetchModels:
    @patch("urllib.request.urlopen")
    def test_fetch_with_x_api_key(self, mock_urlopen):
        p = get_provider_profile("anthropic")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [{"id": "claude-sonnet-4-5"}, {"id": "claude-haiku-4-5"}]
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = p.fetch_models(api_key="sk-ant-test")
        assert result == ["claude-sonnet-4-5", "claude-haiku-4-5"]
        req = mock_urlopen.call_args[0][0]
        headers = dict(req.headers)
        assert headers.get("x-api-key", headers.get("X-api-key")) == "sk-ant-test"
        version_header = headers.get("anthropic-version", headers.get("Anthropic-version"))
        assert version_header == "2023-06-01"

    @patch("urllib.request.urlopen")
    def test_no_api_key_returns_none(self, mock_urlopen):
        p = get_provider_profile("anthropic")
        result = p.fetch_models(api_key=None)
        assert result is None
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_fetch_failure_returns_none(self, mock_urlopen):
        p = get_provider_profile("anthropic")
        mock_urlopen.side_effect = Exception("timeout")
        result = p.fetch_models(api_key="sk-ant-test", timeout=1.0)
        assert result is None


class TestOpenCodeProfile:
    def test_opencode_go_reasoning_kimi_k2(self):
        p = get_provider_profile("opencode-go")
        extra, top = p.build_api_kwargs_extras(
            reasoning_config={"enabled": True, "effort": "high"},
            model="openai/kimi-k2-20260401"
        )
        assert "thinking" in extra
        assert extra["thinking"]["type"] == "enabled"
        assert top.get("reasoning_effort") == "high"

    def test_opencode_go_reasoning_kimi_k2_disabled(self):
        p = get_provider_profile("opencode-go")
        extra, top = p.build_api_kwargs_extras(
            reasoning_config={"enabled": False},
            model="openai/kimi-k2-20260401"
        )
        assert extra["thinking"]["type"] == "disabled"

    def test_opencode_go_reasoning_deepseek(self):
        p = get_provider_profile("opencode-go")
        extra, top = p.build_api_kwargs_extras(
            reasoning_config={"enabled": True, "effort": "xhigh"},
            model="deepseek-v2-chat"
        )
        assert "thinking" in extra
        assert extra["thinking"]["type"] == "enabled"
        assert top.get("reasoning_effort") == "max"

    def test_opencode_go_no_reasoning_config(self):
        p = get_provider_profile("opencode-go")
        extra, top = p.build_api_kwargs_extras(
            model="gpt-4o"
        )
        assert extra == {}
        assert top == {}


class TestEdgeCases:
    def test_default_headers_mutable(self):
        p = ProviderProfile(name="test")
        assert len(p.default_headers) == 0
        p.default_headers["X-Custom"] = "val"
        assert p.default_headers["X-Custom"] == "val"

    def test_list_providers_after_clear(self):
        import nanocode.llm.profiles as reg
        reg._REGISTRY.clear()
        reg._ALIASES.clear()
        reg._discovered = True
        assert list_providers() == []

    def test_discovery_happens_once(self):
        import nanocode.llm.profiles as reg
        reg._discovered = False
        with patch.object(reg, "_discover_providers", wraps=reg._discover_providers) as mock_discover:
            list_providers()
            list_providers()
            assert mock_discover.call_count == 1
