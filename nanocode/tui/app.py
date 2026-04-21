"""NanoCode TUI - Terminal UI matching opencode style."""

import asyncio
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any

from nanocode.core import ANSI
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Static, Button, Label, Input, TextArea, RichLog, DataTable
from textual.binding import Binding
from textual import work
from rich.theme import Theme
from rich.console import Console
from rich.text import Text
from rich.console import Console
from rich.syntax import Syntax


# Gruvbox Dark Theme Colors
GRUVBOX = {
    "bg": "#282828",
    "bg_soft": "#3c3836",
    "fg": "#ebdbb2",
    "red": "#ebdbb2",
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
    TEXT_DANGER = "\x1b[38;5;15m"
    TEXT_DANGER_BOLD = "\x1b[38;5;15m\x1b[1m"
    TEXT_SUCCESS = "\x1b[38;5;154m"
    TEXT_SUCCESS_BOLD = "\x1b[38;5;154m\x1b[1m"
    TEXT_INFO = "\x1b[38;5;176m"
    TEXT_INFO_BOLD = "\x1b[38;5;176m\x1b[1m"
    
    USER_MESSAGE = "\x1b[38;5;154m"
    USER_MESSAGE_BOLD = "\x1b[38;5;154m\x1b[1m"
    ASSISTANT_MESSAGE = "\x1b[38;5;15m"
    ASSISTANT_MESSAGE_BOLD = "\x1b[38;5;15m\x1b[1m"
    TOOL_MESSAGE = "\x1b[38;5;245m"
    TOOL_MESSAGE_BOLD = "\x1b[38;5;245m\x1b[1m"
    SYSTEM_MESSAGE = "\x1b[38;5;245m"
    SYSTEM_MESSAGE_BOLD = "\x1b[38;5;245m\x1b[1m"
    THINKING = "\x1b[38;5;214m\x1b[1m\x1b[3m"


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
        args_str = f"Args: {str(self.request.arguments)}" if self.request.arguments else ""
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


class CommandPaletteScreen(ModalScreen):
    """Modal screen for command palette."""
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]
    
    CSS = """
    CommandPaletteScreen {
        align: center middle;
    }
    
    CommandPaletteScreen > #container {
        width: 60;
        height: 20;
        border: solid #458588;
        background: #282828;
    }
    
    #title {
        text-style: bold;
        color: #d79921;
        padding: 1 2;
    }
    
    #search {
        padding: 0 2;
    }
    
    #commands {
        height: 1fr;
        padding: 0 1;
    }
    
    #help-text {
        color: #928374;
        padding: 0 2 1 2;
    }
    
    DataTable {
        height: 100%;
    }
    """
    
    def __init__(self, commands, **kwargs):
        super().__init__(**kwargs)
        self._commands = commands
        self._filtered = commands
    
    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Command Palette", id="title"),
            Input(placeholder="Search commands...", id="search"),
            DataTable(id="commands"),
            Static("↑↓ navigate  ⏎ select  esc cancel", id="help-text"),
            id="container",
        )
    
    def on_mount(self) -> None:
        table = self.query_one("#commands", DataTable)
        table.add_columns("Command", "Description")
        for cmd, desc in self._commands:
            table.add_row(cmd, desc)
        table.cursor_type = "row"
        self.query_one("#search", Input).focus()
    
    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.lower()
        table = self.query_one("#commands", DataTable)
        table.clear()
        self._filtered = [
            (cmd, desc) for cmd, desc in self._commands
            if query in cmd.lower() or query in desc.lower()
        ]
        for cmd, desc in self._filtered:
            table.add_row(cmd, desc)
    
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_index = event.cursor_row
        if 0 <= row_index < len(self._filtered):
            cmd, _ = self._filtered[row_index]
            self.dismiss(cmd)
    
    def action_cancel(self):
        """Close the palette without selecting."""
        self.dismiss(None)


