"""Configuration management for the autonomous agent."""

import os
import json
from pathlib import Path
from typing import Any, Optional
import yaml


class Config:
    """Configuration manager for the agent."""

    def __init__(self, config_path: Optional[str] = None):
        self._config: dict = {}
        self._config_path = config_path or os.getenv("AGENT_CONFIG", "config.yaml")
        self.load()

    def load(self):
        """Load configuration from file and environment variables."""
        if Path(self._config_path).exists():
            with open(self._config_path) as f:
                self._config = yaml.safe_load(f) or {}
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """Apply environment variable overrides."""
        if api_key := os.getenv("OPENAI_API_KEY"):
            self.setdefault("llm", {}).setdefault("providers", {}).setdefault("openai", {})["api_key"] = api_key
        if base_url := os.getenv("OPENAI_BASE_URL"):
            self.setdefault("llm", {}).setdefault("providers", {}).setdefault("openai", {})["base_url"] = base_url

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def set(self, key: str, value: Any):
        """Set a configuration value using dot notation."""
        keys = key.split(".")
        target = self._config
        for k in keys[:-1]:
            target = target.setdefault(k, {})
        target[keys[-1]] = value

    @property
    def providers(self) -> dict:
        """Get LLM providers configuration."""
        return self.get("llm.providers", {})

    @property
    def default_provider(self) -> str:
        """Get default LLM provider."""
        return self.get("llm.default_provider", "openai")

    @property
    def mcp_servers(self) -> dict:
        """Get MCP servers configuration."""
        return self.get("mcp.servers", {})

    @property
    def tools(self) -> dict:
        """Get tools configuration."""
        return self.get("tools", {})

    @property
    def planning(self) -> dict:
        """Get planning configuration."""
        return self.get("planning", {})


_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
