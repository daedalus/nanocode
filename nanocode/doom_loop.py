"""Doom loop detection - detects repeated tool calls that may indicate infinite loops."""

import json
from collections import defaultdict
from dataclasses import dataclass, field

from nanocode.tools import ToolCall


@dataclass
class DoomLoopDetection:
    """Tracks tool calls to detect doom loops."""

    threshold: int = 3
    _recent_calls: dict[str, list[ToolCall]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _all_recent_calls: list[ToolCall] = field(default_factory=list)
    _exploration_warning_shown: bool = field(default=False)

    def record_call(self, tool_name: str, arguments: dict, call_id: str = None) -> bool:
        """
        Record a tool call and check if it triggers doom loop detection.
        Returns True if doom loop is detected.
        """
        call = ToolCall(name=tool_name, arguments=arguments, id=call_id or "")

        tool_calls = self._recent_calls[tool_name]
        tool_calls.append(call)
        self._all_recent_calls.append(call)

        if len(tool_calls) > self.threshold:
            tool_calls.pop(0)
        if len(self._all_recent_calls) > 6:
            self._all_recent_calls.pop(0)

        if len(tool_calls) >= self.threshold:
            return self._is_doom_loop(tool_calls)

        if len(self._all_recent_calls) >= 3:
            return self._is_exploration_loop()

        return False

    def _is_exploration_loop(self) -> bool:
        """Detect repetitive exploration pattern without progress."""
        if len(self._all_recent_calls) < 3:
            return False

        recent = self._all_recent_calls[-4:]

        if len(recent) < 3:
            return False

        exploration_tools = {"glob", "bash"}

        recent_tools = [c.name for c in recent]

        unique_tools = set(recent_tools)
        if not unique_tools.issubset(exploration_tools):
            # Reset warning flag when non-exploration tools are used
            self._exploration_warning_shown = False
            return False

        if len(unique_tools) <= 2:
            return True

        return False

    def _should_show_exploration_warning(self) -> bool:
        """Check if exploration warning should be shown (only once per detection)."""
        if self._is_exploration_loop() and not self._exploration_warning_shown:
            self._exploration_warning_shown = True
            return True
        return False

    def _is_doom_loop(self, calls: list[ToolCall]) -> bool:
        """Check if the recent calls constitute a doom loop."""
        if len(calls) < self.threshold:
            return False

        recent = calls[-self.threshold :]

        if not all(c.name == recent[0].name for c in recent):
            return False

        first_args = recent[0].arguments

        # Ignore empty or default arguments for doom loop detection
        if not first_args or all(
            v is None or v == "" or v == "." or v == "*" for v in first_args.values()
        ):
            return False

        # Check if arguments are exactly the same
        args_json = json.dumps(first_args, sort_keys=True)
        identical_count = sum(
            1 for c in recent if json.dumps(c.arguments, sort_keys=True) == args_json
        )

        # Only detect doom loop if ALL recent calls have identical args
        # If model is making progress (different args), don't trigger
        return identical_count == len(recent)

    def get_loop_info(self) -> dict | None:
        """Get information about the detected doom loop."""
        for tool_name, calls in self._recent_calls.items():
            if len(calls) >= self.threshold and self._is_doom_loop(calls):
                return {
                    "tool": tool_name,
                    "arguments": calls[-1].arguments,
                    "count": len(calls),
                    "type": "repeat",
                }

        if self._is_exploration_loop():
            return {
                "tool": "exploration",
                "arguments": {"pattern": "glob/bash repetition without progress"},
                "count": len(self._all_recent_calls),
                "type": "exploration",
                "show_warning": not self._exploration_warning_shown,
            }

        return None

    def clear(self, tool_name: str = None):
        """Clear recent calls for a specific tool or all tools."""
        if tool_name:
            self._recent_calls[tool_name] = []
        else:
            self._recent_calls.clear()
            self._all_recent_calls.clear()
            self._exploration_warning_shown = False

    def should_prompt(self, tool_name: str) -> bool:
        """Check if we should prompt for permission for this tool (doom loop detected)."""
        calls = self._recent_calls.get(tool_name, [])
        if len(calls) >= self.threshold:
            return self._is_doom_loop(calls)
        if self._is_exploration_loop():
            return True
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

    def get_loop_warning(self) -> str | None:
        """Generate a warning message about the doom loop."""
        info = self.detection.get_loop_info()
        if info:
            loop_type = info.get("type", "repeat")
            if loop_type == "exploration":
                return (
                    "⚠️ Permission required: You've called exploration tools repeatedly without making progress.\n"
                    "Please use different tools or provide a different approach."
                )
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
