"""NanoCode TUI - Terminal UI matching opencode style."""

import asyncio
import os
import sys
from dataclasses import dataclass
from enum import Enum


class RichColor(Enum):
    """Gruvbox-inspired color palette for rich text."""
    FG = "#ebdbb2"           # Light gray - main text
    YELLOW = "#d79921"       # Yellow - highlights/titles
    GREEN = "#98971a"        # Green - success/user
    RED = "#cc241d"          # Red - danger/error
    BLUE = "#458588"         # Blue - info
    PURPLE = "#b16286"       # Purple - assistant
    AQUA = "#83a598"         # Aqua - tool
    GRAY = "#928374"         # Gray - dim/system

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
)

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
    """Rich text style names for output area."""
    TEXT_HIGHLIGHT = "cyan"
    TEXT_HIGHLIGHT_BOLD = "cyan bold"
    TEXT_DIM = "dim"
    TEXT_DIM_BOLD = "dim"
    TEXT_NORMAL = ""
    TEXT_NORMAL_BOLD = "bold"
    TEXT_WARNING = RichColor.YELLOW.value
    TEXT_WARNING_BOLD = f"{RichColor.YELLOW.value} bold"
    TEXT_DANGER = RichColor.RED.value
    TEXT_DANGER_BOLD = f"{RichColor.RED.value} bold"
    TEXT_SUCCESS = RichColor.GREEN.value
    TEXT_SUCCESS_BOLD = f"{RichColor.GREEN.value} bold"
    TEXT_INFO = RichColor.BLUE.value
    TEXT_INFO_BOLD = f"{RichColor.BLUE.value} bold"

    USER_MESSAGE = RichColor.GREEN.value
    USER_MESSAGE_BOLD = f"{RichColor.GREEN.value} bold"
    ASSISTANT_MESSAGE = RichColor.PURPLE.value
    ASSISTANT_MESSAGE_BOLD = f"{RichColor.PURPLE.value} bold"
    TOOL_MESSAGE = RichColor.AQUA.value
    TOOL_MESSAGE_BOLD = f"{RichColor.AQUA.value} bold"
    SYSTEM_MESSAGE = RichColor.GRAY.value
    SYSTEM_MESSAGE_BOLD = f"{RichColor.GRAY.value} bold"
    THINKING = f"{RichColor.YELLOW.value} italic"


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


