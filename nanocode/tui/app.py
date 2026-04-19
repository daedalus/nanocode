"""NanoCode TUI - Terminal UI matching opencode style."""

import asyncio
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Static, Button, Label, Input, TextArea, RichLog
from textual.binding import Binding
from textual import work
from rich.theme import Theme
from rich.console import Console
from rich.text import Text
from rich.console import Console


# Gruvbox Dark Theme Colors
GRUVBOX = {
    "bg": "#282828",
    "bg_soft": "#3c3836",
    "fg": "#ebdbb2",
    "red": "#cc241d",
    "green": "#98971f",
    "yellow": "#d79921",
    "blue": "#458588",
    "purple": "#b16286",
    "aqua": "#689d6a",
    "gray": "#928374",
    "orange": "#d65d0e",
}

class Style:
    """ANSI color codes matching Gruvbox theme (256-color)."""
    TEXT_HIGHLIGHT = "\x1b[38;5;73m"
    TEXT_HIGHLIGHT_BOLD = "\x1b[38;5;73m\x1b[1m"
    TEXT_DIM = "\x1b[38;5;245m"
    TEXT_DIM_BOLD = "\x1b[38;5;245m\x1b[1m"
    TEXT_NORMAL = "\x1b[0m"
    TEXT_NORMAL_BOLD = "\x1b[1m"
    TEXT_WARNING = "\x1b[38;5;220m"
    TEXT_WARNING_BOLD = "\x1b[38;5;220m\x1b[1m"
    TEXT_DANGER = "\x1b[38;5;196m"
    TEXT_DANGER_BOLD = "\x1b[38;5;196m\x1b[1m"
    TEXT_SUCCESS = "\x1b[38;5;154m"
    TEXT_SUCCESS_BOLD = "\x1b[38;5;154m\x1b[1m"
    TEXT_INFO = "\x1b[38;5;176m"
    TEXT_INFO_BOLD = "\x1b[38;5;176m\x1b[1m"
    
    USER_MESSAGE = "\x1b[38;5;154m"
    USER_MESSAGE_BOLD = "\x1b[38;5;154m\x1b[1m"
    ASSISTANT_MESSAGE = "\x1b[38;5;176m"
    ASSISTANT_MESSAGE_BOLD = "\x1b[38;5;176m\x1b[1m"
    TOOL_MESSAGE = "\x1b[38;5;73m"
    TOOL_MESSAGE_BOLD = "\x1b[38;5;73m\x1b[1m"
    SYSTEM_MESSAGE = "\x1b[38;5;245m"
    SYSTEM_MESSAGE_BOLD = "\x1b[38;5;245m\x1b[1m"
    THINKING = "\x1b[38;5;245m"


class PermissionScreen(ModalScreen):
    """Modal screen for permission requests."""
    
    CSS = """
    PermissionScreen {
        align: center middle;
    }
    
    PermissionScreen > #dialog {
        width: 50;
        height: auto;
        border: solid #458588;
        background: #282828;
        padding: 1 2;
    }
    
    #dialog-title {
        text-align: center;
        text-style: bold;
        color: #d79921;
        margin-bottom: 1;
    }
    
    #dialog-info {
        color: #ebdbb2;
        margin-bottom: 1;
    }
    
    #dialog-args {
        color: #928374;
        margin-bottom: 1;
    }
    
    #dialog-buttons {
        align: center middle;
        margin-top: 1;
    }
    
    #dialog-buttons > Button {
        margin: 0 1;
        min-width: 8;
    }
    """
    
    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self._result = None
    
    def compose(self) -> ComposeResult:
        args_str = f"Args: {str(self.request.arguments)[:40]}" if self.request.arguments else ""
        yield Vertical(
            Static("⚠️ Permission Request", id="dialog-title"),
            Static(f"Tool: {self.request.tool_name}", id="dialog-info"),
            Static(args_str, id="dialog-args"),
            Horizontal(
                Button("Yes (y)", id="btn-yes", variant="primary"),
                Button("No (n)", id="btn-no", variant="default"),
                Button("Always (a)", id="btn-always", variant="success"),
                id="dialog-buttons",
            ),
            id="dialog",
        )
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        from nanocode.agents.permission import PermissionReply, PermissionReplyType
        
        if event.button.id == "btn-yes":
            self._result = PermissionReply(request_id=self.request.id, reply=PermissionReplyType.ONCE)
        elif event.button.id == "btn-no":
            self._result = PermissionReply(request_id=self.request.id, reply=PermissionReplyType.REJECT, message="Permission denied by user")
        elif event.button.id == "btn-always":
            self._result = PermissionReply(request_id=self.request.id, reply=PermissionReplyType.ALWAYS)
        
        self.dismiss(self._result)


