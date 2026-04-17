"""NanoCode TUI App - A Textual-based terminal UI."""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, TextArea, RichLog, Button
from textual.binding import Binding
from textual import work

from typing import Optional
import asyncio


class PermissionRequest:
    """Minimal permission request for TUI."""
    def __init__(self, id: str, agent_name: str, tool_name: str, arguments: dict):
        self.id = id
        self.agent_name = agent_name
        self.tool_name = tool_name
        self.arguments = arguments


class StatusBar(Static):
    """Status bar showing agent state."""
    
    def __init__(self, status: str = "idle", agent_name: str = ""):
        super().__init__()
        self._status = status
        self._agent_name = agent_name
    
    def compose(self) -> ComposeResult:
        yield Static(self._get_status_text(), id="status")
    
    def _get_status_text(self) -> str:
        icons = {
            "idle": "○",
            "planning": "◔",
            "executing": "▶",
            "waiting": "◉",
            "complete": "✓",
            "error": "✗",
        }
        icon = icons.get(self._status, "○")
        return f" {icon} [{self._status.upper()}] {self._agent_name}"
    
    def update_status(self, status: str, agent_name: str = ""):
        self._status = status
        self._agent_name = agent_name
        self.query_one("#status", Static).update(self._get_status_text())


class OutputLog(RichLog):
    """Log viewer for agent output."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auto_scroll = True
    
    def add_message(self, role: str, content: str, style: str = ""):
        """Add a message to the log."""
        role_styles = {
            "user": "cyan",
            "assistant": "blue bold",
            "system": "yellow",
            "tool": "magenta",
            "error": "red bold",
            "success": "green",
        }
        color = role_styles.get(role, "white")
        self.write(f"[{color}][{role.upper()}][/] {content}")


class InputBar(Static):
    """Input bar with text area and send button."""
    
    def __init__(self):
        super().__init__()
        self._pending_input = None
    
    def compose(self) -> ComposeResult:
        with Horizontal(id="input-container"):
            yield TextArea(id="input", placeholder="Enter your task...", border="none")
            yield Button("Send", id="send-btn", variant="primary")
    
    def focus(self):
        self.query_one("#input", TextArea).focus()
    
    async def get_input(self) -> Optional[str]:
        """Get input from the text area."""
        text_area = self.query_one("#input", TextArea)
        return text_area.text
    
    def clear(self):
        self.query_one("#input", TextArea).text = ""


class PermissionDialog(Static):
    """Permission request dialog."""
    
    def __init__(self, request_data: dict):
        super().__init__()
        self.request_data = request_data
    
    def compose(self) -> ComposeResult:
        yield Static(f"Permission Request", id="perm-title")
        yield Static(f"Agent: {self.request_data.get('agent_name', 'unknown')}", id="perm-agent")
        yield Static(f"Tool: {self.request_data.get('tool_name', 'unknown')}", id="perm-tool")
        with Horizontal(id="perm-buttons"):
            yield Button("Allow", id="perm-allow", variant="success")
            yield Button("Deny", id="perm-deny", variant="error")
            yield Button("Always", id="perm-always", variant="primary")


class NanoCodeApp(App):
    """Main TUI application for NanoCode."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #main-container {
        height: 100%;
    }
    
    #output-log {
        height: 1fr;
        border: solid $primary;
        margin: 1;
    }
    
    #input-container {
        height: auto;
        padding: 1;
    }
    
    #input {
        height: 3;
    }
    
    #send-btn {
        height: 3;
    }
    
    #status-bar {
        height: auto;
        background: $surface-darken-1;
        padding: 0 1;
    }
    
    #status {
        text-style: normal;
    }
    
    .permission-dialog {
        background: $panel;
        border: solid $accent;
        padding: 2;
        width: 60%;
    }
    
    #perm-title {
        text-style: bold;
        margin-bottom: 1;
    }
    """
    
    BINDINGS = [
        Binding("enter", "send", "Send", show=False),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("ctrl+l", "clear_output", "Clear Output"),
        Binding("escape", "quit", "Quit", show=True),
    ]
    
    def __init__(self, agent=None, show_thinking: bool = True):
        super().__init__()
        self.agent = agent
        self.show_thinking = show_thinking
        self._permission_callback = None
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-container"):
            yield OutputLog(id="output-log")
            with Horizontal(id="input-container"):
                yield TextArea(id="input", placeholder="Enter your task...")
                yield Button("Send", id="send-btn", variant="primary")
        yield Static("", id="status-bar")
        yield Footer()
    
    def on_mount(self) -> None:
        """Initialize on mount."""
        self.query_one("#input", TextArea).focus()
        self._show_welcome()
        
        # Set up permission callback if agent exists
        if self.agent:
            self._setup_permission_callback()
    
    def _show_welcome(self):
        """Show welcome message."""
        log = self.query_one("#output-log", OutputLog)
        log.add_message("system", "╔═══════════════════════════════════════════════════════════╗")
        log.add_message("system", "║              NanoCode TUI - Ready                        ║")
        log.add_message("system", "║  Type your task or 'help' for commands                     ║")
        log.add_message("system", "╚═══════════════════════════════════════════════════════════╝")
    
    def _setup_permission_callback(self):
        """Set up permission callback for the agent."""
        from nanocode.agents.permission import (
            PermissionCallback,
            PermissionReply,
            PermissionReplyType,
            PermissionRequest,
        )
        
        async def permission_callback(request: PermissionRequest) -> PermissionReply:
            """Handle permission requests in TUI."""
            self._show_permission_dialog(request)
            # For now, default allow - user interaction via dialog later
            return PermissionReply(request_id=request.id, reply=PermissionReplyType.ALWAYS)
        
        self.agent.permission_handler.set_callback(permission_callback)
    
    def _show_permission_dialog(self, request: PermissionRequest):
        """Show permission request dialog."""
        log = self.query_one("#output-log", OutputLog)
        log.add_message("system", f"┌─[PERMISSION REQUEST]")
        log.add_message("system", f"  Agent: {request.agent_name}")
        log.add_message("system", f"  Tool: {request.tool_name}")
        if request.arguments:
            for k, v in request.arguments.items():
                v_str = str(v)
                if len(v_str) > 50:
                    v_str = v_str[:50] + "..."
                log.add_message("system", f"    {k}: {v_str}")
        log.add_message("system", f"  ➜ Allow? (y/n/a=always)")
    
    def action_send(self):
        """Handle send action."""
        input_widget = self.query_one("#input", TextArea)
        text = input_widget.text.strip()
        if text:
            input_widget.text = ""
            self._process_input(text)
    
    def action_clear_output(self):
        """Clear output log."""
        log = self.query_one("#output-log", OutputLog)
        log.clear()
    
    def action_cancel(self):
        """Cancel current action."""
        # TODO: Implement cancellation
        pass
    
    @work(exclusive=True)
    async def _process_input(self, text: str):
        """Process user input through the agent."""
        log = self.query_one("#output-log", OutputLog)
        status = self.query_one("#status-bar", Static)
        
        log.add_message("user", text)
        status.update("Waiting for response...")
        
        try:
            if self.agent:
                result = await self.agent.process_input(
                    text, show_thinking=self.show_thinking
                )
                log.add_message("assistant", str(result))
            else:
                log.add_message("error", "No agent configured")
        except Exception as e:
            log.add_message("error", f"Error: {e}")
        
        status.update("idle")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "send-btn":
            self.action_send()


def run_tui(agent=None, show_thinking: bool = True):
    """Run the TUI application."""
    app = NanoCodeApp(agent=agent, show_thinking=show_thinking)
    app.run()


if __name__ == "__main__":
    run_tui()