class ModelExplorerScreen(ModalScreen):
    """Modal screen for exploring available models from models.dev."""

    CSS = """
    ModelExplorerScreen {
        align: center middle;
    }

    ModelExplorerScreen > #model-dialog {
        width: 80;
        height: 80%;
        border: solid #b16286;
        background: #282828;
        padding: 1 2;
    }

    #model-title {
        text-align: center;
        text-style: bold;
        color: #b16286;
    }

    #model-subtitle {
        color: #928374;
        text-align: center;
    }

    #search-input {
        margin-bottom: 1;
    }

    #model-list {
        height: 1fr;
    }

    DataTable {
        height: 100%;
    }

    #help-text {
        color: #928374;
        padding: 0 2 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "select", "Select"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("up", "move_up", "Up"),
        Binding("down", "move_down", "Down"),
    ]

    def __init__(self, on_select=None, **kwargs):
        super().__init__(**kwargs)
        self._on_select = on_select
        self._models: list[tuple[str, str, int]] = []  # (provider/model, provider, context_limit)
        self._filtered: list[tuple[str, str, int]] = []
        self._loading = True
        self._refresh_time = None
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Model Explorer (models.dev)", id="model-title"),
            Static("Loading...", id="model-subtitle"),
            Input(placeholder="Search models...", id="search-input"),
            DataTable(id="model-list"),
            Static("↑↓: navigate | Enter: select | Ctrl+R: refresh | Escape: cancel", id="help-text"),
        )

    def on_mount(self):
        self._load_registry()

    def _load_registry(self, force: bool = False):
        async def load_models():
            from nanocode.llm.registry import get_registry
            from nanocode.llm.registry import CACHE_TTL_SECONDS
            registry = get_registry()
            await registry.load(force_refresh=force)
            age = registry._cache_age_seconds() if not force else 0
            remaining = CACHE_TTL_SECONDS - age
            return registry, age, remaining

        async def set_models(result):
            registry, age, remaining = result
            subtitle = self.query_one("#model-subtitle", Static)
            if age < 60:
                subtitle.update(f"Cache: just refreshed ({len(registry._providers)} providers)")
            else:
                mins = int(remaining / 60)
                subtitle.update(f"Cache: {mins}m remaining ({len(registry._providers)} providers)")

            models = []
            for pid, provider in registry._providers.items():
                for mname, minfo in provider.models.items():
                    models.append((f"{pid}/{mname}", pid, minfo.context_limit))
            models.sort(key=lambda x: -x[2])

            self._models = models
            self._filtered = models[:100]
            self._loading = False
            self._update_list()

        asyncio.create_task(load_models()).add_done_callback(
            lambda f: self.call_later(set_models, f.result())
        )

    @work()
    async def action_refresh(self):
        """Refresh the model registry."""
        self._loading = True
        self.query_one("#model-subtitle", Static).update("Refreshing...")
        self._load_registry(force=True)

    def _update_list(self):
        table = self.query_one("#model-list", DataTable)
        table.clear()
        table.add_columns("Provider/Model", "Context", "Output")
        for i, (full_id, provider, ctx) in enumerate(self._filtered[:50]):
            output = min(ctx // 8, 16384)
            table.add_row(full_id, f"{ctx:,}", f"{output:,}")

    def on_input_changed(self, event: Input.Changed):
        query = event.value.lower()
        if query:
            self._filtered = [
                (m, p, c) for m, p, c in self._models
                if query in m.lower() or query in p.lower()
            ][:50]
        else:
            self._filtered = self._models[:50]
        self._selected_index = 0
        self._update_list()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        row_index = event.cursor_row
        if 0 <= row_index < len(self._filtered):
            full_id, provider, ctx = self._filtered[row_index]
            self.dismiss((full_id, provider))

    def action_cancel(self):
        self.dismiss(None)

    def action_select(self):
        """Select current model and dismiss."""
        if 0 <= self._selected_index < len(self._filtered):
            full_id, provider, ctx = self._filtered[self._selected_index]
            self.dismiss((full_id, provider))

    def action_move_up(self):
        """Move selection up."""
        if self._filtered:
            self._selected_index = max(0, self._selected_index - 1)
            table = self.query_one("#model-list", DataTable)
            table.cursor_position = self._selected_index

    def action_move_down(self):
        """Move selection down."""
        if self._filtered:
            self._selected_index = min(len(self._filtered) - 1, self._selected_index + 1)
            table = self.query_one("#model-list", DataTable)
            table.cursor_position = self._selected_index


class MessageActionScreen(ModalScreen):
    """Modal screen for message actions: fork, copy, revert."""

    CSS = """
    MessageActionScreen {
        align: center middle;
    }

    MessageActionScreen > #msg-dialog {
        width: 60;
        height: auto;
        border: solid #98971f;
        background: #282828;
        padding: 1 2;
    }

    #msg-dialog-title {
        text-align: center;
        text-style: bold;
        color: #98971f;
        margin-bottom: 1;
    }

    #msg-dialog-preview {
        color: #ebdbb2;
        margin-bottom: 1;
        height: 5;
    }

    #msg-dialog-buttons {
        align: center middle;
        margin-top: 1;
    }

    #msg-dialog-buttons > Button {
        margin: 0 1;
        min-width: 10;
    }
    """

    def __init__(self, message_text: str, message_index: int = 0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._message_text = message_text
        self._message_index = message_index
        self._result = None

    def compose(self) -> ComposeResult:
        preview = self._message_text[:200] + "..." if len(self._message_text) > 200 else self._message_text
        yield Vertical(
            Static("Message Actions", id="msg-dialog-title"),
            Static(preview, id="msg-dialog-preview"),
            Horizontal(
                Button("Fork", id="btn-fork", variant="primary"),
                Button("Copy", id="btn-copy", variant="default"),
                Button("Revert", id="btn-revert", variant="warning"),
                Button("Cancel", id="btn-cancel", variant="default"),
                id="msg-dialog-buttons",
            ),
            id="msg-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id
        if action == "btn-fork":
            self._result = ("fork", self._message_text, self._message_index)
        elif action == "btn-copy":
            self._result = ("copy", self._message_text, self._message_index)
        elif action == "btn-revert":
            self._result = ("revert", self._message_text, self._message_index)
        else:
            self._result = None
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
        self._user_messages: list[tuple[int, str]] = []  # (index, text) for user messages

    def _render_markdown(self, text: str) -> object:
        """Get a markdown renderer with gruvbox theme."""
        from rich.markdown import Markdown
        return Markdown(text)

    def _on_click(self, event: "events.Click") -> None:
        """Handle click to show message actions for user messages."""
        # RichLog doesn't support click spans, so show actions for last user message
        if self._user_messages:
            index, text = self._user_messages[-1]
            self.app.push_screen(
                MessageActionScreen(text, index),
                self._handle_message_action,
            )

    def _handle_message_action(self, result):
        """Handle result from MessageActionScreen."""
        if result:
            action, text, index = result
            if action == "copy":
                import pyperclip
                pyperclip.copy(text)
                self.app.notify("Copied to clipboard", severity="info")

    def add_line(self, text: str, style: str = ""):
        """Add a line to output with Rich markdown rendering."""
        import re

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

        # Track user messages for click actions (check both "user" and color value)
        user_color = self.GRUVBOX["green"]
        is_user = style == "user" or style == user_color
        if is_user:
            self._user_messages.append((len(self._user_messages), text))

        # Handle custom styles before markdown rendering
        if "[thought]" in text:
            from rich.text import Text as RichText
            rich_text = RichText()
            parts = text.split("[thought]")
            if parts[0]:
                rich_text.append(parts[0])
            for part in parts[1:]:
                if "[/thought]" in part:
                    label, rest = part.split("[/thought]", 1)
                    rich_text.append(label, f"{self.GRUVBOX['yellow']} italic")
                    if rest:
                        rich_text.append(rest)
                else:
                    rich_text.append(part)
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
.sidebar-header {
    color: #d79921;
}
.sidebar-path {
    color: #83a598;
}
.sidebar-add {
    color: #98971f;
}
.sidebar-del {
    color: #fb4934;
}
.sidebar-done {
    color: #98971f;
}
.sidebar-active {
    color: #83a598;
}
.sidebar-cancel {
    color: #fb4934;
}
.sidebar-dim {
    color: #928374;
}
.sidebar-mcp-on {
    color: #98971f;
}
.sidebar-mcp-off {
    color: #928374;
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
        Binding("ctrl+m", "message_actions", "Actions", show=True),
        Binding("f2", "model_explorer", "Models", show=True),
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
        self._history_file = self._get_history_file()
        self._load_input_history()

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
                    yield RichLog(id="sidebar-body")
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

    def on_unmount(self) -> None:
        """Save history before exit."""
        self._save_input_history()

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
            import asyncio

            from nanocode.llm.registry import get_registry

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
            max_tok = usage.get("context_limit", 0)
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
            max_out = getattr(self.agent.llm, "max_tokens", None)
            if max_out:
                lines.append(f"Max out: {max_out:,}")

        if hasattr(self, "_session_id") and self._session_id:
            lines.append(f"Session: {self._session_id[:12]}")

        if self.agent and hasattr(self.agent, "tool_registry"):
            task_tool = self.agent.tool_registry.get("task")
            if task_tool and hasattr(task_tool, "sessions"):
                active = sum(1 for s in task_tool.sessions.values() if not s.completed)
                if active > 0:
                    lines.append(f"Active tasks: {active}")

            todo_tool = self.agent.tool_registry.get("todo")
            if todo_tool and hasattr(todo_tool, "todo_service"):
                session_id = getattr(self.agent, '_session_id', None)
                if session_id:
                    todos = todo_tool.todo_service.get_todos(session_id)
                    if todos:
                        lines.append("[#d79921]─ Todos ─[/#d79921]")
                        for t in todos:
                            if t.status == "completed":
                                icon = "[#98971f]✓[/#98971f]"
                            elif t.status == "in_progress":
                                icon = "[#83a598]◐[/#83a598]"
                            elif t.status == "cancelled":
                                icon = "[#fb4934]✗[/#fb4934]"
                            else:
                                icon = "[#928374]○[/#928374]"
                            content = t.content[:30] + "..." if len(t.content) > 30 else t.content
                            lines.append(f"  {icon} {content}")
            elif todo_tool and hasattr(todo_tool, "tasks"):
                todo_items = todo_tool.tasks
                if todo_items:
                    lines.append("[#d79921]─ Todos ─[/#d79921]")
                    for tid, t in todo_items.items():
                        if t.get("status") == "completed":
                            icon = "[#98971f]✓[/#98971f]"
                        elif t.get("status") == "in_progress":
                            icon = "[#83a598]◐[/#83a598]"
                        else:
                            icon = "[#928374]○[/#928374]"
                        content = t.get("content", "")[:30]
                        lines.append(f"  {icon} {content}")

        if self.agent:
            if hasattr(self.agent, '_mcp_available'):
                mcp_available = self.agent._mcp_available
                if mcp_available:
                    lines.append(Text("─ MCP ─", style="#d79921"))
                    for name, enabled in list(mcp_available.items())[:15]:
                        dot = Text("●", style="#98971f") if enabled else Text("○", style="#928374")
                        lines.append(Text("  ") + dot + Text(f" {name}"))

            if hasattr(self.agent, 'lsp_manager') and self.agent.lsp_manager:
                lsp_servers = list(self.agent.lsp_manager._servers.keys()) if hasattr(self.agent.lsp_manager, '_servers') else []
                if lsp_servers:
                    lines.append(Text("─ LSP ─", style="#d79921"))
                    for server_id in lsp_servers[:10]:
                        lines.append(f"  {server_id}")
                    if len(lsp_servers) > 10:
                        lines.append(f"  ... and {len(lsp_servers) - 10} more")

            if hasattr(self.agent, 'modified_files') and self.agent.modified_files:
                try:
                    self.agent.modified_files.refresh_from_git()
                    modified = self.agent.modified_files.get_modified_files()
                    if modified:
                        lines.append(Text("─ Modified ─", style="#d79921"))
                        for f in modified[:15]:
                            adds = Text(f"+{f.additions}", style="#98971f") if f.additions > 0 else Text("")
                            dels = Text(f"-{f.deletions}", style="#fb4934") if f.deletions > 0 else Text("")
                            parts = []
                            if adds:
                                parts.append(adds)
                            if dels:
                                parts.append(dels)
                            stats = Text(" ") + adds + dels if parts else Text("")
                            lines.append(Text("  ") + Text(f.relative_path, style="#83a598") + stats)
                        if len(modified) > 15:
                            lines.append(f"  ... and {len(modified) - 15} more")
                except Exception:
                    pass

        try:
            sidebar_body = self.query_one("#sidebar-body", RichLog)
            sidebar_body.clear()
            for line in lines:
                if isinstance(line, Text):
                    sidebar_body.write(line)
                else:
                    sidebar_body.write(Text(line))
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

    def _update_stream_display(self) -> None:
        """Flush accumulated stream tokens to display."""
        if not hasattr(self, '_stream_buffer') or not self._stream_buffer:
            return
        
        output_area = self.query_one("#output-area", RichLog)
        # Remove the timer so it can be rescheduled
        if hasattr(self, '_stream_timer') and self._stream_timer:
            self._stream_timer.stop()
            self._stream_timer = None
        
        # Write the accumulated tokens
        if self._stream_buffer:
            output_area.write(self._stream_buffer)
            self._stream_buffer = ""

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
    
    def _get_history_file(self):
        """Get history file path."""
        import os
        from pathlib import Path
        xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg_data) / "nanocode" / "storage" / "tui_history.json"
    
    def _load_input_history(self):
        """Load input history from file."""
        history_file = self._history_file
        if history_file.exists():
            import json
            try:
                data = json.loads(history_file.read_text())
                self._input_history = data.get("history", [])
                self._history_index = len(self._input_history) - 1 if self._input_history else -1
            except Exception:
                pass
    
    def _save_input_history(self):
        """Save input history to file."""
        import json
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        self._history_file.write_text(json.dumps({"history": self._input_history}, indent=2))
    
    def _print_logo(self):
        """Print simple banner."""
        self._print_line("NanoCode", Style.TEXT_INFO_BOLD)
    
    def _print_line(self, text: str, style: str = ""):
        """Print a line with optional style."""
        output = self.query_one("#output-area")
        
        # Convert ANSI style to simple Rich style name
        if style == Style.THINKING:
            # Split: "Thinking:" gets yellow italic, rest gets normal
            prefix = ""
            rest = text
            if "| Thinking:" in text:
                parts = text.split("| Thinking:", 1)
                prefix = parts[0] + "| Thinking:"
                rest = parts[1] if len(parts) > 1 else ""
            
            from rich.text import Text as RichText
            if prefix and rest:
                full_text = RichText()
                full_text.append(prefix + " ", style=f"{RichColor.YELLOW.value} italic")
                full_text.append(rest, style=RichColor.FG.value)
            elif prefix:
                full_text = RichText(prefix, style=f"{RichColor.YELLOW.value} italic")
            else:
                full_text = RichText.from_markup(text)
            
            output.write(full_text)
            output._lines.append(text)
            return
        
        output.add_line(text, style)
    
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
        sys.stderr.write("DEBUG: action_show_cli_commands called\n")
        sys.stderr.write(f"CLI_COMMANDS = {self.CLI_COMMANDS}\n")
        sys.stderr.flush()
        output = self.query_one("#output-area")
        output.add_line("\n=== Available Commands ===")
        for cmd, desc in self.CLI_COMMANDS:
            output.add_line(f"  {cmd:<20} {desc}")
        output.add_line("\nPress Ctrl+P to show this menu")
    
    @work()
    async def action_show_command_palette(self):
        """Show the command palette popup."""
        screen = CommandPaletteScreen(self.CLI_COMMANDS)
        result = await self.push_screen_wait(screen)
        if result:
            input_widget = self.query_one("#input", Input)
            input_widget.value = result
            input_widget.focus()

    @work()
    async def action_model_explorer(self):
        """Show model explorer to select a new model."""
        screen = ModelExplorerScreen()
        result = await self.push_screen_wait(screen)
        if result:
            full_id, provider = result
            # Save to config.yaml
            try:
                import yaml
                config_path = "config.yaml"
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                config["llm"]["default_provider"] = provider
                # Extract model name from full_id (e.g., "tencent/hy3" -> "hy3")
                model_name = full_id.split("/")[-1]
                if provider:
                    config["llm"]["providers"][provider] = config["llm"]["providers"].get(provider, {})
                    config["llm"]["providers"][provider]["model"] = model_name
                with open(config_path, "w") as f:
                    yaml.dump(config, f, default_flow_style=False)
                self.notify(f"Model set to {full_id}", severity="success")
            except Exception as e:
                self.notify(f"Failed to save: {e}", severity="error")

    @work()
    async def action_message_actions(self):
        """Show message actions for the last user message."""
        output = self.query_one("#output-area", OutputArea)
        if output._user_messages:
            # Get the last user message
            index, text = output._user_messages[-1]
            result = await self.push_screen_wait(MessageActionScreen(text, index))
            if result:
                action, msg_text, msg_index = result
                if action == "copy":
                    import pyperclip
                    pyperclip.copy(msg_text)
                    self.notify("Copied to clipboard", severity="info")
                elif action == "fork":
                    self._input_history.append(msg_text)
                    self._save_input_history()
                    input_widget = self.query_one("#input", Input)
                    input_widget.value = msg_text
                    input_widget.focus()
                elif action == "revert":
                    # Revert state via agent's context manager
                    if self.agent and hasattr(self.agent, "context_manager"):
                        from nanocode.message_actions import MessageActionManager

                        ctx = self.agent.context_manager
                        if hasattr(ctx, "_messages"):
                            msg_mgr = MessageActionManager(ctx._messages)
                            result = msg_mgr.revert_with_snapshot(msg_index)
                            if result.get("success"):
                                # Update context
                                ctx._messages = msg_mgr._messages
                                self._input_history = self._input_history[:msg_index + 1]
                                self._history_index = len(self._input_history)
                                # Clear output by clearing the RichLog directly
                                try:
                                    output = self.query_one("#output-area", RichLog)
                                    output.clear()
                                    # Force refresh of the screen
                                    self.screen.refresh()
                                except Exception as e:
                                    print(f"Clear error: {e}")
                                self._show_welcome()
                                self.notify(f"Reverted to message {msg_index}", severity="success")
                            else:
                                self.notify(f"Revert failed: {result.get('error')}", severity="error")
                        else:
                            self.notify("Context manager not available", severity="error")
                    else:
                        self.notify("No agent - cannot revert", severity="error")
        else:
            self.notify("No user messages yet", severity="info")
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes."""
        pass
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        text = event.value.strip()
        if text:
            self._input_history.append(text)
            self._history_index = len(self._input_history)
            self._save_input_history()
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
                import datetime
                import io
                import logging
                import sys
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
                    # Streaming buffer for real-time display
                    self._stream_buffer = ""
                    self._stream_timer = None

                    # Define callbacks for real-time updates
                    def on_token(token: str):
                        """Called for each token from LLM."""
                        self._stream_buffer += token
                        # Update display every 100ms (if not already scheduled)
                        if self._stream_timer is None:
                            self._stream_timer = self.set_interval(
                                0.1, self._update_stream_display
                            )

                    def on_tool_start(tool_name, args):
                        """Called when a tool starts execution."""
                        args_str = str(args)[:100]  # Truncate long args
                        self._print_line(f"▶ {tool_name}({args_str})...", Style.TOOL_MESSAGE)

                    def on_tool_complete(tool_name, result):
                        """Called when a tool completes."""
                        # Handle both string and dict results
                        if isinstance(result, dict):
                            # Convert dict to string preview
                            result_str = str(result) if result else ""
                        else:
                            result_str = str(result) if result else ""
                        # Show a summary (first 200 chars)
                        preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
                        self._print_line(f"✓ {tool_name}: {preview}", Style.TOOL_MESSAGE)

                    result = await self.agent.process_input(
                        text,
                        show_thinking=True,
                        show_messages=False,
                        on_tool_start=on_tool_start,
                        on_tool_complete=on_tool_complete,
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
            
            # Clean up streaming
            if hasattr(self, '_stream_timer') and self._stream_timer:
                self._stream_timer.stop()
                self._stream_timer = None
            # Flush any remaining stream buffer
            if hasattr(self, '_stream_buffer') and self._stream_buffer:
                output_area = self.query_one("#output-area", RichLog)
                output_area.write(self._stream_buffer)
                self._stream_buffer = ""

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
            from rich.console import Console
            c = Console()
            c.print("[cyan]░██████╗ ███████╗████████╗██████╗  ██████╗ ██████╗  █████╗ ██████╗ ██████╗ [/cyan]")
            c.print("[cyan]██╔════╝ ██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗[/cyan]")
            c.print("[cyan]██║  ███╗█████╗     ██║   ██████╔╝██║   ██║██████╔╝███████║██████╔╝███████║[/cyan]")
            c.print("[cyan]██║   ██║██╔══╝     ██║   ██╔══██╗██║   ██║██╔══██╗██╔══██║██╔══██╗██╔══██║[/cyan]")
            c.print("[cyan]╚██████╔╝███████╗   ██║   ██║  ██║╚██████╔╝██████╔╝██║  ██║██║  ██║██║  ██║[/cyan]")
            c.print("[cyan] ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝[/cyan]")
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
