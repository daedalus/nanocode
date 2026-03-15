"""NCurses GUI interface for the autonomous agent."""

import curses
import asyncio
from typing import Optional, Callable
from dataclasses import dataclass
from datetime import datetime

from agent_smith.cli.commands import get_command_help, find_command


@dataclass
class GUIColors:
    """Color pairs for ncurses."""

    BLACK = 0
    BLUE = 1
    GREEN = 2
    CYAN = 3
    RED = 4
    MAGENTA = 5
    WHITE = 7
    YELLOW = 6

    @classmethod
    def init(cls, stdscr):
        """Initialize color pairs."""
        curses.start_color()
        curses.use_default_colors()

        for i in range(1, 8):
            curses.init_pair(i, i, -1)

        curses.init_pair(10, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(11, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(12, curses.COLOR_BLACK, curses.COLOR_RED)
        curses.init_pair(13, curses.COLOR_BLACK, curses.COLOR_YELLOW)


class Message:
    """A message in the chat."""

    def __init__(self, role: str, content: str, timestamp: datetime = None):
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.now()


class Panel:
    """Base panel class."""

    def __init__(self, parent, y: int, x: int, height: int, width: int):
        self.parent = parent
        self.y = y
        self.x = x
        self.height = height
        self.width = width
        self.win = None
        self.visible = True

    def create(self):
        """Create the ncurses window."""
        self.win = curses.newwin(self.height, self.width, self.y, self.x)
        self.win.keypad(True)
        return self.win

    def clear(self):
        """Clear the panel."""
        if self.win:
            self.win.clear()

    def refresh(self):
        """Refresh the panel."""
        if self.win:
            self.win.refresh()

    def draw_border(self, color_pair: int = 0):
        """Draw border around panel."""
        if self.win:
            self.win.attron(curses.color_pair(color_pair))
            self.win.border()
            self.win.attroff(curses.color_pair(color_pair))


class TitleBar(Panel):
    """Top title bar."""

    def __init__(self, parent, y: int, x: int, width: int, title: str = "Autonomous Agent"):
        super().__init__(parent, y, x, 1, width)
        self.title = title

    def draw(self, state: str = "IDLE"):
        """Draw the title bar."""
        if not self.win:
            return

        self.win.clear()

        status_colors = {
            "IDLE": 2,
            "PLANNING": 6,
            "EXECUTING": 3,
            "WAITING": 5,
            "COMPLETE": 2,
            "ERROR": 4,
        }
        color = status_colors.get(state, 0)

        self.win.attron(curses.color_pair(10))
        self.win.addstr(0, 0, " " * (self.width - 1))
        self.win.attroff(curses.color_pair(10))

        title = f" {self.title} "
        self.win.addstr(0, 1, title, curses.color_pair(11) | curses.A_BOLD)

        state_str = f" [{state}] "
        self.win.addstr(
            0, self.width - len(state_str) - 1, state_str, curses.color_pair(color) | curses.A_BOLD
        )

        self.refresh()


class Sidebar(Panel):
    """Left sidebar with tools and info."""

    def __init__(self, parent, y: int, x: int, height: int, width: int):
        super().__init__(parent, y, x, height, width)
        self.selected_item = 0
        self.items = []
        self.item_type = "tools"

    def set_items(self, items: list[str], item_type: str = "tools"):
        """Set sidebar items."""
        self.items = items
        self.item_type = item_type
        self.selected_item = 0

    def draw(self):
        """Draw the sidebar."""
        if not self.win:
            return

        self.win.clear()

        header = f" {self.item_type.upper()} "
        self.win.addstr(0, 1, header, curses.color_pair(10) | curses.A_BOLD)

        self.win.addstr(1, 0, "─" * (self.width - 1), curses.color_pair(0))

        for i, item in enumerate(self.items[: self.height - 3]):
            y_pos = i + 2
            if y_pos >= self.height - 1:
                break

            if i == self.selected_item:
                self.win.addstr(y_pos, 0, "▶ ", curses.color_pair(3) | curses.A_BOLD)
                self.win.addstr(y_pos, 2, item[: self.width - 3], curses.color_pair(3))
            else:
                self.win.addstr(y_pos, 2, "  " + item[: self.width - 4], curses.color_pair(0))

        self.draw_border(0)
        self.refresh()

    def handle_input(self, key: int) -> Optional[str]:
        """Handle keyboard input."""
        if key == curses.KEY_UP and self.selected_item > 0:
            self.selected_item -= 1
            return None
        elif key == curses.KEY_DOWN and self.selected_item < len(self.items) - 1:
            self.selected_item += 1
            return None
        elif key in (curses.KEY_ENTER, 10, 13) and self.items:
            return self.items[self.selected_item]
        return None


class ChatPanel(Panel):
    """Main chat area."""

    def __init__(self, parent, y: int, x: int, height: int, width: int):
        super().__init__(parent, y, x, height, width)
        self.messages: list[Message] = []
        self.scroll_offset = 0

    def add_message(self, role: str, content: str):
        """Add a message to the chat."""
        self.messages.append(Message(role, content))

        if len(self.messages) > self.height - 4:
            self.scroll_offset = len(self.messages) - self.height + 4

    def draw(self):
        """Draw the chat panel."""
        if not self.win:
            return

        self.win.clear()

        visible_messages = self.messages[self.scroll_offset : self.scroll_offset + self.height - 3]

        role_colors = {
            "user": 3,
            "assistant": 2,
            "system": 6,
            "tool": 5,
        }

        y = 0
        for msg in visible_messages:
            if y >= self.height - 2:
                break

            color = role_colors.get(msg.role, 0)

            prefix = f"[{msg.role.upper()}]"
            self.win.addstr(y, 1, prefix, curses.color_pair(color) | curses.A_BOLD)

            content_lines = msg.content.split("\n")
            for line in content_lines[: self.height - y - 2]:
                if len(line) > self.width - 4:
                    line = line[: self.width - 7] + "..."
                y += 1
                if y >= self.height - 2:
                    break
                self.win.addstr(y, 1, line[: self.width - 4], curses.color_pair(0))

            y += 1

        self.draw_border(0)
        self.refresh()

    def handle_input(self, key: int) -> Optional[str]:
        """Handle keyboard input."""
        if key == curses.KEY_PPAGE and self.scroll_offset > 0:
            self.scroll_offset = max(0, self.scroll_offset - 10)
        elif key == curses.KEY_NPAGE and self.scroll_offset < len(self.messages) - 1:
            self.scroll_offset = min(len(self.messages) - 1, self.scroll_offset + 10)
        return None


class InputPanel(Panel):
    """Bottom input area."""

    def __init__(self, parent, y: int, x: int, height: int, width: int):
        super().__init__(parent, y, x, height, width)
        self.input_text = ""
        self.cursor_pos = 0
        self.history: list[str] = []
        self.history_index = -1

    def draw(self):
        """Draw the input panel."""
        if not self.win:
            return

        self.win.clear()

        prompt = "➜ "
        self.win.addstr(0, 0, prompt, curses.color_pair(3) | curses.A_BOLD)

        display_text = self.input_text[: self.width - len(prompt) - 2]
        self.win.addstr(0, len(prompt), display_text, curses.color_pair(0))

        cursor_x = len(prompt) + min(self.cursor_pos, len(display_text))
        self.win.move(0, cursor_x)
        self.win.refresh()

    def handle_input(self, key: int) -> Optional[str]:
        """Handle keyboard input."""
        if key in (curses.KEY_ENTER, 10, 13):
            text = self.input_text.strip()
            self.input_text = ""
            self.cursor_pos = 0
            return text

        elif key in (curses.KEY_BACKSPACE, 127):
            if self.cursor_pos > 0:
                self.input_text = (
                    self.input_text[: self.cursor_pos - 1] + self.input_text[self.cursor_pos :]
                )
                self.cursor_pos -= 1

        elif key == curses.KEY_DC:
            if self.cursor_pos < len(self.input_text):
                self.input_text = (
                    self.input_text[: self.cursor_pos] + self.input_text[self.cursor_pos + 1 :]
                )

        elif key == curses.KEY_LEFT and self.cursor_pos > 0:
            self.cursor_pos -= 1

        elif key == curses.KEY_RIGHT and self.cursor_pos < len(self.input_text):
            self.cursor_pos += 1

        elif key == curses.KEY_HOME:
            self.cursor_pos = 0

        elif key == curses.KEY_END:
            self.cursor_pos = len(self.input_text)

        elif key == curses.KEY_UP:
            if self.history and self.history_index < len(self.history) - 1:
                self.history_index += 1
                self.input_text = self.history[-(self.history_index + 1)]
                self.cursor_pos = len(self.input_text)

        elif key == curses.KEY_DOWN:
            if self.history_index > 0:
                self.history_index -= 1
                self.input_text = self.history[-(self.history_index + 1)]
                self.cursor_pos = len(self.input_text)
            elif self.history_index == 0:
                self.history_index = -1
                self.input_text = ""
                self.cursor_pos = 0

        elif 32 <= key <= 126:
            char = chr(key)
            self.input_text = (
                self.input_text[: self.cursor_pos] + char + self.input_text[self.cursor_pos :]
            )
            self.cursor_pos += 1

        return None

    def add_to_history(self, text: str):
        """Add text to command history."""
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
            if len(self.history) > 100:
                self.history.pop(0)
        self.history_index = -1


class StatusBar(Panel):
    """Bottom status bar."""

    def __init__(self, parent, y: int, x: int, width: int):
        super().__init__(parent, y, x, 1, width)

    def draw(self, token_usage: dict = None, model: str = None, provider: str = None):
        """Draw the status bar."""
        if not self.win:
            return

        self.win.clear()

        self.win.addstr(0, 0, " ", curses.color_pair(10))

        parts = []

        if token_usage:
            tokens = token_usage.get("current_tokens", 0)
            max_ctx = token_usage.get("context_limit", 0)
            ctx_pct = token_usage.get("context_usage_percent", 0)
            parts.append(f"Tokens: {tokens:,}")
            parts.append(f"Context: {ctx_pct:.1f}%")
            if max_ctx:
                parts.append(f"Max: {max_ctx:,}")

        if model:
            parts.append(f"Model: {model}")

        if provider:
            parts.append(f"Provider: {provider}")

        status_text = " | ".join(parts)
        self.win.addstr(0, 1, status_text, curses.color_pair(0))

        help_text = "↑↓ Navigate | Enter Send | Ctrl+C Quit | Ctrl+L Clear"
        self.win.addstr(0, self.width - len(help_text) - 1, help_text, curses.color_pair(0))

        self.refresh()


class NcursesGUI:
    """Main ncurses GUI application."""

    def __init__(self, agent, on_message: Callable = None):
        self.agent = agent
        self.on_message = on_message
        self.panels = {}
        self.active_panel = "chat"
        self.running = False
        self.show_thinking = False

    def init_panels(self, stdscr):
        """Initialize all panels."""
        height, width = stdscr.getmaxyx()

        GUIColors.init(stdscr)

        title_bar = TitleBar(stdscr, 0, 0, width, "Autonomous Agent")
        title_bar.create()
        self.panels["title"] = title_bar

        sidebar_width = 0
        sidebar = Sidebar(stdscr, 1, 0, height - 2, sidebar_width)
        sidebar.visible = False
        sidebar.create()
        self.panels["sidebar"] = sidebar

        chat_x = 0
        chat_height = height - 4
        chat = ChatPanel(stdscr, 1, chat_x, chat_height, width - 1)
        chat.create()
        self.panels["chat"] = chat

        input_height = 1
        input_panel = InputPanel(stdscr, height - 2, 0, input_height, width - 1)
        input_panel.create()
        self.panels["input"] = input_panel

        status_bar = StatusBar(stdscr, height - 1, 0, width)
        status_bar.create()
        self.panels["status"] = status_bar

    def update_tools(self, tools: list[str]):
        """Update sidebar with tools."""
        if "sidebar" in self.panels:
            self.panels["sidebar"].set_items(tools, "TOOLS")

    def add_chat_message(self, role: str, content: str):
        """Add a message to chat."""
        if "chat" in self.panels:
            self.panels["chat"].add_message(role, content)

    def get_token_usage(self) -> dict:
        """Get token usage from agent."""
        if hasattr(self.agent, "context_manager"):
            return self.agent.context_manager.get_token_usage()
        return {}

    def get_model_info(self) -> tuple:
        """Get model and provider info from agent."""
        model = None
        provider = None

        if hasattr(self.agent, "llm") and self.agent.llm:
            model = getattr(self.agent.llm, "model", None)
            provider = getattr(self.agent.llm, "provider", None)

        if hasattr(self.agent, "config") and self.agent.config:
            config = self.agent.config
            if not provider:
                provider = config.get("default_provider")
            if not model:
                model = config.get("default_model")

        return model, provider

    def draw(self, state: str = "IDLE"):
        """Draw all panels."""
        for name, panel in self.panels.items():
            if not panel.visible:
                continue

            if name == "title":
                panel.draw(state)
            elif name == "sidebar":
                panel.draw()
            elif name == "chat":
                panel.draw()
            elif name == "input":
                panel.draw()
            elif name == "status":
                token_usage = self.get_token_usage()
                model, provider = self.get_model_info()
                panel.draw(token_usage, model, provider)

    def run(self, stdscr):
        """Run the ncurses application."""
        try:
            curses.curs_set(1)
        except curses.error:
            pass

        try:
            curses.cbreak()
        except curses.error:
            try:
                curses.raw()
            except curses.error:
                pass

        try:
            curses.noecho()
        except curses.error:
            pass

        try:
            stdscr.keypad(True)
        except curses.error:
            pass

        stdscr.clear()

        self.init_panels(stdscr)

        tools = [t.name for t in self.agent.tool_registry.list_tools()]
        self.update_tools(tools)

        self.add_chat_message("system", "Welcome to Autonomous Agent! Type your message below.")

        self.draw("IDLE")
        self.running = True

        while self.running:
            try:
                state = "IDLE"
                if hasattr(self.agent, "state"):
                    state = self.agent.state.state.name

                self.draw(state)

                if "input" in self.panels:
                    key = self.panels["input"].win.getch()
                else:
                    key = stdscr.getch()

                if key == 3:
                    break

                if key == 12:
                    stdscr.clear()
                    self.init_panels(stdscr)
                    continue

                if self.active_panel == "chat":
                    result = self.panels["chat"].handle_input(key)
                elif self.active_panel == "sidebar":
                    result = self.panels["sidebar"].handle_input(key)
                elif self.active_panel == "input":
                    result = self.panels["input"].handle_input(key)

                if result and self.active_panel == "input" and result.strip():
                    self.panels["input"].add_to_history(result)

                    if result.startswith("/"):
                        response = self._handle_command(result)
                        if response:
                            self.add_chat_message("system", response)
                    else:
                        self.add_chat_message("user", result)
                        if self.on_message:
                            asyncio.ensure_future(self._handle_message(result))

                    self.panels["input"].input_text = ""
                    self.panels["input"].cursor_pos = 0

                elif result and self.active_panel == "sidebar":
                    self.add_chat_message("system", f"Selected: {result}")

                if key == 9:
                    self.active_panel = {"chat": "sidebar", "sidebar": "input", "input": "chat"}[
                        self.active_panel
                    ]

            except curses.error:
                pass
            except Exception as e:
                self.add_chat_message("system", f"Error: {str(e)}")

    def _handle_command(self, command: str) -> Optional[str]:
        """Handle special commands starting with /."""
        parts = command.split()
        cmd = parts[0].lower()

        if cmd in ("/exit", "/quit", "/q"):
            self.running = False
            return "Goodbye!"

        if cmd in ("/help", "/h"):
            return get_command_help()

        elif cmd in ("/clear", "/c"):
            self.panels["chat"].messages = []
            return "Chat cleared."

        elif cmd == "/history":
            history = self.panels["input"].history
            if history:
                lines = ["Command history:"]
                for i, item in enumerate(reversed(history[-20:]), 1):
                    lines.append(f"  {i}. {item}")
                return "\n".join(lines)
            return "No command history."

        elif cmd == "/tools":
            tools = [t.name for t in self.agent.tool_registry.list_tools()]
            return (
                f"Available tools ({len(tools)}):\n"
                + ", ".join(tools[:30])
                + ("..." if len(tools) > 30 else "")
            )

        elif cmd == "/provider":
            model, provider = self.get_model_info()
            return f"Provider: {provider or 'unknown'}\nModel: {model or 'unknown'}"

        elif cmd == "/checkpoint":
            if hasattr(self.agent, "planning") and hasattr(self.agent.planning, "list_checkpoints"):
                checkpoints = self.agent.planning.list_checkpoints()
                if checkpoints:
                    lines = ["Checkpoints:"]
                    for cp in checkpoints[-10:]:
                        lines.append(f"  {cp.get('id', 'N/A')} - {cp.get('description', '')[:40]}")
                    return "\n".join(lines)
            return "No checkpoints available."

        elif cmd == "/skills":
            if hasattr(self.agent, "skills"):
                skills = (
                    list(self.agent.skills.keys()) if hasattr(self.agent.skills, "keys") else []
                )
                return f"Available skills: {', '.join(skills) if skills else 'None'}"
            return "Skills not available."

        elif cmd == "/snapshot":
            if hasattr(self.agent, "snapshot"):
                import uuid

                snapshot_id = str(uuid.uuid4())[:8]
                return f"Snapshot created: {snapshot_id}"
            return "Snapshot not available."

        elif cmd == "/snapshots":
            return "No snapshots available."

        elif cmd == "/trace":
            if hasattr(self.agent, "last_traceback"):
                return self.agent.last_traceback
            return "No trace available."

        elif cmd == "/debug":
            if hasattr(self.agent, "toggle_debug"):
                self.agent.toggle_debug()
                return "Debug logging toggled."
            return "Debug not available."

        elif cmd == "/show_thinking":
            self.show_thinking = not self.show_thinking
            return f"Show thinking: {'enabled' if self.show_thinking else 'disabled'}"

        elif cmd == "/compact":
            if hasattr(self.agent, "context_manager") and hasattr(
                self.agent.context_manager, "compact"
            ):
                return "Compacting context..."
            return "Compact not available."

        elif cmd.startswith("/plan "):
            task = command[6:]
            asyncio.ensure_future(self._execute_task(task))
            return f"Planning: {task[:50]}..."

        elif cmd.startswith("/resume "):
            checkpoint_id = command[8:]
            asyncio.ensure_future(self._resume_checkpoint(checkpoint_id))
            return f"Resuming checkpoint: {checkpoint_id}"

        elif cmd.startswith("/revert "):
            snapshot_hash = command[8:].strip()
            asyncio.ensure_future(self._revert_snapshot(snapshot_hash))
            return f"Reverting to snapshot: {snapshot_hash[:8]}..."

        if find_command(command) is None:
            return f"Unknown command: {cmd}. Type /help for available commands."
        return f"Unknown command: {cmd}"

    async def _handle_message(self, message: str):
        """Handle incoming message asynchronously."""
        try:
            self.panels["title"].state = "EXECUTING"

            response = await self.agent.process_input(message, show_thinking=self.show_thinking)

            self.add_chat_message("assistant", response)
            self.panels["title"].state = "COMPLETE"

            await self._check_and_compact_context()

        except Exception as e:
            self.add_chat_message("system", f"Error: {str(e)}")
            self.panels["title"].state = "ERROR"

    async def _check_and_compact_context(self):
        """Check and compact context if needed."""
        if hasattr(self.agent, "context_manager"):
            ctx = self.agent.context_manager
            usage = ctx.get_token_usage()
            pct = usage.get("context_usage_percent", 0)
            threshold = (
                ctx.config.get("auto_compact_threshold", 85) if hasattr(ctx, "config") else 85
            )
            if pct >= threshold and hasattr(ctx, "compact"):
                self.add_chat_message("system", f"Auto-compacting context ({pct:.1f}% usage)...")
                await ctx.compact()

    async def _execute_task(self, task: str):
        """Execute a task with planning."""
        self.add_chat_message("system", f"Planning: {task[:50]}...")
        try:
            result = await self.agent.execute_task(task)
            if result.get("success"):
                self.add_chat_message(
                    "assistant", f"Task completed: {result.get('summary', 'Done')}"
                )
            else:
                self.add_chat_message(
                    "system", f"Task failed: {result.get('error', 'Unknown error')}"
                )
        except Exception as e:
            self.add_chat_message("system", f"Error: {str(e)}")

    async def _resume_checkpoint(self, checkpoint_id: str):
        """Resume from a checkpoint."""
        self.add_chat_message("system", f"Resuming checkpoint: {checkpoint_id}")
        try:
            result = await self.agent.resume_from_checkpoint(checkpoint_id)
            if result.get("success"):
                self.add_chat_message("system", "Checkpoint resumed successfully")
            else:
                self.add_chat_message("system", f"Failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            self.add_chat_message("system", f"Error: {str(e)}")

    async def _revert_snapshot(self, snapshot_hash: str):
        """Revert to a snapshot."""
        self.add_chat_message("system", f"Reverting to snapshot: {snapshot_hash[:8]}...")
        try:
            if hasattr(self.agent, "snapshot"):
                result = await self.agent.snapshot.revert(snapshot_hash)
                self.add_chat_message("system", f"Reverted to {snapshot_hash[:8]}")
            else:
                self.add_chat_message("system", "Snapshot not available")
        except Exception as e:
            self.add_chat_message("system", f"Error: {str(e)}")

    def start(self):
        """Start the GUI."""
        curses.wrapper(self.run)


class GUIRunner:
    """Helper to run GUI with async agent."""

    def __init__(self, agent):
        self.agent = agent
        self.gui = NcursesGUI(agent, self.on_message)

    async def handle_message(self, message: str):
        """Handle a message."""
        response = await self.agent.process_input(message)
        self.gui.add_chat_message("assistant", response)

    def run(self):
        """Run the GUI."""
        self.gui.on_message = lambda msg: asyncio.create_task(self.handle_message(msg))
        self.gui.run(curses.wrapper)
