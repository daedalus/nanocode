"""Console interface for the agent."""

import asyncio
import sys
import os
import threading
from typing import Optional
from datetime import datetime


class Spinner:
    """Animated spinner shown while waiting for LLM response."""
    
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    
    def __init__(self, message: str = "Thinking"):
        self.message = message
        self.running = False
        self.thread = None
    
    def _spin(self):
        """Spin in background thread."""
        i = 0
        while self.running:
            frame = self.frames[i % len(self.frames)]
            sys.stdout.write(f"\r{self.ui.color('cyan', frame)} {self.message}...")
            sys.stdout.flush()
            i += 1
            threading.Event().wait(0.08)
        # Clear the spinner line
        sys.stdout.write("\r" + " " * (len(self.message) + 15))
        sys.stdout.write("\r")
        sys.stdout.flush()
    
    def start(self, ui):
        """Start the spinner."""
        if self.running:
            return
        self.ui = ui
        self.running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the spinner."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        # Ensure clean state
        sys.stdout.flush()


class ConsoleUI:
    """Terminal UI for the agent."""

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
        "gray": "\033[90m",
    }

    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors and sys.stdout.isatty()

    def color(self, color: str, text: str) -> str:
        """Apply color to text."""
        if not self.use_colors:
            return text
        c = self.COLORS.get(color, "")
        return f"{c}{text}{self.COLORS['reset']}"

    def print_welcome(self):
        """Print welcome message."""
        print(self.color("cyan", """
╔═══════════════════════════════════════════════════════════╗
║              Autonomous Agent - Ready                     ║
║  Type your task or 'help' for commands                   ║
╚═══════════════════════════════════════════════════════════╝
        """))

    def print_prompt(self, state: str = "idle"):
        """Print the prompt."""
        state_colors = {
            "idle": "white",
            "planning": "yellow",
            "executing": "blue",
            "waiting": "magenta",
            "complete": "green",
            "error": "red",
        }
        color = state_colors.get(state, "white")
        print(f"\n{self.color(color, '┌─[' + state.upper() + ']')}", end=" ")
        print(self.color("cyan", "➜"), end=" ")
        return input()

    def print_message(self, role: str, content: str):
        """Print a message."""
        role_colors = {
            "user": "green",
            "assistant": "blue",
            "system": "yellow",
            "tool": "magenta",
        }
        color = role_colors.get(role, "white")
        print(f"\n{self.color(color, '[' + role.upper() + ']')}")
        print(content)

    def print_tool_call(self, name: str, args: dict):
        """Print tool call."""
        print(f"\n{self.color('magenta', '⚡ Calling tool:')} {name}")
        for k, v in args.items():
            print(f"  {self.color('gray', k + ':')} {v}")

    def print_tool_result(self, result: str, success: bool = True):
        """Print tool result."""
        color = "green" if success else "red"
        prefix = "✓" if success else "✗"
        print(f"\n{self.color(color, prefix)} Result:")
        print(self.color("gray", "─" * 40))
        print(result[:2000] if len(result) > 2000 else result)
        if len(result) > 2000:
            print(self.color("yellow", f" ... ({len(result) - 2000} more chars)"))

    def print_error(self, error: str):
        """Print error message."""
        print(f"\n{self.color('red', '✗ Error:')} {error}")

    def print_info(self, info: str):
        """Print info message."""
        print(f"\n{self.color('blue', 'ℹ')} {info}")

    def print_success(self, message: str):
        """Print success message."""
        print(f"\n{self.color('green', '✓')} {message}")

    def print_plan(self, plan: dict):
        """Print execution plan."""
        print(f"\n{self.color('cyan', '📋 Execution Plan:')}")
        print(self.color("gray", "─" * 40))
        for i, step in enumerate(plan.get("steps", []), 1):
            status_icon = {
                "pending": "○",
                "running": "◐",
                "complete": "●",
                "failed": "✗",
            }.get(step.get("status", "pending"), "○")
            desc = step.get("description", "No description")
            print(f"  {status_icon} {i}. {desc}")
        print()

    def print_help(self):
        """Print help message."""
        print(self.color("cyan", """
╔═══════════════════════════════════════════════════════════╗
║                      Commands                              ║
╠═══════════════════════════════════════════════════════════╣
║  help          - Show this help message                   ║
║  exit/quit     - Exit the agent                           ║
║  clear         - Clear the terminal                        ║
║  history       - Show command history                     ║
║  plan <task>   - Create and execute a plan                 ║
║  checkpoint    - List saved checkpoints                    ║
║  resume <id>   - Resume from a checkpoint                  ║
║  tools         - List available tools                      ║
╚═══════════════════════════════════════════════════════════╝
        """))


