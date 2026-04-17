"""Autonomous Agent - A fully autonomous AI agent with advanced tool use."""

__version__ = "0.1.0.1"
__all__ = [
    "config",
    "core",
    "agents",
    "llm",
    "tools",
    "mcp",
    "lsp",
    "planning",
    "multimodal",
    "acp",
    "server",
    "mdns",
    "retry",
    "skills",
    "snapshot",
    "cli",
    "context",
    "state",
    "bus",
    "effect",
    "share",
]

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .core import AutonomousAgent
