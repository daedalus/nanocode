"""Console interface for the agent."""

import json
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from nanocode.cli.commands import find_command, get_command_help

try:
    import readline

    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

HISTORY_FILE = os.path.expanduser("~/.config/nanocode/history")


def _get_default_storage_dir() -> Path:
    """Get default storage directory following XDG spec."""
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "nanocode" / "storage"


class PromptHandler:
    """Simple prompt handler to mimic @clack/prompts functionality."""

    async def confirm(self, message: str) -> bool:
        """Ask a yes/no question."""
        try:
            response = input(f"{message} (y/N): ").strip().lower()
            return response in ["y", "yes"]
        except (KeyboardInterrupt, EOFError):
            return False

    async def password(self, message: str, validate=None) -> str | None:
        """Ask for password input."""
        try:
            # Note: This doesn't hide input like a real password prompt
            # For production, consider using getpass.getpass()
            response = input(f"{message}: ").strip()
            if validate:
                error = validate(response)
                if error:
                    print(f"Validation error: {error}")
                    return await self.password(message, validate)  # Recursive retry
            return response if response else None
        except (KeyboardInterrupt, EOFError):
            return None

    async def autocomplete(self, options: dict[str, Any]) -> str | None:
        """Show autocomplete selection."""
        try:
            print(options["message"])
            opts = options["options"]
            for i, opt in enumerate(opts, 1):
                print(f"  {i}. {opt['label']}")

            choice = input(f"Select option (1-{len(opts)}): ").strip()
            try:
                index = int(choice) - 1
                if 0 <= index < len(opts):
                    return opts[index]["value"]
            except ValueError:
                pass
            return None
        except (KeyboardInterrupt, EOFError):
            return None

    def isCancel(self, value: Any) -> bool:
        """Check if value represents a cancellation."""
        return value is None


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
        self.prompts = PromptHandler()
        self._setup_readline()

    def _setup_readline(self):
        """Setup readline for history support."""
        if not READLINE_AVAILABLE:
            return
        try:
            readline.parse_and_bind("tab: complete")
            if hasattr(readline, "set_history_length"):
                readline.set_history_length(100)
            self._load_history()
            readline.set_completer(self._complete)
        except Exception:
            pass

    def _complete(self, text: str, state: int):
        """Tab completion handler for readline."""
        if not READLINE_AVAILABLE:
            return None

        line = readline.get_line_buffer()
        tokens = line.split()

        if not tokens or not line.startswith("/"):
            return None

        first_token = tokens[0].lower()

        if first_token == "/agent" and len(tokens) > 1:
            agent_names = self._get_agent_names()
            matches = [a for a in agent_names if a.startswith(text[7:].lower())]
            if state < len(matches):
                return matches[state]
            return None

        if first_token == "/":
            commands = [
                "help", "exit", "quit", "q", "clear", "history", "tools",
                "provider", "plan", "resume", "checkpoint", "skills",
                "snapshot", "snapshots", "revert", "trace", "debug",
                "compact", "show_thinking", "agents", "agent"
            ]
            matches = [f"/{c}" for c in commands if c.startswith(text[1:].lower())]
            if state < len(matches):
                return matches[state]
            return None

        return None

    def _get_agent_names(self) -> list[str]:
        """Get list of agent names for completion."""
        try:
            from nanocode.agents import get_agent_registry
            registry = get_agent_registry()
            return [a.name for a in registry.list_primary()]
        except Exception:
            return []

    def _load_history(self):
        """Load history from file."""
        if not READLINE_AVAILABLE:
            return
        try:
            history_path = os.environ.get("AGENT_SMITH_HISTORY", HISTORY_FILE)
            if os.path.exists(history_path):
                readline.read_history_file(history_path)
        except Exception:
            pass

    def save_history(self):
        """Save history to file."""
        if not READLINE_AVAILABLE:
            return
        try:
            history_path = os.environ.get("AGENT_SMITH_HISTORY", HISTORY_FILE)
            os.makedirs(os.path.dirname(history_path), exist_ok=True)
            readline.write_history_file(history_path)
        except Exception:
            pass

    def add_to_history(self, command: str):
        """Add a command to readline history."""
        if not READLINE_AVAILABLE or not command.strip():
            return
        try:
            readline.add_history(command)
        except Exception:
            pass

    def clear_history(self):
        """Clear readline history."""
        if not READLINE_AVAILABLE:
            return
        try:
            if hasattr(readline, "clear_history"):
                readline.clear_history()
        except Exception:
            pass

    def print_warning(self, message: str):
        """Print warning message."""
        print(f"\n{self.color('yellow', '⚠ Warning:')} {message}")

    def color(self, color: str, text: str) -> str:
        """Apply color to text."""
        if not self.use_colors:
            return text
        c = self.COLORS.get(color, "")
        return f"{c}{text}{self.COLORS['reset']}"

    def print_welcome(self):
        """Print welcome message."""
        print(
            self.color(
                "cyan",
                """
╔═══════════════════════════════════════════════════════════╗
║              Autonomous Agent - Ready                     ║
║  Type your task or 'help' for commands                   ║
╚═══════════════════════════════════════════════════════════╝
        """,
            )
        )

    def print_prompt(self, state: str = "idle", agent_name: str | None = None):
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
        agent_str = f"{agent_name}: " if agent_name else ""
        prompt_str = f"\n{self.color(color, '┌─[' + state.upper() + ']')} {self.color('cyan', agent_str + '➜')} "
        if READLINE_AVAILABLE:
            try:
                return input(prompt_str)
            except Exception:
                return input()
        return input(prompt_str)

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
        print(result)
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

    def print_permission_request(
        self,
        agent_name: str,
        tool_name: str,
        arguments: dict,
    ) -> bool:
        """Print a permission request and get user response."""
        print(f"\n{self.color('yellow', '┌─[PERMISSION REQUEST]')}")
        print(f"  {self.color('cyan', 'Agent:')} {agent_name}")
        print(f"  {self.color('cyan', 'Tool:')} {tool_name}")
        if arguments:
            print(f"  {self.color('cyan', 'Arguments:')}")
            for k, v in arguments.items():
                v_str = str(v)
                print(f"    {k}: {v_str}")
        print(f"  {self.color('magenta', '➜')} ", end="")

        try:
            response = input().strip().lower()
            if response in ("y", "yes", "a", "always"):
                return True
            if response == "always":
                return "always"
            return False
        except (KeyboardInterrupt, EOFError):
            return False

    def print_permission_result(self, tool_name: str, allowed: bool):
        """Print permission result."""
        if allowed:
            print(self.color("green", f"  ✓ Permission granted for '{tool_name}'"))
        else:
            print(self.color("red", f"  ✗ Permission denied for '{tool_name}'"))

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
        help_text = f"""
╔═════════════════════════════════════════════════════════════╗
║                      Commands                              ║
╠══════════════════════════════════════════════════════════════╣
{get_command_help()}
╚══════════════════════════════════════════════════════════════╝

NOTE: All commands MUST be prefixed with '/'. 
      Any text NOT starting with '/' is sent directly to the AI agent.
"""
        print(self.color("cyan", help_text))