class CommandHistory:
    """Manage command history."""

    def __init__(self, max_size: int = 100):
        self.history: list[dict] = []
        self.max_size = max_size

    def add(self, command: str, output: str = None, timestamp: datetime = None):
        """Add a command to history."""
        self.history.append({
            "command": command,
            "output": output,
            "timestamp": timestamp or datetime.now(),
        })
        if len(self.history) > self.max_size:
            self.history.pop(0)

    def get_all(self) -> list[dict]:
        """Get all history."""
        return self.history

    def search(self, query: str) -> list[dict]:
        """Search history."""
        return [
            h for h in self.history
            if query.lower() in h.get("command", "").lower()
        ]

    def clear(self):
        """Clear history."""
        self.history.clear()


class InteractiveCLI:
    """Main CLI for the agent."""

    def __init__(self, agent):
        self.agent = agent
        self.ui = ConsoleUI()
        self.history = CommandHistory()

    async def run(self):
        """Run the CLI."""
        self.ui.print_welcome()

        while True:
            try:
                user_input = self.ui.print_prompt(state=self.agent.state.state.name.lower())

                if not user_input.strip():
                    continue

                self.history.add(user_input)

                if user_input.lower() in ("exit", "quit", "q"):
                    print(self.ui.color("green", "Goodbye!"))
                    break

                if user_input.lower() == "help":
                    self.ui.print_help()
                    continue

                if user_input.lower() == "clear":
                    os.system("clear" if os.name == "posix" else "cls")
                    continue

                if user_input.lower() == "history":
                    self._print_history()
                    continue

                if user_input.lower() == "tools":
                    self._print_tools()
                    continue

                if user_input.lower().startswith("plan "):
                    task = user_input[5:]
                    await self._execute_task(task)
                    continue

                if user_input.lower().startswith("resume "):
                    checkpoint_id = user_input[7:]
                    await self._resume_checkpoint(checkpoint_id)
                    continue

                if user_input.lower() == "checkpoint":
                    self._list_checkpoints()
                    continue

                await self._process_input(user_input)

            except KeyboardInterrupt:
                print("\n" + self.ui.color("yellow", "Use 'exit' to quit"))
            except Exception as e:
                self.ui.print_error(str(e))

    async def _process_input(self, user_input: str):
        """Process user input through the agent."""
        self.ui.print_message("user", user_input)

        spinner = Spinner("Thinking")
        spinner.start(self.ui)
        
        try:
            response = await self.agent.process_input(user_input)
        finally:
            spinner.stop()
        
        self.ui.print_message("assistant", response)

    async def _execute_task(self, task: str):
        """Execute a task with planning."""
        self.ui.print_info(f"Planning: {task}")
        
        result = await self.agent.execute_task(task)
        
        if result.get("success"):
            self.ui.print_success(f"Task completed: {result.get('summary', 'Done')}")
        else:
            self.ui.print_error(result.get("error", "Task failed"))

    async def _resume_checkpoint(self, checkpoint_id: str):
        """Resume from a checkpoint."""
        self.ui.print_info(f"Resuming checkpoint: {checkpoint_id}")
        result = await self.agent.resume_from_checkpoint(checkpoint_id)
        
        if result.get("success"):
            self.ui.print_success("Checkpoint resumed successfully")
        else:
            self.ui.print_error(result.get("error", "Failed to resume"))

    def _print_history(self):
        """Print command history."""
        print(self.ui.color("cyan", "\nCommand History:"))
        print(self.ui.color("gray", "─" * 40))
        for i, item in enumerate(self.history.get_all()[-20:], 1):
            ts = item["timestamp"].strftime("%H:%M:%S")
            print(f"  {i}. [{ts}] {item['command']}")

    def _print_tools(self):
        """Print available tools."""
        tools = self.agent.tool_registry.list_tools()
        print(self.ui.color("cyan", "\nAvailable Tools:"))
        print(self.ui.color("gray", "─" * 40))
        for tool in tools:
            print(f"  • {self.ui.color('magenta', tool.name)}: {tool.description}")

    def _list_checkpoints(self):
        """List saved checkpoints."""
        import os
        checkpoint_dir = ".agent"
        if os.path.exists(checkpoint_dir):
            files = [f for f in os.listdir(checkpoint_dir) if f.startswith("checkpoint_")]
            if files:
                print(self.ui.color("cyan", "\nSaved Checkpoints:"))
                for f in files:
                    print(f"  • {f}")
            else:
                print(self.ui.color("gray", "No checkpoints found"))
        else:
            print(self.ui.color("gray", "No checkpoints found"))
