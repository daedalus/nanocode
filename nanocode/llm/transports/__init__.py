"""Transport layer types and registry for provider response normalization.

Usage:
    from nanocode.llm.transports import get_transport
    transport = get_transport("chat_completions")
    kwargs = transport.build_kwargs(model, messages, tools)
"""

from nanocode.llm.transports.types import (
    NormalizedResponse,
    ToolCall,
    Usage,
    build_tool_call,
    map_finish_reason,
)

_REGISTRY: dict[str, type] = {}
_discovered: bool = False


def register_transport(api_mode: str, transport_cls: type) -> None:
    """Register a transport class for an api_mode string."""
    _REGISTRY[api_mode] = transport_cls


def get_transport(api_mode: str):
    """Get a transport instance for the given api_mode.

    Returns None if no transport is registered for this api_mode.
    This allows gradual migration — call sites can check for None
    and fall back to the legacy code path.
    """
    global _discovered
    if not _discovered:
        _discover_transports()
    cls = _REGISTRY.get(api_mode)
    if cls is None:
        _discover_transports()
        cls = _REGISTRY.get(api_mode)
    if cls is None:
        return None
    return cls()


def _discover_transports() -> None:
    """Import all transport modules to trigger auto-registration."""
    global _discovered
    _discovered = True
    try:
        import nanocode.llm.transports.chat_completions  # noqa: F401
    except ImportError:
        pass
    try:
        import nanocode.llm.transports.anthropic  # noqa: F401
    except ImportError:
        pass
