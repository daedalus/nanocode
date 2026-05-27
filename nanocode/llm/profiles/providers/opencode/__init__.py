from __future__ import annotations

from typing import Any

from nanocode.llm.profiles import register_provider
from nanocode.llm.profiles.base import ProviderProfile


class OpenCodeGoProfile(ProviderProfile):
    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, model: str | None = None, **context
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        m = (model or "").strip().rsplit("/", 1)[-1].lower()

        if m.startswith("kimi-k2"):
            if not isinstance(reasoning_config, dict):
                return extra_body, top_level
            enabled = reasoning_config.get("enabled") is not False
            extra_body["thinking"] = {"type": "enabled" if enabled else "disabled"}
            if not enabled:
                return extra_body, top_level
            effort = (reasoning_config.get("effort") or "").strip().lower()
            if effort in {"xhigh", "max"}:
                top_level["reasoning_effort"] = "high"
            elif effort in {"low", "medium", "high"}:
                top_level["reasoning_effort"] = effort
            return extra_body, top_level

        if m in ("deepseek-reasoner",) or (m.startswith("deepseek-v") and not m.startswith("deepseek-v3")):
            enabled = True
            if isinstance(reasoning_config, dict) and reasoning_config.get("enabled") is False:
                enabled = False
            extra_body["thinking"] = {"type": "enabled" if enabled else "disabled"}
            if not enabled:
                return extra_body, top_level
            if isinstance(reasoning_config, dict):
                effort = (reasoning_config.get("effort") or "").strip().lower()
                if effort in {"xhigh", "max"}:
                    top_level["reasoning_effort"] = "max"
                elif effort in {"low", "medium", "high"}:
                    top_level["reasoning_effort"] = effort
            return extra_body, top_level

        return extra_body, top_level


opencode_zen = ProviderProfile(
    name="opencode",
    aliases=("opencode-zen", "zen"),
    api_mode="chat_completions",
    env_vars=("OPENCODE_ZEN_API_KEY",),
    base_url="https://opencode.ai/zen/v1",
    auth_type="api_key",
    default_aux_model="gemini-3-flash",
)

opencode_go = OpenCodeGoProfile(
    name="opencode-go",
    aliases=("go",),
    api_mode="chat_completions",
    env_vars=("OPENCODE_GO_API_KEY",),
    base_url="https://opencode.ai/zen/go/v1",
    auth_type="api_key",
    default_aux_model="glm-5",
)

register_provider(opencode_zen)
register_provider(opencode_go)
