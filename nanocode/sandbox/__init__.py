"""Sandbox module - lifecycle management for agent sandboxes."""

from typing import Any

from nanocode.sandbox.base import Sandbox, SandboxProvider
from nanocode.sandbox.local import LocalSandboxProvider

# Provider registry
_PROVIDERS = {
    "local": LocalSandboxProvider,
}

# Import Docker provider if available (optional)
try:
    from nanocode.sandbox.docker import DockerSandboxProvider
    _PROVIDERS["docker"] = DockerSandboxProvider
except ImportError:
    pass  # Docker provider not available

# Import Blaxel provider if available (optional)
try:
    from nanocode.sandbox.blaxel import BlaxelSandboxProvider
    _PROVIDERS["blaxel"] = BlaxelSandboxProvider
except ImportError:
    pass  # Blaxel provider not available


def get_sandbox_provider(provider_type: str = "local", config: Any = None) -> SandboxProvider:
    """Get a sandbox provider by type.

    Args:
        provider_type: 'local', 'docker', 'blaxel' (default: 'local')
        config: Optional config object for the provider

    Returns:
        SandboxProvider instance
    """
    provider_class = _PROVIDERS.get(provider_type)
    if not provider_class:
        raise ValueError(f"Unknown sandbox provider: {provider_type}")
    return provider_class(config)


def register_sandbox_provider(name: str, provider_class: type[SandboxProvider]):
    """Register a custom sandbox provider."""
    _PROVIDERS[name] = provider_class


__all__ = [
    "Sandbox",
    "SandboxProvider",
    "LocalSandboxProvider",
    "DockerSandboxProvider",
    "get_sandbox_provider",
    "register_sandbox_provider",
]
