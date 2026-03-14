"""Console interface for the agent."""

import asyncio
import sys
import os
import threading
import json
import httpx
import yaml
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

try:
    import readline

    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

HISTORY_FILE = os.path.expanduser("~/.config/agent_smith/history")


class PromptHandler:
    """Simple prompt handler to mimic @clack/prompts functionality."""

    async def confirm(self, message: str) -> bool:
        """Ask a yes/no question."""
        try:
            response = input(f"{message} (y/N): ").strip().lower()
            return response in ["y", "yes"]
        except (KeyboardInterrupt, EOFError):
            return False

    async def password(self, message: str, validate=None) -> Optional[str]:
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

    async def autocomplete(self, options: Dict[str, Any]) -> Optional[str]:
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
        except Exception:
            pass

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
        prompt_str = (
            f"\n{self.color(color, '┌─[' + state.upper() + ']')} {self.color('cyan', '➜')} "
        )
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
        help_text = """
╔═════════════════════════════════════════════════════════════╗
║                      Commands                              ║
╠══════════════════════════════════════════════════════════════╣
║  /help         - Show this help message                   ║
║  /exit/quit    - Exit the agent                           ║
║  /clear        - Clear the terminal                        ║
║  /history      - Show command history                     ║
║  /plan <task>  - Create and execute a plan                 ║
║  /provider     - Select AI provider and model              ║
║  /checkpoint   - List saved checkpoints                    ║
║  /resume <id>  - Resume from a checkpoint                  ║
║  /tools        - List available tools                      ║
║  /skills       - List available skills                     ║
║  /snapshot     - Create a new snapshot                     ║
║  /snapshots    - List available snapshots                  ║
║  /revert <hash> - Revert to a snapshot (hash or 'latest')║
║  /trace        - Show last error trace                     ║
║  /compact      - Compact context (summarize old messages)  ║
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

    def add(self, command: str, output: Optional[str] = None, timestamp: Optional[datetime] = None):
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
        return [h for h in self.history if query.lower() in h.get("command", "").lower()]

    def clear(self):
        """Clear history."""
        self.history.clear()


class InteractiveCLI:
    """Main CLI for the agent."""

    def __init__(self, agent):
        self.agent = agent
        self.ui = ConsoleUI()
        self.history = CommandHistory()
        self.last_error_trace: Optional[str] = None
        self.compact_threshold: float = 85.0

    async def run(self):
        """Run the CLI."""
        self.ui.print_welcome()

        while True:
            try:
                user_input = self.ui.print_prompt(state=self.agent.state.state.name.lower())

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

                    if command == "/compact":
                        await self._compact_context()
                        continue

                    # If it starts with "/" but doesn't match any known command, treat as regular input
                    await self._process_input(user_input)
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
            response = await self.agent.process_input(user_input)
        finally:
            spinner.stop()

        if response.startswith("Error:") and self.agent.state.last_traceback:
            self.last_error_trace = self.agent.state.last_traceback

        self.ui.print_message("assistant", response)

        await self._check_and_compact_context()

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

    async def _provider_command(self):
        """Handle the provider command for selecting providers and models."""
        self.ui.print_info("Provider/Model Selection")

        # Ask if user wants to select from recent models first
        use_recent = await self.ui.prompts.confirm("Select from recently used models?")

        if use_recent:
            recent_selection = await self._show_recent_models_menu()
            if recent_selection:
                # Parse provider/model from recent selection
                if "/" in recent_selection:
                    provider_id, model_id = recent_selection.split("/", 1)
                    # Get API key and update agent
                    api_key = await self._get_api_key(provider_id)
                    if api_key is not None:  # User didn't cancel
                        await self._store_api_key(provider_id, api_key)
                        await self._update_agent_model(provider_id, model_id)
                        await self._add_to_recent_models(provider_id, model_id)
                        self.ui.print_success(f"Selected {provider_id}/{model_id}")
                return

        # Otherwise, proceed with normal provider/model selection

        # Step 1: Load providers from models.dev
        providers = await self._fetch_providers()

        # Step 2: Show provider selection menu
        selected_provider = await self._select_provider(providers)
        if not selected_provider:
            return

        # Step 3: Get API key if needed
        api_key = await self._get_api_key(selected_provider)

        # Step 4: Store API key securely
        await self._store_api_key(selected_provider, api_key)

        # Step 5: Show model selection menu
        models = await self._fetch_models(selected_provider)
        selected_model = await self._select_model(models)
        if not selected_model:
            return

        # Step 6: Update agent configuration to use selected model
        await self._update_agent_model(selected_provider, selected_model)

        # Step 7: Add to recent models list
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
                0, {"id": "opencode", "name": "OpenCode (Free)", "model_count": "unknown"}
            )

        options = []
        for provider in providers:
            hint = f"{provider['model_count']} models"
            if provider["id"] == "opencode":
                hint = "Free models, no API key needed"
            options.append({"label": f"{provider['name']} ({hint})", "value": provider["id"]})

        selected = await self.ui.prompts.autocomplete(
            {"message": "Select provider", "maxItems": 8, "options": options}
        )

        if self.ui.prompts.isCancel(selected):
            return None
        return selected

    async def _get_api_key(self, provider_id):
        """Get API key for provider."""
        if provider_id == "opencode":
            return "public"  # Special case for opencode provider

        # Check if we already have a stored key
        stored_key = await self._get_stored_api_key(provider_id)
        if stored_key:
            overwrite = await self.ui.prompts.confirm(
                f"API key for {provider_id} already stored. Overwrite?"
            )
            if not overwrite:
                return stored_key

        # Ask for new API key
        key = await self.ui.prompts.password(
            message=f"Enter API key for {provider_id}",
            validate=lambda x: (x and len(x) > 0) and "Required" or None,
        )

        if self.ui.prompts.isCancel(key):
            return None
        return key

    async def _store_api_key(self, provider_id, api_key):
        """Store API key securely."""
        if not api_key:
            return

        # Create secure storage directory
        storage_dir = Path.home() / ".agent" / "credentials"
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
        key_file = Path.home() / ".agent" / "credentials" / f"{provider_id}.key"
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
                response = await client.get(f"https://models.dev/api.json", timeout=10.0)
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
                                "context": model_data.get("limit", {}).get("context", "unknown"),
                                "input_cost": model_data.get("cost", {}).get("input", 0),
                                "output_cost": model_data.get("cost", {}).get("output", 0),
                                "is_free": model_data.get("cost", {}).get("input", 0) == 0
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
                cost_info = f"${model['input_cost']}/{model['output_cost']} per 1M tokens"

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

        # Update config in memory
        self.agent.config.set("llm.default_model", model_full_id)

        # Reinitialize LLM with new configuration
        self.agent._init_llm()

        # Also update the config file if desired
        config_path = Path("config.yaml")
        if config_path.exists():
            import yaml

            try:
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                config["llm"]["default_model"] = model_full_id
                with open(config_path, "w") as f:
                    yaml.dump(config, f, default_flow_style=False)
            except Exception as e:
                self.ui.print_warning(f"Could not update config file: {e}")

    async def _add_to_recent_models(self, provider_id, model_id):
        """Add model to recent models list."""
        model_full_id = f"{provider_id}/{model_id}"

        # Load existing recent models
        recent_file = Path.home() / ".agent" / "recent_models.json"
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
        recent_models = recent_models[:5]

        # Save back
        try:
            recent_file.write_text(json.dumps(recent_models, indent=2))
        except Exception as e:
            self.ui.print_error(f"Failed to save recent models: {e}")

    async def _show_recent_models_menu(self):
        """Show menu of recently used models."""
        recent_file = Path.home() / ".agent" / "recent_models.json"
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
                    {"label": f"{provider_id}/{model_id} (recent)", "value": model_full_id}
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

    def _list_skills(self):
        """List available skills."""
        try:
            from agent_smith.skills import create_skills_manager

            manager = create_skills_manager()
            skills = manager.list_skills()

            if not skills:
                print(self.ui.color("yellow", "\nNo skills found."))
                print("Create skills in .agent/skills/<skill-name>/skill.md")
                return

            print(self.ui.color("cyan", "\nAvailable Skills:"))
            print(self.ui.color("gray", "─" * 40))
            for skill in skills:
                print(f"  • {self.ui.color('magenta', skill['name'])}: {skill['description']}")
                print(f"    {self.ui.color('gray', skill['location'])}")
        except ImportError:
            print(self.ui.color("gray", "\nSkills module not available."))

    async def _create_snapshot(self):
        """Create a new snapshot."""
        try:
            from agent_smith.snapshot import create_snapshot_manager

            manager = create_snapshot_manager()
            snapshot_hash = await manager.track()

            if snapshot_hash:
                self.ui.print_success(f"Snapshot created: {snapshot_hash[:8]}")
            else:
                self.ui.print_error("Failed to create snapshot")
        except Exception as e:
            self.ui.print_error(f"Error: {e}")

    async def _revert_snapshot(self, snapshot_hash: str):
        """Revert to a snapshot."""
        if not snapshot_hash:
            self.ui.print_error("Snapshot hash required. Use /snapshots to list available.")
            return

        try:
            from agent_smith.snapshot import create_snapshot_manager

            manager = create_snapshot_manager()

            if snapshot_hash == "latest":
                snapshots = await manager.list_snapshots()
                if not snapshots:
                    self.ui.print_error("No snapshots available")
                    return
                snapshot_hash = snapshots[0]["hash"]

            success = await manager.restore(snapshot_hash)

            if success:
                self.ui.print_success(f"Reverted to snapshot: {snapshot_hash[:8]}")
            else:
                self.ui.print_error("Failed to revert snapshot")
        except Exception as e:
            self.ui.print_error(f"Error: {e}")

    async def _list_snapshots(self):
        """List available snapshots."""
        try:
            from agent_smith.snapshot import create_snapshot_manager

            manager = create_snapshot_manager()
            snapshots = await manager.list_snapshots()

            if not snapshots:
                print(self.ui.color("yellow", "\nNo snapshots available."))
                print("Use /snapshot to create one.")
                return

            print(self.ui.color("cyan", "\nAvailable Snapshots:"))
            print(self.ui.color("gray", "─" * 40))
            for s in snapshots:
                print(f"  • {self.ui.color('magenta', s['hash'][:8])} ({s['timestamp']})")
        except Exception as e:
            self.ui.print_error(f"Error: {e}")

    def _print_trace(self):
        """Print the last error trace."""
        if self.last_error_trace:
            print(self.ui.color("red", "\n═══ Error Trace ═══"))
            print(self.last_error_trace)
        else:
            print(self.ui.color("gray", "\nNo error trace available."))

    async def _compact_context(self):
        """Compact the context by summarizing old messages."""
        try:
            ctx_mgr = getattr(self.agent, "context_manager", None)
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
            ctx_mgr = getattr(self.agent, "context_manager", None)
            if not ctx_mgr:
                return

            usage = ctx_mgr.get_token_usage()
            usage_percent = usage.get("context_usage_percent", 0)

            if usage_percent >= self.compact_threshold:
                self.ui.print_info(f"Context usage at {usage_percent:.1f}%, compacting...")
                await self._compact_context()
        except Exception:
            pass
