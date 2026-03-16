"""Doom loop detection - detects repeated tool calls that may indicate infinite loops."""

from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
import json


@dataclass
class ToolCall:
    """Represents a tool call."""

    tool_name: str
    arguments: dict
    call_id: str


@dataclass
class DoomLoopDetection:
    """Tracks tool calls to detect doom loops."""

    threshold: int = 3
    _recent_calls: dict[str, list[ToolCall]] = field(default_factory=lambda: defaultdict(list))

    def record_call(self, tool_name: str, arguments: dict, call_id: str = None) -> bool:
        """
        Record a tool call and check if it triggers doom loop detection.
        Returns True if doom loop is detected.
        """
        call = ToolCall(tool_name=tool_name, arguments=arguments, call_id=call_id or "")

        tool_calls = self._recent_calls[tool_name]
        tool_calls.append(call)

        if len(tool_calls) > self.threshold:
            tool_calls.pop(0)

        if len(tool_calls) >= self.threshold:
            return self._is_doom_loop(tool_calls)

        return False

    def _is_doom_loop(self, calls: list[ToolCall]) -> bool:
        """Check if the recent calls constitute a doom loop."""
        if len(calls) < self.threshold:
            return False

        recent = calls[-self.threshold :]

        if not all(c.tool_name == recent[0].tool_name for c in recent):
            return False

        first_args = recent[0].arguments
        return all(
            json.dumps(c.arguments, sort_keys=True) == json.dumps(first_args, sort_keys=True)
            for c in recent
        )

    def get_loop_info(self) -> Optional[dict]:
        """Get information about the detected doom loop."""
        for tool_name, calls in self._recent_calls.items():
            if len(calls) >= self.threshold and self._is_doom_loop(calls):
                return {
                    "tool": tool_name,
                    "arguments": calls[-1].arguments,
                    "count": len(calls),
                }
        return None

    def clear(self, tool_name: str = None):
        """Clear recent calls for a specific tool or all tools."""
        if tool_name:
            self._recent_calls[tool_name] = []
        else:
            self._recent_calls.clear()

    def should_prompt(self, tool_name: str) -> bool:
        """Check if we should prompt for permission for this tool (doom loop detected)."""
        calls = self._recent_calls.get(tool_name, [])
        if len(calls) >= self.threshold:
            return self._is_doom_loop(calls)
        return False


class DoomLoopHandler:
    """Handles doom loop detection and permission requests."""

    def __init__(self, threshold: int = 3):
        self.detection = DoomLoopDetection(threshold=threshold)
        self.enabled = True

    def check_tool_call(self, tool_name: str, arguments: dict) -> bool:
        """
        Check if a tool call triggers doom loop detection.
        Returns True if doom loop is detected.
        """
        if not self.enabled:
            return False
        return self.detection.record_call(tool_name, arguments)

    def get_loop_warning(self) -> Optional[str]:
        """Generate a warning message about the doom loop."""
        info = self.detection.get_loop_info()
        if info:
            return (
                f"Warning: The tool '{info['tool']}' has been called "
                f"{info['count']} times with the same arguments. "
                f"This may indicate a doom loop. "
                f"Arguments: {json.dumps(info['arguments'], sort_keys=True)}"
            )
        return None

    def should_ask_permission(self, tool_name: str) -> bool:
        """Check if we should ask for permission due to doom loop."""
        return self.detection.should_prompt(tool_name)

    def reset(self, tool_name: str = None):
        """Reset the doom loop detection."""
        self.detection.clear(tool_name)


def create_doom_loop_handler(threshold: int = 3) -> DoomLoopHandler:
    """Create a doom loop handler with the specified threshold."""
    return DoomLoopHandler(threshold=threshold)
