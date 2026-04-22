"""Configuration management for the autonomous agent."""

import os
from pathlib import Path
from typing import Any

import yaml


def _get_default_storage_dir() -> Path:
    """Get default storage directory following XDG spec."""
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "nanocode" / "storage"


class Config:
    """Configuration manager for the agent."""

    def __init__(self, config_path: str | None = None):
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
            self.setdefault("llm", {}).setdefault("providers", {}).setdefault(
                "openai", {}
            )["api_key"] = api_key
        if base_url := os.getenv("OPENAI_BASE_URL"):
            self.setdefault("llm", {}).setdefault("providers", {}).setdefault(
                "openai", {}
            )["base_url"] = base_url

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

    @property
    def agents(self) -> dict:
        """Get agents configuration."""
        return self.get("agents", {})

    @property
    def default_agent(self) -> str:
        """Get default agent name."""
        return self.get("agents.default", "build")

    @property
    def permission(self) -> dict:
        """Get permission configuration."""
        return self.get("permission", {})

    @property
    def file_watcher(self) -> dict:
        """Get file watcher configuration."""
        return self.get("file_watcher", {})

    @property
    def admin(self) -> dict:
        """Get admin console configuration."""
        return self.get("admin", {})

    @property
    def github(self) -> dict:
        """Get GitHub configuration."""
        return self.get("github", {})

    @property
    def proxy(self) -> str | None:
        """Get proxy configuration."""
        return self.get("proxy")

    @property
    def cache_enabled(self) -> bool:
        """Check if prompt caching is enabled."""
        return self.get("cache.enabled", False)

    @property
    def cache_dir(self) -> Path:
        """Get cache directory."""
        cache_path = self.get("cache.dir")
        if cache_path:
            return Path(cache_path)
        return _get_default_storage_dir()

    @property
    def base_dir(self) -> str:
        """Get base directory for the agent."""
        return self.get("base_dir", os.getcwd())


_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