class CommandHistory:
    """Manage command history."""

    def __init__(self, max_size: int = 100):
        self.history: list[dict] = []
        self.max_size = max_size

    def add(
        self,
        command: str,
        output: str | None = None,
        timestamp: datetime | None = None,
    ):
        """Add a command to history."""
        self.history.append(
            {
                "command": command,
                "output": output,
                "timestamp": timestamp or datetime.now(),
            }
        )
        if len(self.history) > self.max_size:
            self.history.pop(0)

    def get_all(self) -> list[dict]:
        """Get all history."""
        return self.history

    def search(self, query: str) -> list[dict]:
        """Search history."""
        return [
            h for h in self.history if query.lower() in h.get("command", "").lower()
        ]

    def clear(self):
        """Clear history."""
        self.history.clear()


class InteractiveCLI:
    """Main CLI for the agent."""

    def __init__(self, agent, show_thinking: bool = True, show_messages: bool = False):
        self.nanocode = agent
        self.ui = ConsoleUI()
        self.history = CommandHistory()
        self.last_error_trace: str | None = None
        self.compact_threshold: float = 85.0
        self.show_thinking = show_thinking
        self.show_messages = show_messages
        self.debug = False

    async def run(self):
        """Run the CLI."""
        self.ui.print_welcome()

        while True:
            try:
                agent_name = None
                if hasattr(self.nanocode, 'current_agent') and self.nanocode.current_agent:
                    agent_name = self.nanocode.current_agent.name

                user_input = self.ui.print_prompt(
                    state=self.nanocode.state.state.name.lower(),
                    agent_name=agent_name
                )

                if not user_input.strip():
                    continue

                self.history.add(user_input)

                # Handle slash-prefixed commands ONLY
                if user_input.startswith("/"):
                    command = user_input.lower()
                    if command in ("/exit", "/quit", "/q"):
                        self.ui.save_history()
                        print(self.ui.color("green", "Goodbye!"))
                        break

                    if command == "/help":
                        self.ui.print_help()
                        continue

                    if command == "/clear":
                        os.system("clear" if os.name == "posix" else "cls")
                        continue

                    if command == "/history":
                        self._print_history()
                        continue

                    if command == "/tools":
                        self._print_tools()
                        continue

                    if command == "/provider":
                        await self._provider_command()
                        continue

                    if command.startswith("/plan "):
                        task = user_input[6:]
                        await self._execute_task(task)
                        continue

                    if command.startswith("/resume "):
                        checkpoint_id = user_input[8:]
                        await self._resume_checkpoint(checkpoint_id)
                        continue

                    if command == "/checkpoint":
                        self._list_checkpoints()
                        continue

                    if command == "/skills":
                        self._list_skills()
                        continue

                    if command == "/snapshot":
                        await self._create_snapshot()
                        continue

                    if command.startswith("/revert "):
                        snapshot_hash = user_input[8:].strip()
                        await self._revert_snapshot(snapshot_hash)
                        continue

                    if command == "/snapshots":
                        await self._list_snapshots()
                        continue

                    if command == "/trace":
                        self._print_trace()
                        continue

                    if command == "/debug":
                        await self._handle_debug_command()
                        continue

                    if command == "/compact":
                        await self._compact_context()
                        continue

                    if command == "/show_thinking":
                        self.show_thinking = not self.show_thinking
                        self.ui.print_info(
                            f"Show thinking: {'enabled' if self.show_thinking else 'disabled'}"
                        )
                        continue

                    if command == "/agents":
                        self._list_agents()
                        continue

                    if command.startswith("/agent "):
                        agent_name = user_input[8:].strip()
                        await self._switch_agent(agent_name)
                        continue

                    # If it starts with "/" but doesn't match any known command, show error and stop processing
                    cmd = find_command(user_input)
                    if cmd is None:
                        self.ui.print_error(
                            f"Unknown command: {user_input}. Type /help for available commands."
                        )
                        continue
                else:
                    # Treat ALL non-slash-prefixed input as regular agent input
                    # Do NOT convert "help" to "/help" or treat any plain text as commands
                    await self._process_input(user_input)

            except KeyboardInterrupt:
                self.ui.save_history()
                print("\n" + self.ui.color("yellow", "Use 'exit' to quit"))
            except Exception as e:
                self.last_error_trace = traceback.format_exc()
                self.ui.print_error(str(e))

    async def _process_input(self, user_input: str):
        """Process user input through the agent."""
        self.ui.print_message("user", user_input)

        spinner = Spinner("Thinking")
        spinner.start(self.ui)

        try:
            response = await self.nanocode.process_input(
                user_input,
                show_thinking=self.show_thinking,
                show_messages=self.show_messages,
            )
        finally:
            spinner.stop()

        if response.startswith("Error:") and self.nanocode.state.last_traceback:
            self.last_error_trace = self.nanocode.state.last_traceback

        self.ui.print_message("assistant", response)

        await self._check_and_compact_context()

    async def _execute_task(self, task: str):
        """Execute a task with planning."""
        self.ui.print_info(f"Planning: {task}")

        result = await self.nanocode.execute_task(task)

        if result.get("success"):
            self.ui.print_success(f"Task completed: {result.get('summary', 'Done')}")
        else:
            self.ui.print_error(result.get("error", "Task failed"))

    async def _resume_checkpoint(self, checkpoint_id: str):
        """Resume from a checkpoint."""
        self.ui.print_info(f"Resuming checkpoint: {checkpoint_id}")
        result = await self.nanocode.resume_from_checkpoint(checkpoint_id)

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
        tools = self.nanocode.tool_registry.list_tools()
        print(self.ui.color("cyan", "\nAvailable Tools:"))
        print(self.ui.color("gray", "─" * 40))
        for tool in tools:
            print(f"  • {self.ui.color('magenta', tool.name)}: {tool.description}")

    async def _provider_command(self):
        """Handle the provider command for selecting providers and models."""
        self.ui.print_info("Provider/Model Selection")

        # Check if there are recent models to show
        recent_file = _get_default_storage_dir() / "recent_models.json"
        has_recent = False
        if recent_file.exists():
            try:
                recent_models = json.loads(recent_file.read_text())
                has_recent = bool(recent_models)
            except Exception:
                has_recent = False

        # If there are recent models, offer choice; otherwise go directly to new selection
        if has_recent:
            choice = await self.ui.prompts.confirm("Select from recent models?")
            if choice:
                recent_selection = await self._show_recent_models_menu()
                if recent_selection:
                    provider_id, model_id = recent_selection.split("/", 1)
                    api_key = await self._get_api_key(provider_id)
                    if api_key is not None:
                        await self._store_api_key(provider_id, api_key)
                        await self._update_agent_model(provider_id, model_id)
                        await self._add_to_recent_models(provider_id, model_id)
                        self.ui.print_success(f"Selected {provider_id}/{model_id}")
                return

        # Proceed with new provider/model selection
        providers = await self._fetch_providers()
        selected_provider = await self._select_provider(providers)
        if not selected_provider:
            return

        api_key = await self._get_api_key(selected_provider)
        if api_key is None:
            return

        await self._store_api_key(selected_provider, api_key)

        models = await self._fetch_models(selected_provider)
        selected_model = await self._select_model(models)
        if not selected_model:
            return

        await self._update_agent_model(selected_provider, selected_model)
        await self._add_to_recent_models(selected_provider, selected_model)

        self.ui.print_success(f"Selected {selected_provider}/{selected_model}")

    async def _fetch_providers(self):
        """Fetch providers from models.dev API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("https://models.dev/api.json", timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    # Format: {provider_id: {name: "...", models: {...}}, ...}
                    providers = []
                    for provider_id, provider_data in data.items():
                        providers.append(
                            {
                                "id": provider_id,
                                "name": provider_data.get("name", provider_id),
                                "model_count": len(provider_data.get("models", {})),
                            }
                        )
                    return sorted(providers, key=lambda x: x["name"])
        except Exception as e:
            self.ui.print_error(f"Failed to fetch providers: {e}")
            return []

    async def _select_provider(self, providers):
        """Show provider selection menu."""
        if not providers:
            self.ui.print_error("No providers available")
            return None

        # Add special "opencode" provider if not present
        opencode_exists = any(p["id"] == "opencode" for p in providers)
        if not opencode_exists:
            providers.insert(
                0,
                {"id": "opencode", "name": "OpenCode (Free)", "model_count": "unknown"},
            )

        options = []
        for provider in providers:
            hint = f"{provider['model_count']} models"
            if provider["id"] == "opencode":
                hint = "Free models, no API key needed"
            options.append(
                {"label": f"{provider['name']} ({hint})", "value": provider["id"]}
            )

        selected = await self.ui.prompts.autocomplete(
            {"message": "Select provider", "maxItems": 8, "options": options}
        )

        if self.ui.prompts.isCancel(selected):
            return None
        return selected

    async def _get_api_key(self, provider_id):
        """Get API key for provider."""
        # Providers that don't need API keys
        if provider_id in ("opencode", "ollama", "lm-studio"):
            return "public" if provider_id == "opencode" else None

        # Check if we already have a stored key
        stored_key = await self._get_stored_api_key(provider_id)
        if stored_key:
            return stored_key

        # Ask for new API key
        key = await self.ui.prompts.password(
            message=f"Enter API key for {provider_id}",
            validate=lambda x: None if (x and len(x) > 0) else "Required",
        )

        if self.ui.prompts.isCancel(key):
            return None
        return key

    async def _store_api_key(self, provider_id, api_key):
        """Store API key securely."""
        if not api_key:
            return

        # Create secure storage directory
        storage_dir = _get_default_storage_dir() / "credentials"
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Store key (in a real implementation, this would be encrypted)
        key_file = storage_dir / f"{provider_id}.key"
        try:
            key_file.write_text(api_key)
            # Set restrictive permissions (Unix-like systems)
            os.chmod(key_file, 0o600)
        except Exception as e:
            self.ui.print_error(f"Failed to store API key: {e}")

    async def _get_stored_api_key(self, provider_id):
        """Retrieve stored API key."""
        key_file = _get_default_storage_dir() / "credentials" / f"{provider_id}.key"
        if key_file.exists():
            try:
                return key_file.read_text().strip()
            except Exception:
                pass
        return None

    async def _fetch_models(self, provider_id):
        """Fetch models for a specific provider."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("https://models.dev/api.json", timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    provider_data = data.get(provider_id, {})
                    models = provider_data.get("models", {})

                    # Format for selection
                    model_list = []
                    for model_id, model_data in models.items():
                        model_list.append(
                            {
                                "id": model_id,
                                "name": model_data.get("name", model_id),
                                "context": model_data.get("limit", {}).get(
                                    "context", "unknown"
                                ),
                                "input_cost": model_data.get("cost", {}).get(
                                    "input", 0
                                ),
                                "output_cost": model_data.get("cost", {}).get(
                                    "output", 0
                                ),
                                "is_free": model_data.get("cost", {}).get("input", 0)
                                == 0
                                and model_data.get("cost", {}).get("output", 0) == 0,
                            }
                        )

                    # Sort: free models first, then by name
                    model_list.sort(key=lambda x: (not x["is_free"], x["name"]))
                    return model_list
        except Exception as e:
            self.ui.print_error(f"Failed to fetch models: {e}")
            return []

    async def _select_model(self, models):
        """Show model selection menu."""
        if not models:
            self.ui.print_error("No models available")
            return None

        options = []
        for model in models:
            cost_info = ""
            if model["is_free"]:
                cost_info = "free"
            else:
                cost_info = (
                    f"${model['input_cost']}/{model['output_cost']} per 1M tokens"
                )

            options.append(
                {
                    "label": f"{model['name']} ({model['context']}ctx, {cost_info})",
                    "value": model["id"],
                }
            )

        selected = await self.ui.prompts.autocomplete(
            {"message": "Select model", "maxItems": 10, "options": options}
        )

        if self.ui.prompts.isCancel(selected):
            return None
        return selected

    async def _update_agent_model(self, provider_id, model_id):
        """Update the agent's LLM configuration to use the selected model."""
        # Update the agent's LLM configuration
        model_full_id = f"{provider_id}/{model_id}"

        # Update config in memory - enable model registry and set provider
        self.nanocode.config.set("llm.use_model_registry", True)
        self.nanocode.config.set("llm.default_model", model_full_id)

        # Get API key and store in config so LLM can find it
        api_key = await self._get_stored_api_key(provider_id)
        if api_key:
            self.nanocode.config.set(f"llm.providers.{provider_id}.api_key", api_key)

        # Reinitialize LLM with new configuration
        self.nanocode._init_llm()

        # Also update the config file if desired
        config_path = Path("config.yaml")
        if config_path.exists():
            import yaml

            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                config["llm"]["use_model_registry"] = True
                config["llm"]["default_model"] = model_full_id
                if api_key:
                    config.setdefault("llm", {}).setdefault("providers", {}).setdefault(
                        provider_id, {}
                    )["api_key"] = api_key
                with open(config_path, "w") as f:
                    yaml.dump(config, f, default_flow_style=False)
            except Exception as e:
                self.ui.print_warning(f"Could not update config file: {e}")

    async def _add_to_recent_models(self, provider_id, model_id):
        """Add model to recent models list."""
        model_full_id = f"{provider_id}/{model_id}"

        # Load existing recent models
        recent_file = _get_default_storage_dir() / "recent_models.json"
        recent_models = []

        if recent_file.exists():
            try:
                recent_models = json.loads(recent_file.read_text())
            except Exception:
                recent_models = []

        # Remove if already exists (to move to front)
        recent_models = [m for m in recent_models if m != model_full_id]

        # Add to front
        recent_models.insert(0, model_full_id)

        # Keep only last 5
        recent_models = recent_models

        # Save back
        try:
            recent_file.write_text(json.dumps(recent_models, indent=2))
        except Exception as e:
            self.ui.print_error(f"Failed to save recent models: {e}")

    async def _show_recent_models_menu(self):
        """Show menu of recently used models."""
        recent_file = _get_default_storage_dir() / "recent_models.json"
        recent_models = []

        if recent_file.exists():
            try:
                recent_models = json.loads(recent_file.read_text())
            except Exception:
                recent_models = []

        if not recent_models:
            return None

        options = []
        for model_full_id in recent_models:
            if "/" in model_full_id:
                provider_id, model_id = model_full_id.split("/", 1)
                options.append(
                    {
                        "label": f"{provider_id}/{model_id} (recent)",
                        "value": model_full_id,
                    }
                )

        if not options:
            return None

        selected = await self.ui.prompts.autocomplete(
            {"message": "Select recent model", "maxItems": 5, "options": options}
        )

        if self.ui.prompts.isCancel(selected):
            return None
        return selected

    def _list_checkpoints(self):

        checkpoint_dir = str(_get_default_storage_dir() / "checkpoints")
        if os.path.exists(checkpoint_dir):
            files = [
                f for f in os.listdir(checkpoint_dir) if f.startswith("checkpoint_")
            ]
            if files:
                print(self.ui.color("cyan", "\nSaved Checkpoints:"))
                for f in files:
                    print(f"  • {f}")
            else:
                print(self.ui.color("gray", "No checkpoints found"))
        else:
            print(self.ui.color("gray", "No checkpoints found"))

    def _list_skills(self):
        """List available skills."""
        try:
            from nanocode.skills import create_skills_manager

            manager = create_skills_manager()
            skills = manager.list_skills()

            if not skills:
                print(self.ui.color("yellow", "\nNo skills found."))
                print("Create skills in .nanocode/skills/<skill-name>/skill.md")
                return

            print(self.ui.color("cyan", "\nAvailable Skills:"))
            print(self.ui.color("gray", "─" * 40))
            for skill in skills:
                print(
                    f"  • {self.ui.color('magenta', skill['name'])}: {skill['description']}"
                )
                print(f"    {self.ui.color('gray', skill['location'])}")
        except ImportError:
            print(self.ui.color("gray", "\nSkills module not available."))

    def _list_agents(self):
        """List available agents."""
        if not hasattr(self.nanocode, 'nanocode_registry'):
            self.ui.print_error("Agent registry not available")
            return

        agents = self.nanocode.nanocode_registry.list_primary()
        current = self.nanocode.current_agent.name if self.nanocode.current_agent else None

        print(self.ui.color("cyan", "\nAvailable Agents:"))
        print(self.ui.color("gray", "─" * 40))
        for agent in agents:
            marker = " *" if agent.name == current else ""
            color = self.ui.color('green', agent.name) if agent.name == current else self.ui.color('white', agent.name)
            print(f"  • {color}{marker}")
            if agent.description:
                print(f"    {self.ui.color('gray', agent.description)}")
        print()
        print(f"{self.ui.color('cyan', 'Current:')} {current}")
        print(f"{self.ui.color('gray', 'Use /agent <name> to switch')}")

    async def _switch_agent(self, agent_name: str):
        """Switch to a different agent."""
        if not agent_name:
            self.ui.print_error("Agent name required. Use /agents to list available agents.")
            return

        if not hasattr(self.nanocode, 'switch_agent'):
            self.ui.print_error("Agent switching not available")
            return

        success = self.nanocode.switch_agent(agent_name)
        if success:
            self.ui.print_success(f"Switched to agent: {agent_name}")
        else:
            available = [a.name for a in self.nanocode.nanocode_registry.list_primary()]
            self.ui.print_error(f"Agent '{agent_name}' not found. Available: {', '.join(available)}")

    async def _create_snapshot(self):
        """Create a new snapshot."""
        try:
            from nanocode.snapshot import create_snapshot_manager

            manager = create_snapshot_manager()
            snapshot_hash = await manager.track()

            if snapshot_hash:
                self.ui.print_success(f"Snapshot created: {snapshot_hash}")
            else:
                self.ui.print_error("Failed to create snapshot")
        except Exception as e:
            self.ui.print_error(f"Error: {e}")

    async def _revert_snapshot(self, snapshot_hash: str):
        """Revert to a snapshot."""
        if not snapshot_hash:
            self.ui.print_error(
                "Snapshot hash required. Use /snapshots to list available."
            )
            return

        try:
            from nanocode.snapshot import create_snapshot_manager

            manager = create_snapshot_manager()

            if snapshot_hash == "latest":
                snapshots = await manager.list_snapshots()
                if not snapshots:
                    self.ui.print_error("No snapshots available")
                    return
                snapshot_hash = snapshots[0]["hash"]

            success = await manager.restore(snapshot_hash)

            if success:
                self.ui.print_success(f"Reverted to snapshot: {snapshot_hash}")
            else:
                self.ui.print_error("Failed to revert snapshot")
        except Exception as e:
            self.ui.print_error(f"Error: {e}")

    async def _list_snapshots(self):
        """List available snapshots."""
        try:
            from nanocode.snapshot import create_snapshot_manager

            manager = create_snapshot_manager()
            snapshots = await manager.list_snapshots()

            if not snapshots:
                print(self.ui.color("yellow", "\nNo snapshots available."))
                print("Use /snapshot to create one.")
                return

            print(self.ui.color("cyan", "\nAvailable Snapshots:"))
            print(self.ui.color("gray", "─" * 40))
            for s in snapshots:
                print(
                    f"  • {self.ui.color('magenta', s['hash'])} ({s['timestamp']})"
                )
        except Exception as e:
            self.ui.print_error(f"Error: {e}")

    def _print_trace(self):
        """Print the last error trace."""
        if self.last_error_trace:
            print(self.ui.color("red", "\n═══ Error Trace ═══"))
            print(self.last_error_trace)
        else:
            print(self.ui.color("gray", "\nNo error trace available."))

    async def _handle_debug_command(self):
        """Handle the /debug command to toggle HTTP and tool debug logging."""
        import logging

        self.debug = not self.debug

        if hasattr(self.nanocode, "debug"):
            self.nanocode.debug = self.debug

        if self.debug:
            logging.getLogger("httpx").setLevel(logging.DEBUG)
            logging.getLogger("nanocode.tools").setLevel(logging.DEBUG)
            self.ui.print_info(
                "Debug mode enabled - HTTP requests and tool calls will be logged"
            )
        else:
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("nanocode.tools").setLevel(logging.WARNING)
            self.ui.print_info("Debug mode disabled")

    async def _compact_context(self):
        """Compact the context by summarizing old messages."""
        try:
            ctx_mgr = getattr(self.nanocode, "context_manager", None)
            if not ctx_mgr:
                self.ui.print_error("Context manager not available")
                return

            before_count = len(ctx_mgr._messages)
            before_tokens = ctx_mgr.get_token_usage().get("current_tokens", 0)

            if hasattr(ctx_mgr, "_compact_async"):
                await ctx_mgr._compact_async()
            elif hasattr(ctx_mgr, "_compact"):
                ctx_mgr._compact()

            after_count = len(ctx_mgr._messages)
            after_tokens = ctx_mgr.get_token_usage().get("current_tokens", 0)

            self.ui.print_success(
                f"Context compacted: {before_count} → {after_count} messages, "
                f"{before_tokens} → {after_tokens} tokens"
            )
        except Exception as e:
            self.ui.print_error(f"Failed to compact context: {e}")

    async def _check_and_compact_context(self):
        """Check context usage and auto-compact if threshold is reached."""
        try:
            ctx_mgr = getattr(self.nanocode, "context_manager", None)
            if not ctx_mgr:
                return

            usage = ctx_mgr.get_token_usage()
            usage_percent = usage.get("context_usage_percent", 0)

            if usage_percent >= self.compact_threshold:
                self.ui.print_info(
                    f"Context usage at {usage_percent:.1f}%, compacting..."
                )
                await self._compact_context()
        except Exception:
            pass