class OutputArea(RichLog):
    """Scrollable output area using RichLog widget for color support."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lines: list[str] = []
    
    def add_line(self, text: str, style: str = ""):
        """Add a line to output with Rich color."""
        from rich.text import Text
        from rich.style import Style as RichStyle
        
        # Map style to Rich style name (use lowercase for Rich)
        style_map = {
            "user": "green",
            "assistant": "magenta",
            "tool": "cyan",
            "dim": "dim",
            "success": "green",
            "warning": "yellow",
            "danger": "red",
            "thinking": "dim",
            "info": "blue",
        }
        
        rich_style_name = style_map.get(style, "")
        if rich_style_name:
            rich_text = Text(text, style=rich_style_name)
            self.write(rich_text)
        else:
            self.write(text)
        
        self._lines.append(text)
    
    def add_empty_line(self):
        """Add an empty line."""
        self.write("")
        self._lines.append("")
    
    def clear_lines(self):
        """Clear all lines."""
        self._lines.clear()
        self.clear()


class ToolState(Enum):
    """Tool execution state."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ToolCall:
    """Represents a tool call."""
    tool: str
    title: str
    description: str = ""
    state: ToolState = ToolState.PENDING
    output: str = ""
    icon: str = "⚙"


class NanoCodeTUI(App):
    """Main TUI application for NanoCode matching Gruvbox dark theme."""
    
    CSS = """
/* Gruvbox Dark Theme */
Screen {
    background: #282828;
}
Header {
    background: #3c3836;
    color: #ebdbb2;
}
Footer {
    background: #3c3836;
    color: #928374;
}
#main-container {
    height: 100%;
}
#output-area {
    height: 1fr;
    border: solid #458588;
    background: #282828;
    margin: 1;
    padding: 0 1;
}
#input-container {
    height: auto;
    padding: 0 1 1 1;
    background: #282828;
}
#input-prompt {
    width: 2;
    text-align: right;
    color: #ebdbb2;
}
#input {
    height: auto;
    border: none;
    width: 2fr;
    background: #282828;
    color: #ebdbb2;
}
.tool-title {
    color: #ebdbb2;
}
.tool-description {
    color: #928374;
}
.thinking {
    color: #928374;
    text-style: italic;
}
.error {
    color: #cc241d;
}
/* Role-based colors for conversation */
.user-message {
    color: #98971f;
}
.assistant-message {
    color: #b16286;
}
.tool-message {
    color: #458588;
}
.tool-message {
    color: #458588;
}
.thinking {
    color: #928374;
}
.success {
    color: #98971f;
}
.success {
    color: #98971f;
}
.tool-output {
    color: #928374;
    padding-left: 2;
}
"""
    
    BINDINGS = [
        Binding("enter", "submit", "Send"),
        Binding("ctrl+l", "clear_output", "Clear"),
        Binding("escape", "quit", "Quit", show=True),
        Binding("ctrl+c", "interrupt", "Interrupt", show=False),
    ]
    
    def __init__(self, agent=None, show_thinking: bool = True):
        super().__init__()
        self.agent = agent
        self.show_thinking = show_thinking
        self._processing = False
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-container"):
            with OutputArea(id="output-area", auto_scroll=True):
                pass
            with Horizontal(id="input-container"):
                yield Label("➜", id="input-prompt")
                yield Input(placeholder="Enter your task...", id="input")
        yield Static("", id="status-bar")
        yield Footer()
    
    def on_mount(self) -> None:
        """Initialize on mount."""
        self.query_one("#input", Input).focus()
        self._show_welcome()
        
        if self.agent:
            self._setup_permission_callback()
    
    def _show_welcome(self):
        """Show welcome message matching opencode style."""
        self._print_logo()
        self._print_empty()
        self._print_line("Type your task or 'help' for commands", Style.TEXT_DIM)
        self._print_empty()
    
    def _print_logo(self):
        """Print ASCII logo."""
        logo = [
            "█▀▀█ █▀▀█ █▀▀█ █▀▀▄ █▀▀▀ █▀▀█ █▀▀█ █▀▀█",
            "█  █ █  █ █▀▀▀ █  █ █    █  █ █  █ █▀▀▀",
            "▀▀▀▀ █▀▀▀ ▀▀▀▀ ▀  ▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀",
        ]
        for line in logo:
            self._print_line(f"  {line}", Style.TEXT_NORMAL)
    
    def _print_line(self, text: str, style: str = ""):
        """Print a line with optional style."""
        output = self.query_one("#output-area")
        
        # Convert ANSI style to simple Rich style name
        style_map = {
            Style.USER_MESSAGE: "user",
            Style.USER_MESSAGE_BOLD: "user",
            Style.ASSISTANT_MESSAGE: "assistant",
            Style.ASSISTANT_MESSAGE_BOLD: "assistant",
            Style.TOOL_MESSAGE: "tool",
            Style.TOOL_MESSAGE_BOLD: "tool",
            Style.TEXT_DIM: "dim",
            Style.TEXT_DIM_BOLD: "dim",
            Style.TEXT_NORMAL: "",
            Style.TEXT_NORMAL_BOLD: "",
            Style.TEXT_WARNING: "warning",
            Style.TEXT_WARNING_BOLD: "warning",
            Style.TEXT_DANGER: "danger",
            Style.TEXT_DANGER_BOLD: "danger",
            Style.TEXT_SUCCESS: "success",
            Style.TEXT_SUCCESS_BOLD: "success",
            Style.TEXT_INFO: "info",
            Style.TEXT_INFO_BOLD: "info",
            Style.THINKING: "thinking",
        }
        
        rich_style = style_map.get(style, "")
        output.add_line(text, rich_style)
    
    def _print_empty(self):
        """Print an empty line."""
        output = self.query_one("#output-area")
        output.add_empty_line()
    
    def _print_info(self, text: str, bold: bool = False):
        """Print info text."""
        style = Style.TEXT_INFO_BOLD if bold else Style.TEXT_INFO
        self._print_line(text, style)
    
    def _print_warning(self, text: str, bold: bool = False):
        """Print warning text."""
        style = Style.TEXT_WARNING_BOLD if bold else Style.TEXT_WARNING
        self._print_line(text, style)
    
    def _print_error(self, text: str, bold: bool = False):
        """Print error text."""
        style = Style.TEXT_DANGER_BOLD if bold else Style.TEXT_DANGER
        self._print_line(text, style)
    
    def _print_success(self, text: str, bold: bool = False):
        """Print success text."""
        style = Style.TEXT_SUCCESS_BOLD if bold else Style.TEXT_SUCCESS
        self._print_line(text, style)
    
    def _print_dim(self, text: str):
        """Print dimmed text."""
        self._print_line(text, Style.TEXT_DIM)
    
    def _setup_permission_callback(self):
        """Set up permission callback for the agent."""
        # Disable permission callback in TUI for now - auto-allow all
        # This can be re-enabled once the screen dismiss flow works properly
        pass
    
    async def _show_permission_dialog(self, request) -> "PermissionReply":
        """Show permission request dialog as a modal screen and wait for result."""
        screen = PermissionScreen(request)
        # push_screen returns the value passed to dismiss() when screen is dismissed
        result = await self.push_screen(screen)
        return result
    
    def _print_tool(self, tool_call: ToolCall):
        """Print a tool call matching opencode style."""
        icon = tool_call.icon
        title = tool_call.title
        desc = tool_call.description
        
        line = f"{icon} {title}"
        if desc:
            line = f"{line} {Style.TEXT_DIM}{desc}{Style.TEXT_NORMAL}"
        
        self._print_line(line, Style.TEXT_NORMAL)
        
        if tool_call.state == ToolState.COMPLETED and tool_call.output:
            self._print_empty()
            for output_line in tool_call.output.strip().split("\n"):
                self._print_line(f"  {output_line}", Style.TEXT_DIM)
            self._print_empty()
        
        if tool_call.state == ToolState.ERROR:
            self._print_error(tool_call.output if tool_call.output else "Tool failed")
    
    def _format_tool_call(self, tool_name: str, arguments: dict) -> ToolCall:
        """Format a tool call based on its type, matching opencode's tool handlers."""
        
        def normalize_path(path: str) -> str:
            if not path:
                return ""
            try:
                return os.path.relpath(path, os.getcwd()) or "."
            except ValueError:
                return path
        
        if tool_name == "glob":
            root = arguments.get("path", "")
            pattern = arguments.get("pattern", "")
            title = f'Glob "{pattern}"'
            suffix = f"in {normalize_path(root)}" if root else ""
            return ToolCall(tool=tool_name, title=title, description=suffix, icon="✱")
        
        if tool_name == "grep":
            root = arguments.get("path", "")
            pattern = arguments.get("pattern", "")
            title = f'Grep "{pattern}"'
            suffix = f"in {normalize_path(root)}" if root else ""
            return ToolCall(tool=tool_name, title=title, description=suffix, icon="✱")
        
        if tool_name == "read":
            filepath = normalize_path(arguments.get("filePath", ""))
            extra_args = {k: v for k, v in arguments.items() 
                         if k != "filePath" and isinstance(v, (str, int, bool))}
            desc = f"[{', '.join(f'{k}={v}' for k, v in extra_args.items())}]" if extra_args else ""
            return ToolCall(tool=tool_name, title=f"Read {filepath}", description=desc, icon="→")
        
        if tool_name == "write":
            filepath = normalize_path(arguments.get("filePath", ""))
            return ToolCall(tool=tool_name, title=f"Write {filepath}", icon="←")
        
        if tool_name == "edit":
            filepath = normalize_path(arguments.get("filePath", ""))
            return ToolCall(tool=tool_name, title=f"Edit {filepath}", icon="←")
        
        if tool_name == "webfetch":
            url = arguments.get("url", "")
            return ToolCall(tool=tool_name, title=f"WebFetch {url}", icon="%")
        
        if tool_name == "codesearch":
            query = arguments.get("query", "")
            return ToolCall(tool=tool_name, title=f'Exa Code Search "{query}"', icon="◇")
        
        if tool_name == "websearch":
            query = arguments.get("query", "")
            return ToolCall(tool=tool_name, title=f'Exa Web Search "{query}"', icon="◈")
        
        if tool_name == "task":
            desc = arguments.get("description", "")
            subagent = arguments.get("subagent_type", "")
            agent_name = subagent if subagent else "unknown"
            icon = "•"
            name = desc if desc else f"{agent_name} Task"
            return ToolCall(tool=tool_name, title=name, description=f"{agent_name} Agent", icon=icon)
        
        if tool_name == "skill":
            name = arguments.get("name", "")
            return ToolCall(tool=tool_name, title=f'Skill "{name}"', icon="→")
        
        if tool_name == "bash":
            command = arguments.get("command", "")
            return ToolCall(tool=tool_name, title=command, icon="$")
        
        if tool_name == "todowrite":
            return ToolCall(tool=tool_name, title="Todos", icon="#")
        
        # Fallback for unknown tools
        title = str(arguments) if arguments else "Unknown"
        return ToolCall(tool=tool_name, title=f"{tool_name} {title}", icon="⚙")
    
    def _get_tool_icon(self, tool_name: str) -> str:
        """Get icon for a tool name."""
        icons = {
            "glob": "✱", "grep": "✱", "read": "→", "write": "←",
            "edit": "←", "webfetch": "%", "codesearch": "◇",
            "websearch": "◈", "task": "•", "skill": "→",
            "bash": "$", "todowrite": "#", "mcp-parigp": "∑",
            "mcp-number-theory": "∫", "mcp-numpy": "∎",
            "mcp-sympy": "∂", "mcp-qiskit": "⚛",
        }
        return icons.get(tool_name, "⚙")
    
    def action_submit(self):
        """Handle send action."""
        input_widget = self.query_one("#input", Input)
        text = input_widget.value.strip()
        if text:
            input_widget.value = ""
            self._process_input(text)
    
    def action_interrupt(self):
        """Handle interrupt (Ctrl+C)."""
        if self._processing:
            self._print_warning("!", True)
            self._print_line("Interrupted")
            self._processing = False
    
    def action_clear_output(self):
        """Clear output."""
        output = self.query_one("#output-area")
        output.clear_lines()
        self._show_welcome()
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes."""
        pass
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        text = event.value.strip()
        if text:
            event.input.value = ""
            self._process_input(text)
    
    @work(exclusive=True)
    async def _process_input(self, text: str):
        """Process user input through the agent."""
        self._print_line(f"> {text}", Style.USER_MESSAGE)
        self._print_empty()
        
        self._processing = True
        
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = True
        
        try:
            if self.agent:
                # Enable debug mode to capture tool output
                original_debug = self.agent.debug
                self.agent.debug = False  # Don't print debug to stdout
                
                # Use process_input - let agent handle tool execution normally
                result = await self.agent.process_input(
                    text, show_thinking=True  # Enable to capture thinking for display
                )

                # Restore debug setting
                self.agent.debug = original_debug

                # Display tool calls and results if any
                if hasattr(self.agent, '_last_tool_results'):
                    tool_results = getattr(self.agent, '_last_tool_results', [])
                    for tr in tool_results:
                        tool_name = tr.get('tool_name', 'unknown')
                        tool_result = tr.get('result', '')
                        success = tr.get('success', False)
                        
                        icon = self._get_tool_icon(tool_name)
                        self._print_line(f"{icon} {tool_name}", Style.TOOL_MESSAGE)
                        if success:
                            for line in tool_result.strip().split('\n')[:20]:
                                self._print_line(f"  {line}", Style.TEXT_DIM)
                        else:
                            self._print_error(f"  {tool_result[:100]}", True)
                        self._print_empty()

                # Display thinking if enabled
                if self.show_thinking and hasattr(self.agent, '_last_thinking'):
                    thinking = getattr(self.agent, '_last_thinking', None)
                    if thinking:
                        self._print_line(f"Thinking: {thinking}", Style.THINKING)
                        self._print_empty()
                
                # Display final response with role coloring
                if result and len(result) > 10:
                    # Debug: show context state
                    msg_count = len(self.agent.context_manager._messages) if hasattr(self.agent, 'context_manager') else 0
                    self._print_line(f"[DEBUG ctx msgs={msg_count}, result len={len(result)}]", Style.TEXT_DIM)
                    self._print_line(result[:300], Style.ASSISTANT_MESSAGE)
                    if len(result) > 300:
                        self._print_line("...", Style.TEXT_DIM)
                    self._print_empty()
                else:
                    self._print_line("(waiting for model response...)", Style.TEXT_DIM)
                
                self._print_line("✓", Style.TEXT_SUCCESS_BOLD)
            else:
                self._print_error("No agent configured")
        except Exception as e:
            self._print_error(f"Error: {e}")
        finally:
            self._processing = False
            input_widget.disabled = False
            input_widget.focus()


async def run_tui(agent=None, show_thinking: bool = True):
    """Run the TUI application."""
    app = NanoCodeTUI(agent=agent, show_thinking=show_thinking)
    await app.run_async()


if __name__ == "__main__":
    run_tui()