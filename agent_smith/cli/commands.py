"""Command definitions for CLI and GUI."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Command:
    names: tuple[str, ...]
    description: str
    takes_args: bool = False
    arg_name: Optional[str] = None


COMMANDS = [
    Command(("help",), "Show this help message", takes_args=False),
    Command(("exit", "quit", "q"), "Exit the agent"),
    Command(("clear",), "Clear the terminal"),
    Command(("history",), "Show command history"),
    Command(("plan",), "Create and execute a plan", takes_args=True, arg_name="task"),
    Command(("provider",), "Select AI provider and model"),
    Command(("checkpoint",), "List saved checkpoints"),
    Command(("resume",), "Resume from a checkpoint", takes_args=True, arg_name="id"),
    Command(("tools",), "List available tools"),
    Command(("skills",), "List available skills"),
    Command(("snapshot",), "Create a new snapshot"),
    Command(("snapshots",), "List available snapshots"),
    Command(
        ("revert",), "Revert to a snapshot (hash or 'latest')", takes_args=True, arg_name="hash"
    ),
    Command(("trace",), "Show last error trace"),
    Command(("debug",), "Toggle HTTP debug logging"),
    Command(("compact",), "Compact context (summarize old messages)"),
    Command(("show_thinking",), "Toggle thinking display"),
]


def get_command_help() -> str:
    """Generate help text for all commands."""
    lines = [
        "Available commands:",
    ]
    for cmd in COMMANDS:
        names = [n if n.startswith("/") else "/" + n for n in cmd.names]
        names_str = "/".join(names)
        if cmd.takes_args:
            lines.append(f"  {names_str} <{cmd.arg_name}> - {cmd.description}")
        else:
            lines.append(f"  {names_str} - {cmd.description}")
    return "\n".join(lines)


def find_command(name: str) -> Optional[Command]:
    """Find a command by name."""
    name_lower = name.lower().lstrip("/")
    for cmd in COMMANDS:
        if name_lower in cmd.names:
            return cmd
    return None


def get_command_names() -> list[str]:
    """Get all command names (with / prefix)."""
    names = []
    for cmd in COMMANDS:
        for name in cmd.names:
            if name.startswith("/"):
                names.append(name)
            else:
                names.append("/" + name)
    return names