class OutputArea(RichLog):
    """Scrollable output area using RichLog widget for color support."""

    GRUVBOX = {
        "fg": "#ebdbb2",
        "gray": "#928374",
        "red": "#cc241d",
        "green": "#98971a",
        "yellow": "#d79921",
        "blue": "#458588",
        "purple": "#b16286",
        "aqua": "#689d6a",
        "orange": "#d65d0e",
        "red_bright": "#fb4934",
        "green_bright": "#b8bb26",
        "yellow_bright": "#fabd2f",
        "blue_bright": "#83a598",
        "purple_bright": "#d3869b",
        "aqua_bright": "#8ec07c",
        "orange_bright": "#fe8019",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lines: list[str] = []
        self._md_theme: object = None

    def _render_markdown(self, text: str) -> object:
        """Get a markdown renderer with gruvbox theme."""
        from rich.markdown import Markdown
        return Markdown(text)

    def add_line(self, text: str, style: str = ""):
        """Add a line to output with Rich markdown rendering."""
        import re
        from rich.text import Text
        from rich.markdown import Markdown

        style_map = {
            "user": self.GRUVBOX["green"],
            "assistant": self.GRUVBOX["fg"],
            "tool": self.GRUVBOX["gray"],
            "dim": self.GRUVBOX["gray"],
            "success": self.GRUVBOX["green"],
            "warning": self.GRUVBOX["yellow"],
            "danger": self.GRUVBOX["fg"],
            "thinking": self.GRUVBOX["yellow"],
            "info": self.GRUVBOX["blue_bright"],
        }

        base_color = style_map.get(style, "")

        # Handle Rich markup only for thinking style (e.g., [bold italic yellow]| Thinking:[/])
        if style == "thinking" and "[" in text and "]" in text:
            from rich.text import Text as RichText
            rich_text = RichText.from_markup(text)
            self.write(rich_text)
            self._lines.append(text)
            return

        # Use markdown rendering for non-code-block text
        if '```' in text:
            code_block_pattern = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
            last_end = 0
            for match in code_block_pattern.finditer(text):
                if match.start() > last_end:
                    text_part = text[last_end:match.start()]
                    if text_part.strip():
                        md = Markdown(text_part)
                        self.write(md)

                # Code block - use syntax highlighting
                lang = match.group(1) or "python"
                code = match.group(2).rstrip()
                from rich.syntax import Syntax
                syntax = Syntax(code, lang, theme="gruvbox-dark", line_numbers=False)
                self.write(syntax)
                last_end = match.end()

            if last_end < len(text):
                text_part = text[last_end:]
                if text_part.strip():
                    md = Markdown(text_part)
                    self.write(md)
        else:
            # Render as markdown
            md = Markdown(text)
            self.write(md)

        self._lines.append(text)

    def _write_formatted(self, text: str, base_color: str):
        """Write formatted text with basic markdown highlighting."""
        import re
        from rich.text import Text

        if not base_color:
            self.write(text)
            return

        bold_pattern = re.compile(r'\*\*([^*]+)\*\*')
        code_pattern = re.compile(r'`([^`]+)`')

        last_end = 0
        for match in bold_pattern.finditer(text):
            if match.start() > last_end:
                self.write(text[last_end:match.start()])
            self.write(Text(match.group(1), style=base_color + " bold"))
            last_end = match.end()

        if last_end < len(text):
            self.write(text[last_end:])

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
#content-area {
    width: 1fr;
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
#sidebar {
    width: 20%;
    min-width: 30;
    max-width: 50;
    background: #3c3836;
    border-left: solid #928374;
}
#sidebar-title {
    background: #3c3836;
    color: #d79921;
    padding: 0 1;
    text-style: bold;
}
#sidebar-body {
    padding: 1;
    color: #ebdbb2;
}
#sidebar-footer {
    background: #3c3836;
    color: #928374;
    padding: 0 1;
}
#input-prompt {
    width: 2;
    text-align: right;
    color: #ebdbb2;
}
#spinner {
    width: 3;
    color: #458588;
    text-style: bold;
}
.spinner-active {
    color: #458588;
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
    color: #d79921;
    text-style: bold italic;
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
    color: #d79921;
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
        Binding("f1", "show_command_palette", "Commands", show=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=True),
    ]

    def on_key(self, event) -> None:
        """Capture arrow keys when Input is focused."""
        input_widget = self.query_one("#input", Input)
        if self.focused == input_widget:
            if event.key == "up":
                self._history_up()
                event.prevent_default()
            elif event.key == "down":
                self._history_down()
                event.prevent_default()

    # CLI commands list (not Textual CommandPalette)
    CLI_COMMANDS = [
        ("/help", "Show help and commands"),
        ("/clear", "Clear output"),
        ("/exit", "Exit the application"),
        ("/quit", "Exit the application"),
        ("/history", "Show conversation history"),
        ("/tools", "Show available tools"),
        ("/provider", "Switch LLM provider"),
        ("/plan", "Enter plan mode"),
        ("/resume", "Resume a task"),
        ("/checkpoint", "Create a checkpoint"),
        ("/skills", "Show available skills"),
        ("/snapshot", "Manage snapshots"),
        ("/snapshots", "List snapshots"),
        ("/trace", "Toggle trace mode"),
        ("/debug", "Toggle debug mode"),
        ("/compact", "Compact context"),
        ("/show_thinking", "Toggle thinking display"),
        ("/agents", "Show available agents"),
        ("/agent", "Switch agent"),
        ("/tasks", "Show active subagent sessions"),
        ("/kill", "Kill a subagent session"),
    ]

    def __init__(self, agent=None, show_thinking: bool = True):
        super().__init__()
        self.agent = agent
        self.show_thinking = show_thinking
        self._processing = False
        self._input_history: list[str] = []
        self._history_index = -1
        self._sidebar_visible = True
        self._sidebar_content: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="content-area"):
                with OutputArea(id="output-area", auto_scroll=True):
                    pass
                with Horizontal(id="input-container"):
                    yield Static("", id="spinner")
                    yield Label("➜", id="input-prompt")
                    yield Input(placeholder="Enter your task...", id="input")
            with Vertical(id="sidebar"):
                yield Static("╭─ Info ──╮", id="sidebar-title")
                with ScrollableContainer(id="sidebar-content"):
                    yield Static("", id="sidebar-body")
                yield Static("╰─────────╯", id="sidebar-footer")
        yield Static("", id="status-bar")
        yield Footer()
    
    def on_mount(self) -> None:
        """Initialize on mount."""
        self.query_one("#input", Input).focus()
        self._show_welcome()
        
        if self.agent:
            self._setup_permission_callback()
        
        self._status_timer = self.set_interval(1.0, self._update_status_bar)
        self._sidebar_timer = self.set_interval(2.0, self._update_sidebar)
        self._update_sidebar()

    def _update_status_bar(self) -> None:
        """Update status bar with subagent count."""
        status_bar = self.query_one("#status-bar", Static)

        if self.agent and hasattr(self.agent, "tool_registry"):
            task_tool = self.agent.tool_registry.get("task")
            if task_tool and hasattr(task_tool, "sessions"):
                active = sum(1 for s in task_tool.sessions.values() if not s.completed)
                if active > 0:
                    status_bar.update(f"Tasks: {active}")
                    self._update_sidebar()
                    return

        status_bar.update("")
        self._update_sidebar()

    def _fetch_model_info(self):
        """Fetch model info from models.dev registry."""
        try:
            from nanocode.llm.registry import get_registry
            import asyncio

            async def fetch():
                registry = get_registry()
                await registry.load()
                return registry

            registry = asyncio.run(fetch())
            if self.agent and hasattr(self.agent, "llm") and self.agent.llm:
                model = self.agent.llm.model
                if registry and model:
                    info = registry.get_model_by_full_id(model)
                    if info:
                        return info
        except Exception:
            pass
        return None

    def _update_sidebar(self) -> None:
        """Update sidebar content with current state info."""
        if not self._sidebar_visible:
            return

        lines = []

        if self.agent and hasattr(self.agent, "context_manager"):
            ctx = self.agent.context_manager
            usage = ctx.get_token_usage()
            current = usage.get("current_tokens", 0)
            max_tok = usage.get("max_tokens", 0)
            if max_tok > 0:
                pct = (current / max_tok) * 100
                lines.append(f"Context: {current:,} / {max_tok:,} ({pct:.0f}%)")
            else:
                lines.append(f"Context: {current:,}")
            lines.append(f"Msgs: {usage.get('message_count', 0)}")

        if self.agent and hasattr(self.agent, "current_agent"):
            lines.append(f"Agent: {self.agent.current_agent.name}")

        if self.agent and hasattr(self.agent, "llm") and self.agent.llm:
            model = getattr(self.agent.llm, "model", "unknown")
            lines.append(f"Model: {model}")
            if hasattr(self.agent.llm, "max_tokens"):
                lines.append(f"Max out: {self.agent.llm.max_tokens:,}")

        if hasattr(self, "_session_id") and self._session_id:
            lines.append(f"Session: {self._session_id[:12]}")

        if self.agent and hasattr(self.agent, "tool_registry"):
            task_tool = self.agent.tool_registry.get("task")
            if task_tool and hasattr(task_tool, "sessions"):
                active = sum(1 for s in task_tool.sessions.values() if not s.completed)
                if active > 0:
                    lines.append(f"Active tasks: {active}")

        try:
            sidebar_body = self.query_one("#sidebar-body", Static)
            sidebar_body.update("\n".join(lines))
        except Exception:
            pass

    def action_toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        self._sidebar_visible = not self._sidebar_visible
        try:
            sidebar = self.query_one("#sidebar")
            if self._sidebar_visible:
                sidebar.display = "block"
            else:
                sidebar.display = "none"
            self._update_sidebar()
        except Exception:
            pass

    def _update_spinner(self) -> None:
        """Update spinner animation."""
        if not self._processing:
            if hasattr(self, '_spinner_timer') and self._spinner_timer:
                self._spinner_timer.stop()
            return
        
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_chars)
        spinner = self.query_one("#spinner", Static)
        spinner.update(self._spinner_chars[self._spinner_index])

    def _show_welcome(self):
        """Show welcome message matching opencode style."""
        self._print_logo()
        self._print_empty()
        self._print_line("Type your task or 'help' for commands", Style.TEXT_DIM)
        self._print_empty()
    
    def _print_logo(self):
        """Print simple banner."""
        self._print_line("NanoCode", Style.TEXT_INFO_BOLD)
    
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
        }
        
        if style == Style.THINKING:
            # Split: "Thinking:" gets bold italic yellow, rest gets white
            prefix = ""
            rest = text
            if "| Thinking:" in text:
                parts = text.split("| Thinking:", 1)
                prefix = parts[0] + "| Thinking:"
                rest = parts[1] if len(parts) > 1 else ""
            
            from rich.text import Text as RichText
            if prefix and rest:
                full_text = RichText()
                full_text.append(prefix + " ", style="bold italic yellow")
                full_text.append(rest, style="white")
            elif prefix:
                full_text = RichText(prefix, style="bold italic yellow")
            else:
                full_text = RichText.from_markup(text)
            
            output.write(full_text)
            output._lines.append(text)
            return
        
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

        # Use opencode's ~ icon format
        line = f"~ {icon} {title}"
        if desc:
            line = f"{line} {Style.TEXT_DIM}{desc}{Style.TEXT_NORMAL}"

        self._print_line(line, Style.TEXT_NORMAL)

        # Block tool style with left border for output
        if tool_call.state == ToolState.COMPLETED and tool_call.output:
            self._print_empty()
            for output_line in tool_call.output.strip().split("\n"):
                if output_line.strip():  # Skip empty lines
                    self._print_line(f"| {output_line}", Style.TEXT_DIM)
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
            filepath = normalize_path(arguments.get("path", ""))
            extra_args = {k: v for k, v in arguments.items()
                         if k != "filePath" and isinstance(v, (str, int, bool))}
            desc = f"[{', '.join(f'{k}={v}' for k, v in extra_args.items())}]" if extra_args else ""
            return ToolCall(tool=tool_name, title=f"Read {filepath}", description=desc, icon="→")

        if tool_name == "write":
            filepath = normalize_path(arguments.get("path", ""))
            return ToolCall(tool=tool_name, title=f"Write {filepath}", icon="←")

        if tool_name == "edit":
            filepath = normalize_path(arguments.get("path", ""))
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
            workdir = arguments.get("workdir", "")
            if workdir and workdir != ".":
                try:
                    workdir = os.path.relpath(workdir, os.getcwd())
                except ValueError:
                    pass
                title = f"# {command} in {workdir}"
            else:
                title = f"# {command}"
            return ToolCall(tool=tool_name, title=title, icon="$")
        
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
    
    def action_show_cli_commands(self):
        """Show command palette."""
        import sys
        sys.stderr.write(f"DEBUG: action_show_cli_commands called\n")
        sys.stderr.write(f"CLI_COMMANDS = {self.CLI_COMMANDS}\n")
        sys.stderr.flush()
        output = self.query_one("#output-area")
        output.add_line(f"\n=== Available Commands ===")
        for cmd, desc in self.CLI_COMMANDS:
            output.add_line(f"  {cmd:<20} {desc}")
        output.add_line(f"\nPress Ctrl+P to show this menu")
    
    @work()
    async def action_show_command_palette(self):
        """Show the command palette popup."""
        screen = CommandPaletteScreen(self.CLI_COMMANDS)
        result = await self.push_screen_wait(screen)
        if result:
            input_widget = self.query_one("#input", Input)
            input_widget.value = result
            input_widget.focus()
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes."""
        pass
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        text = event.value.strip()
        if text:
            self._input_history.append(text)
            self._history_index = len(self._input_history)
            event.input.value = ""
            self._process_input(text)

    def _history_up(self):
        """Navigate history up (previous command)."""
        input_widget = self.query_one("#input", Input)
        if self._input_history and self._history_index > 0:
            self._history_index -= 1
            input_widget.value = self._input_history[self._history_index]
            input_widget.cursor_position = len(input_widget.value)

    def _history_down(self):
        """Navigate history down (next command)."""
        input_widget = self.query_one("#input", Input)
        if self._history_index < len(self._input_history) - 1:
            self._history_index += 1
            input_widget.value = self._input_history[self._history_index]
            input_widget.cursor_position = len(input_widget.value)
        elif self._history_index == len(self._input_history) - 1:
            self._history_index += 1
            input_widget.value = ""
            input_widget.cursor_position = 0
    
    @work(exclusive=True)
    async def _process_input(self, text: str):
        import traceback
        self._print_line(f"> {text}", Style.USER_MESSAGE)
        self._print_empty()

        # Handle slash-prefixed commands locally before sending to agent
        if text.startswith("/"):
            await self._handle_command(text)
            return

        self._processing = True

        # Show and animate spinner
        spinner = self.query_one("#spinner", Static)
        spinner.update("◐")
        spinner.classes = "spinner-active"
        
        # Start spinner animation
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spinner_index = 0
        self._spinner_timer = self.set_interval(0.15, self._update_spinner)

        input_widget = self.query_one("#input", Input)
        input_widget.disabled = True

        if not self.agent:
            self._print_error("No agent configured - run via 'nanocode -g textual'")
            import sys
            import threading
            sys.stderr.write(f"DEBUG: agent is None, thread={threading.current_thread().name}\n")
            self._processing = False
            input_widget.disabled = False
            input_widget.focus()
            return

        try:
            if self.agent:
                # Enable debug mode to capture tool output
                original_debug = self.agent.debug
                self.agent.debug = False  # Don't print debug to stdout
                
                # Use process_input - let agent handle tool execution normally
                # Suppress stdout/stderr print output to TUI but write to log file
                import io
                import sys
                import logging
                import datetime
                import traceback
                
                # Save original stdout/stderr
                self._saved_stdout = sys.stdout
                self._saved_stderr = sys.stderr
                
                # Create capture buffers
                stdout_capture = io.StringIO()
                stderr_capture = io.StringIO()
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture
                
                # Suppress all loggers to file only
                root_logger = logging.getLogger()
                old_level = root_logger.level
                root_logger.setLevel(logging.DEBUG)
                
                # Disable all handlers and add file handler only
                for h in root_logger.handlers[:]:
                    root_logger.removeHandler(h)
                fh = logging.FileHandler("/tmp/nanocode.log")
                fh.setLevel(logging.DEBUG)
                root_logger.addHandler(fh)
                
                try:
                    result = await self.agent.process_input(
                        text, show_thinking=True, show_messages=False
                    )
                finally:
                    # Restore logging
                    root_logger.removeHandler(fh)
                    fh.close()
                    for h in root_logger.handlers[:]:
                        root_logger.removeHandler(h)
                    root_logger.setLevel(old_level)
                
                # Restore stdout/stderr (but don't restore - keep them captured!)
                # Actually, keep them captured permanently to prevent any print from showing
                # sys.stdout = self._saved_stdout
                # sys.stderr = self._saved_stderr
                
                # Write captured output to log
                stdout_output = stdout_capture.getvalue()
                stderr_output = stderr_capture.getvalue()
                
                if stdout_output or stderr_output:
                    logger = logging.getLogger("nanocode.tui")
                    log_output = f"\n=== TUI Debug Output {datetime.datetime.now().isoformat()} ===\n"
                    log_output += stdout_output
                    if stderr_output:
                        log_output += f"\nSTDERR:\n{stderr_output}"
                    logger.debug(log_output)

                # Restore debug setting
                self.agent.debug = original_debug

                # Display tool calls using opencode's format
                if hasattr(self.agent, '_last_tool_results'):
                    tool_results = getattr(self.agent, '_last_tool_results', [])
                    for tr in tool_results:
                        tool_name = tr.get('tool_name', 'unknown')
                        arguments = tr.get('arguments', {})
                        success = tr.get('success', False)

                        # Format with full details using _format_tool_call
                        tool_call = self._format_tool_call(tool_name, arguments)

                        # Add result info from the tool call
                        result = tr.get('result', '')
                        if tool_name in ('grep', 'glob') and result:
                            # Count results
                            lines = result.strip().split('\n') if result else []
                            count = len([l for l in lines if l.strip()])
                            suffix = f"({count} matches)"
                            tool_call.description = suffix
                        elif tool_name == 'read' and result:
                            lines = result.strip().split('\n')
                            count = len(lines)
                            suffix = f"[{count} lines]"
                            tool_call.description = suffix

                        status = "✓" if success else "✗"
                        self._print_line(f"~ {tool_call.icon} {tool_call.title} {tool_call.description} {status}", Style.TOOL_MESSAGE)

                # Display thinking (with left border styling like opencode)
                # Only show if not already in the result to avoid duplication
                if self.show_thinking and hasattr(self.agent, '_last_thinking'):
                    thinking = getattr(self.agent, '_last_thinking', None)
                    if thinking and thinking not in (result or ""):
                        self._print_line(f"| Thinking: {thinking}", Style.THINKING)
                        self._print_empty()

                # Display final response with role coloring and syntax highlighting
                if result and len(result) > 10:
                    output_area = self.query_one("#output-area")
                    output_area.add_line(result, "assistant")
                else:
                    self._print_line("(waiting for model response...)", Style.TEXT_DIM)

                # Completion marker like opencode's `▣`
                self._print_line("▣", Style.TEXT_SUCCESS_BOLD)
            else:
                self._print_error("No agent configured")
        except Exception as e:
            import traceback
            self._print_error(f"Error: {e}")
            traceback.print_exc()
        finally:
            # Stop spinner
            if hasattr(self, '_spinner_timer') and self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            spinner = self.query_one("#spinner", Static)
            spinner.update("")  # Clear spinner
            spinner.classes = ""  # Remove active class
            
            self._processing = False
            input_widget.disabled = False
            input_widget.focus()

    async def _handle_command(self, command: str):
        """Handle slash-prefixed commands locally."""
        cmd = command.lower()
        parts = command.split()

        if cmd in ("/exit", "/quit", "/q"):
            session_id = getattr(self.agent, '_session_id', 'unknown') if self.agent else 'unknown'
            self.exit()
            print()
            print("\033[96m" + "░██████╗ ███████╗████████╗██████╗  ██████╗ ██████╗  █████╗ ██████╗ ██████╗ " + "\033[0m")
            print("\033[96m" + "██╔════╝ ██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗" + "\033[0m")
            print("\033[96m" + "██║  ███╗█████╗     ██║   ██████╔╝██║   ██║██████╔╝███████║██████╔╝███████║" + "\033[0m")
            print("\033[96m" + "██║   ██║██╔══╝     ██║   ██╔══██╗██║   ██║██╔══██╗██╔══██║██╔══██╗██╔══██║" + "\033[0m")
            print("\033[96m" + "╚██████╔╝███████╗   ██║   ██║  ██║╚██████╔╝██████╔╝██║  ██║██║  ██║██║  ██║" + "\033[0m")
            print("\033[96m" + " ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝" + "\033[0m")
            print()
            print(f"Session: {session_id}")
            return

        if cmd == "/help":
            self._print_line("Available commands:")
            for c, desc in self.CLI_COMMANDS:
                self._print_line(f"  {c:<20} {desc}")
            return

        if cmd == "/clear":
            output = self.query_one("#output-area")
            output.clear_lines()
            self._show_welcome()
            return

        if cmd == "/history":
            self._print_line("Use Ctrl+H for history")
            return

        if cmd == "/tools":
            if self.agent and hasattr(self.agent, "tool_registry"):
                tools = self.agent.tool_registry.list_tools()
                self._print_line("Available tools:")
                for t in tools:
                    name = t.name if hasattr(t, "name") else "unknown"
                    desc = t.description if hasattr(t, "description") else ""
                    self._print_line(f"  {name}: {desc}")
            else:
                self._print_line("No tools available")
            return

        if cmd == "/provider":
            self._print_line("Use --provider flag to set provider")
            return

        if cmd == "/plan":
            self._print_line("Planning not yet implemented in TUI")
            return

        if cmd.startswith("/resume"):
            self._print_line("Use nanocode -r <session_id> to resume")
            return

        if cmd == "/checkpoint":
            self._print_line("Checkpoints not yet implemented in TUI")
            return

        if cmd == "/skills":
            if self.agent and hasattr(self.agent, "skills_manager"):
                skills = self.agent.skills_manager.list_skills()
                self._print_line("Available skills:")
                for s in skills:
                    name = s.get("name", "unknown") if isinstance(s, dict) else getattr(s, "name", "unknown")
                    desc = s.get("description", "") if isinstance(s, dict) else getattr(s, "description", "")
                    self._print_line(f"  {name}: {desc}")
            else:
                self._print_line("No skills found")
            return

        if cmd == "/snapshot":
            self._print_line("Snapshots not yet implemented in TUI")
            return

        if cmd == "/snapshots":
            self._print_line("Snapshots not yet implemented in TUI")
            return

        if cmd == "/trace":
            if self.agent:
                self._print_line("Trace not yet implemented")
            return

        if cmd == "/compact":
            if self.agent and hasattr(self.agent, "context_manager"):
                self.agent.context_manager._compact()
                self._print_line("Context compacted")
            return

        if cmd == "/show_thinking":
            self.show_thinking = not self.show_thinking
            self._print_line(f"Show thinking: {self.show_thinking}")
            return

        if cmd == "/agents":
            if self.agent and hasattr(self.agent, "nanocode_registry"):
                agents = self.agent.nanocode_registry.list_primary()
                self._print_line("Available agents:")
                for a in agents:
                    name = a.name if hasattr(a, "name") else "unknown"
                    desc = a.description if hasattr(a, "description") else ""
                    self._print_line(f"  {name}: {desc}")
            return

        if cmd.startswith("/agent "):
            agent_name = parts[1] if len(parts) > 1 else None
            if agent_name and self.agent and hasattr(self.agent, "switch_agent"):
                success = self.agent.switch_agent(agent_name)
                if success:
                    self._print_line(f"Switched to agent: {agent_name}")
                else:
                    self._print_error(f"Unknown agent: {agent_name}")
            else:
                self._print_line("Use /agents to list available agents")
            return

        if cmd == "/tasks":
            if self.agent and hasattr(self.agent, "tool_registry"):
                task_tool = self.agent.tool_registry.get_tool("task")
                if task_tool and hasattr(task_tool, "sessions"):
                    sessions = task_tool.sessions
                    if sessions:
                        self._print_line("Active subagent sessions:")
                        for sid, sess in sessions.items():
                            status = "completed" if sess.completed else "running"
                            aname = sess.agent.name if hasattr(sess.agent, "name") else "?"
                            self._print_line(f"  {sid[:8]}: {aname} [{status}]")
                    else:
                        self._print_line("No active subagent sessions")
                else:
                    self._print_line("Task tool not available")
            return

        if cmd.startswith("/kill "):
            task_id = parts[1] if len(parts) > 1 else None
            if task_id and self.agent and hasattr(self.agent, "tool_registry"):
                task_tool = self.agent.tool_registry.get_tool("task")
                if task_tool and hasattr(task_tool, "sessions") and task_id in task_tool.sessions:
                    del task_tool.sessions[task_id]
                    self._print_line(f"Killed session: {task_id[:8]}")
                else:
                    self._print_error(f"Session not found: {task_id[:8]}")
            else:
                self._print_error("Usage: /kill <session_id>")
            return

        if cmd == "/debug":
            if self.agent:
                self.agent.debug = not getattr(self.agent, "debug", False)
                self._print_line(f"Debug: {self.agent.debug}")
            return

        # Unknown command
        self._print_error(f"Unknown command: {command}. Type /help for available commands.")
        return


async def run_tui(agent=None, show_thinking: bool = True):
    """Run the TUI application."""
    app = NanoCodeTUI(agent=agent, show_thinking=show_thinking)
    await app.run_async()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_tui())