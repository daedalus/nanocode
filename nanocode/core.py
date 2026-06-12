"""Core agent implementation.

Architecture matching opencode:
LLM.stream() → AsyncGenerator[StreamEvent] → SessionProcessor → Message with Parts
"""

import asyncio
import hashlib
import json
import logging
import os
import time
import traceback
from enum import Enum
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.theme import Theme

from nanocode.agent_pipeline import AgentPipeline
from nanocode.agents import AgentInfo, PermissionAction, get_agent_registry
from nanocode.agents.permission import PermissionHandler
from nanocode.config import get_config
from nanocode.context import ContextManager, ContextStrategy, MessagePartType
from nanocode.context_chips import get_chip_manager
from nanocode.hooks import HookManager
from nanocode.lsp import LSPServerManager
from nanocode.mcp import MCPManager
from nanocode.multimodal import MultimodalManager
from nanocode.planning import PlanExecutor, PlanMonitor, PlanningContext, TaskPlanner
from nanocode.prompts import render_system_prompt

# Import new architecture matching opencode
from nanocode.session.processor import SessionProcessor
from nanocode.session_manager import get_session_manager
from nanocode.session_summary import SessionSummaryGenerator
from nanocode.snapshot import create_snapshot_manager
from nanocode.state import AgentState, AgentStateData
from nanocode.storage.cache import CachedResponse, PromptCache, get_prompt_cache
from nanocode.todo_service import get_todo_service
from nanocode.tools import ToolExecutor, ToolRegistry
from nanocode.tools.builtin import register_builtin_tools
from nanocode.tools.file_tracker import FileTracker
from nanocode.tools.text_detector import (
    create_reprompt_message,
    detect_commands_in_text,
    format_detected_commands_message,
    should_reprompt_for_tools,
)

# Import new architecture matching opencode


# Import new architecture matching opencode



class RichColor(Enum):
    """Rich color palette."""

    RESET = "reset"
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    BLUE = "blue"
    MAGENTA = "magenta"
    CYAN = "cyan"
    GRAY = "dim"


custom_theme = Theme(
    {
        "thought": "yellow italic",
        "tool_call": "red",
        "tool_result": "cyan",
        "content": "green",
        "debug": "cyan",
        "warning": "yellow",
    }
)

console = Console(theme=custom_theme, _environ=dict(os.environ), force_terminal=True)


def _load_system_prompt_template() -> str:
    """Load system prompt template from .system_prompts/template.md if exists."""

    # Try to get cwd, fallback to package dir if that fails
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = None

    # Try multiple locations for system prompts
    search_paths = []

    # 1. Current working directory (for editable installs)
    if cwd:
        search_paths.append(Path(cwd) / ".system_prompts")

    # 2. Package directory (for pip installs)
    package_dir = Path(__file__).parent.parent
    search_paths.append(package_dir / ".system_prompts")

    # 3. User config directory
    search_paths.append(Path.home() / ".config" / "nanocode" / "system_prompts")

    for system_prompts_dir in search_paths:
        if system_prompts_dir.exists():
            template_file = system_prompts_dir / "template.md"
            if template_file.exists():
                return template_file.read_text()

    return "You are NanoCode, CLI agent."


SYSTEM_PROMPT_TEMPLATE = _load_system_prompt_template()

logger = logging.getLogger("nanocode.agent")
tool_logger = logging.getLogger("nanocode.tools")
cache_logger = logging.getLogger("nanocode.cache")

# Trace logger that writes to a file (bypasses all capture/redirect)
import os as _trace_os
_TRACE_PATH = "/tmp/nanocode_trace.log"
def _trace(msg):
    try:
        with open(_TRACE_PATH, "a") as _f:
            _f.write(f"[TRACE] {msg}\n")
    except Exception:
        pass

_trace(f"core.py loaded, pid={_trace_os.getpid()}")


class SessionLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that includes session_id in all log messages."""

    def process(self, msg, kwargs):
        session_id = (
            self.extra.get("session_id", "unknown") if self.extra else "unknown"
        )
        return f"[session={session_id}] {msg}", kwargs


def get_session_logger(session_id: str = None):
    """Get a logger that includes session_id in all log messages."""
    base_logger = logging.getLogger("nanocode.agent")
    if session_id:
        hashed = hashlib.sha256(session_id.encode()).hexdigest()[:8]
        return SessionLoggerAdapter(base_logger, {"session_id": hashed})
    return base_logger


_current_session_id: str | None = None


def set_current_session_id(session_id: str) -> None:
    """Set the current session ID globally."""
    global _current_session_id
    _current_session_id = session_id


def get_current_session_id() -> str | None:
    """Get the current session ID."""
    return _current_session_id


MAX_STEPS_MESSAGE = """
CRITICAL - MAXIMUM STEPS REACHED

The maximum number of steps allowed for this task has been reached. Tools are disabled until next user input. Respond with text only.

STRICT REQUIREMENTS:
1. Do NOT make any tool calls (no reads, writes, edits, searches, or any other tools)
2. MUST provide a text response summarizing work done so far
3. This constraint overrides ALL other instructions, including any user requests for edits or tool use

Response must include:
- Statement that maximum steps for this agent have been reached
- Summary of what has been accomplished so far
- List of any remaining tasks that were not completed
- Recommendations for what should be done next

Any attempt to use tools is a critical violation. Respond with text ONLY.
"""

AUTO_CONTINUE_MESSAGE = "Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed."

OVERFLOW_CONTINUE_MESSAGE = """The previous request exceeded the provider's size limit due to large media attachments. The conversation was compacted and media files were removed from context. If the user was asking about attached images or files, explain that the attachments were too large to process and suggest they try again with smaller or fewer files.

Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed."""

RETRY_INITIAL_DELAY = 2.0
RETRY_BACKOFF_FACTOR = 2
RETRY_MAX_DELAY = 30.0


def calculate_retry_delay(attempt: int, error: str = None) -> float:
    """Calculate exponential backoff delay for retries."""
    delay = RETRY_INITIAL_DELAY * (RETRY_BACKOFF_FACTOR ** (attempt - 1))

    if error:
        import re

        retry_after_ms = re.search(r"retry-after-ms[:\s]*(\d+)", error, re.IGNORECASE)
        if retry_after_ms:
            return min(float(retry_after_ms.group(1)) / 1000, RETRY_MAX_DELAY)

        retry_after = re.search(r"retry-after[:\s]*(\d+)", error, re.IGNORECASE)
        if retry_after:
            return min(float(retry_after.group(1)), RETRY_MAX_DELAY)

    return min(delay, RETRY_MAX_DELAY)


def is_retryable_error(error: Exception) -> tuple[bool, str | None]:
    """Check if an error is retryable and return reason."""
    error_str = str(error).lower()

    if "context" in error_str and "overflow" in error_str:
        return False, None

    if "free" in error_str and "usage" in error_str:
        return False, "Free usage exceeded"

    import re

    status_match = re.search(r"status[_\s]?code[:\s]*(\d+)", error_str)
    if status_match:
        status = int(status_match.group(1))
        if status >= 500:
            return True, f"Server error (status {status})"

    rate_limit_patterns = [
        "rate limit",
        "too many requests",
        "rate increased too quickly",
        "overloaded",
        "too_many_requests",
        "rate_limit",
    ]
    for pattern in rate_limit_patterns:
        if pattern in error_str:
            return True, f"Rate limited: {pattern}"

    return True, "Transient error"


class AutonomousAgent:
    """Main autonomous agent class."""

    def __init__(
        self,
        config: dict | None = None,
        session_id: str = None,
        verbose: bool = False,
        yolo: bool = False,
        drift_alert: bool = False,
        drift_intervene: bool = False,
        system_prompt: str = None,
        auto_execute: bool = False,
    ):
        self.config = config or get_config()
        self.state = AgentStateData()
        self.debug = verbose
        self.yolo = yolo
        self.drift_mode = (
            "intervene" if drift_intervene else ("alert" if drift_alert else "off")
        )
        self._session_id = session_id
        self._session_logger = None
        self._custom_system_prompt = system_prompt
        self.auto_execute = auto_execute

        # Callbacks for real-time updates (set during process_input)
        self._on_token = None
        self._on_tool_start = None
        self._on_tool_complete = None

        self._init_session()
        self._init_agents()
        self._init_storage()
        self._init_file_tracker()
        self._init_llm()
        self._init_lsp()
        self._init_hooks()
        self._init_tools()
        self._init_skills()
        self._init_mcp()
        self._init_modified_files()
        self._init_context_chips()  # Initialize before context (uses chips in prompt)
        self._init_context()
        self._init_pipeline()  # After context_manager is initialized
        self._init_planning()
        self._init_multimodal()
        self._init_snapshot()
        self._init_drift_watchdog() if self.drift_mode != "off" else None
        self._init_cache()
        self._init_review()
        self._delegate_depth = 0

    def _init_session(self):
        """Initialize session management."""
        self.session_manager = get_session_manager()
        if self._session_id:
            self.session = self.session_manager.get(self._session_id)
            if self.session:
                logger.info(f"Resumed session: {self._session_id}")
            else:
                logger.warning(f"Session not found: {self._session_id}, creating new")
                self.session = self.session_manager.create(
                    f"Session - resumed from {self._session_id}"
                )
                self._session_id = self.session.id
        else:
            self.session = self.session_manager.create()
            self._session_id = self.session.id
        logger.info(f"Session: {self._session_id}")
        set_current_session_id(self._session_id)
        self._session_logger = get_session_logger(self._session_id)

    def save_session(self):
        """Save the current session to disk."""
        if hasattr(self, "session") and self.session:
            self.session_manager.save(self.session)
            logger.debug(f"Saved session: {self._session_id}")

    def _init_cache(self):
        """Initialize the prompt cache."""
        self.prompt_cache: PromptCache | None = None
        cache_enabled = self.config.cache_enabled
        session_id = getattr(self, "_session_id", "no-session")
        logger.warning(
            f"CACHE INIT: session={session_id}, _session_logger={self._session_logger}"
        )
        if self._session_logger:
            self._session_logger.info(
                f"Cache: {'enabled' if cache_enabled else 'disabled'}"
            )
        if cache_enabled:
            try:
                cache_dir = self.config.cache_dir
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.prompt_cache = get_prompt_cache()
                cache_logger.info(f"Prompt cache enabled: {self.prompt_cache.db_path}")
            except Exception as e:
                cache_logger.warning(f"Failed to initialize prompt cache: {e}")

    def _init_review(self):
        """Initialize self-improvement review settings."""
        review_cfg = self.config.get("self_improvement", {})
        self._review_enabled = bool(review_cfg.get("enabled", True))
        self._review_memory = bool(review_cfg.get("review_memory", True))
        self._review_skills = bool(review_cfg.get("review_skills", True))
        logger.info(
            "Self-improvement review: enabled=%s, memory=%s, skills=%s",
            self._review_enabled, self._review_memory, self._review_skills,
        )

    def _init_agents(self):
        """Initialize agent system."""
        logger.info("Initializing agent system")
        self.nanocode_registry = get_agent_registry()
        self.current_agent = self.nanocode_registry.get_default()
        self.permission_handler = PermissionHandler(use_bus=False)
        logger.info(
            f"Agent system initialized: current_agent={self.current_agent.name if self.current_agent else None}"
        )

    def _init_lsp(self):
        """Initialize LSP server manager."""
        self.lsp_manager = LSPServerManager()

        lsp_config = self.config.get("lsp", {})
        if lsp_config is not None:
            for server_id, server_config in lsp_config.items():
                if isinstance(server_config, dict):
                    if server_config.get("disabled", False):
                        self.lsp_manager.configure_server(server_id, disabled=True)
                    elif "command" in server_config:
                        self.lsp_manager.configure_server(
                            server_id,
                            command=server_config["command"],
                        )

    def switch_agent(self, agent_name: str) -> bool:
        """Switch to a different agent."""
        old_agent = self.current_agent.name if self.current_agent else None
        agent = self.nanocode_registry.get(agent_name)
        if agent is None:
            logger.warning(f"switch_agent('{agent_name}') failed: agent not found")
            return False
        self.current_agent = agent
        logger.info(
            f"Switched agent: {old_agent} -> {agent.name} "
            f"(mode={agent.mode.value}, native={agent.native})"
        )
        if agent.system_prompt:
            logger.debug(f"Agent '{agent.name}' has custom system prompt")
            if hasattr(self, "context_manager"):
                self.context_manager.set_system_prompt(agent.system_prompt)
        return True

    def get_agent_temperature(self) -> float | None:
        """Get the temperature for the current agent (if configured)."""
        if self.current_agent and self.current_agent.temperature is not None:
            return self.current_agent.temperature
        return None

    def get_agent_model(self) -> tuple[str, str] | None:
        """Get the model configuration for the current agent (provider_id, model_id)."""
        if self.current_agent and self.current_agent.model is not None:
            return (
                self.current_agent.model.provider_id,
                self.current_agent.model.model_id,
            )
        return None

    def get_agent_steps(self) -> int | None:
        """Get the max steps for the current agent (if configured)."""
        if self.current_agent and self.current_agent.steps is not None:
            return self.current_agent.steps
        return None

    def get_current_agent(self) -> AgentInfo | None:
        """Get the current agent."""
        return self.current_agent

    def list_agents(self) -> list[AgentInfo]:
        """List available agents."""
        return self.nanocode_registry.list_primary()

    def get_disabled_tools(self) -> set:
        """Get tools disabled for the current agent."""
        from nanocode.agents import get_disabled_tools

        tools = [t.name for t in self.tool_registry.list_tools()]
        if self.current_agent is None:
            return set()
        return get_disabled_tools(tools, self.current_agent.permission)

    def _init_storage(self):
        """Initialize persistent storage."""
        self.storage = None
        self.session_id = None
        self.project_id = None
        self.config.get("storage.enabled", True)

    def _init_file_tracker(self):
        """Initialize file tracker for auto-reload on modification."""
        cache_dir = self.config.get("file_tracker.cache_dir")
        # Resolve relative paths to absolute, handling deleted cwd
        if cache_dir and not os.path.isabs(cache_dir):
            try:
                cache_dir = os.path.abspath(cache_dir)
            except OSError:
                cache_dir = None  # Will use default
        self.file_tracker = FileTracker(cache_dir)

    def _load_registry(self):
        """Ensure provider registry is loaded."""
        import asyncio
        from nanocode.provider_registry import get_provider_registry
        registry = get_provider_registry()
        if not registry._providers:
            asyncio.create_task(registry.initialize())
        return registry

    def _find_endpoint_config(self, default_connector: str, default_model: str):
        """Find matching endpoint config from connectors list."""
        endpoint_list = self.config.connectors.get(default_connector, [])
        if not isinstance(endpoint_list, list):
            endpoint_list = [endpoint_list]

        model_connector = default_model.split("/")[0] if "/" in default_model else default_connector

        for endpoint in endpoint_list:
            if isinstance(endpoint, dict) and endpoint.get("name") == model_connector:
                return endpoint.copy()
        if endpoint_list:
            return endpoint_list[0].copy()
        return None

    def _resolve_max_tokens(self, registry, model: str, default_connector: str, explicit: int | None) -> int | None:
        """Resolve max_tokens from registry if not explicitly set."""
        if explicit:
            return explicit
        from nanocode.llm.router import OUTPUT_TOKEN_MAX
        model_id = model if "/" in model else f"{default_connector}/{model}"
        model_spec = registry.get_model_by_full_id(model_id)
        if model_spec and model_spec.max_output_tokens > 0:
            return max(model_spec.max_output_tokens, OUTPUT_TOKEN_MAX)
        return None

    def _init_llm(self):
        """Initialize LLM provider from config + profiles.

        Resolution order:
          1. Connector endpoint config (self.config.connectors) for overrides
          2. Provider profile (nanocode/llm/profiles/) for defaults
          3. create_llm() backward-compat explicit provider mapping
        """
        default_model = self.config.get("llm.default_model")
        default_connector = self.config.default_connector
        user_agent = self.config.get("llm.user_agent", "nanocode/1.0")
        proxy = self.config.proxy

        if not default_connector:
            raise ValueError("No default_connector configured. Set llm.default_connector in config.yaml")
        if not default_model:
            raise ValueError("No default_model configured. Set llm.default_model in config.yaml")

        registry = self._load_registry()
        from nanocode.llm import create_llm

        provider_kwargs = {}

        endpoint_config = self._find_endpoint_config(default_connector, default_model)
        if endpoint_config:
            logger.info(f"Using connector: {default_connector}, model: {default_model}")
            logger.info(f"URL: {endpoint_config.get('base_url')}")
            max_tokens = endpoint_config.pop("max_tokens", None)
            endpoint_model = endpoint_config.pop("model", None)
            provider_kwargs.update(endpoint_config)
            max_tokens = self._resolve_max_tokens(registry, default_model, default_connector, max_tokens)
            if max_tokens is not None:
                provider_kwargs["max_tokens"] = max_tokens
            if endpoint_model:
                default_model = endpoint_model

        self.llm = create_llm(
            default_connector,
            model=default_model,
            user_agent=user_agent,
            proxy=proxy,
            debug=self.debug,
            **provider_kwargs,
        )

    def _init_pipeline(self):
        """Initialize the event-based agent pipeline (matching opencode).
        
        Must be called after _init_tools (for tool_registry) and _init_context (for context_manager).
        """
        self.pipeline = AgentPipeline(
            llm=self.llm,
            processor=SessionProcessor(headless=True),
            context_manager=self.context_manager,
            tool_registry=self.tool_registry,
        )
        logger.debug("Agent pipeline initialized (headless mode)")

    def _init_hooks(self):
        """Initialize hook system."""

        self.hook_manager = HookManager(base_dir=self.config.get("base_dir", "."))
        self.hook_manager.discover_hooks()
        logger.info(
            f"Hook system initialized: {len(sum(self.hook_manager.hooks.values(), []))} hooks loaded"
        )

    def _init_tools(self):
        """Initialize tool system."""
        from nanocode.agents.delegate import create_delegate_tool
        from nanocode.doom_loop import create_doom_loop_handler
        from nanocode.tools.task import create_task_tool

        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry, self.hook_manager)

        # fs_router will be created on first use (requires async context)
        self._fs_router = None

        register_builtin_tools(
            self.tool_registry, self.config.tools, self.file_tracker, self.lsp_manager,
            fs_router=self._fs_router,
            worktree=str(self.config.get("base_dir", ".")),
            session_id=getattr(self, "_session_id", "default")
        )

        self.task_tool = create_task_tool(
            self.nanocode_registry, self.permission_handler
        )
        self.task_tool.set_parent_agent(self)
        self.tool_registry.register(self.task_tool)

        self.delegate_tool = create_delegate_tool(
            self.tool_registry, self.config._data if hasattr(self.config, "_data") else {}
        )
        self.delegate_tool.set_parent_llm(self.llm)
        self.tool_registry.register(self.delegate_tool)

        self.tool_registry.register_handler("mcp", self._handle_mcp_tool)

        self.doom_loop_handler = create_doom_loop_handler()

    async def _ensure_fs_router(self):
        """Lazily create the file-system router (requires DB session)."""
        if self._fs_router is not None:
            return self._fs_router

        from nanocode import storage
        from nanocode.tools.backends import (
            DatabaseBackend,
            FileSystemRouter,
            LocalFSBackend,
        )

        workspace_backend = LocalFSBackend(self.config.get("base_dir", os.getcwd()))
        skills_backend = None
        memory_backend = None

        try:
            db = await storage.get_db()
            async with db.session() as session:
                skills_backend = DatabaseBackend(session, scope="user")
                memory_backend = DatabaseBackend(session, scope="user")
        except Exception as e:
            logger.warning(f"Failed to create DB backends: {e}")

        self._fs_router = FileSystemRouter(
            workspace_backend=workspace_backend,
            skills_backend=skills_backend,
            memory_backend=memory_backend,
        )

        # Inject fs_router into tools that support it
        for tool in self.tool_registry.list_tools():
            if hasattr(tool, "fs_router"):
                tool.fs_router = self._fs_router

        return self._fs_router

    def _init_skills(self):
        """Initialize skills system."""
        from nanocode.skills import create_skills_manager

        self.skills_manager = create_skills_manager()

    def _init_context(self):
        """Initialize context manager."""
        ctx_config = self.config.get("context", {})

        strategy_str = ctx_config.get("strategy", "sliding_window")
        strategy = ContextStrategy(strategy_str)

        session_id = ctx_config.get("session_id")

        self.context_manager = ContextManager(
            max_tokens=ctx_config.get("max_tokens", 8000),
            strategy=strategy,
            preserve_system=ctx_config.get("preserve_system", True),
            preserve_last_n=ctx_config.get("preserve_last_n", 3),
            llm=self.llm,
            session_id=session_id,
            storage=self.storage,
            tool_truncation=ctx_config.get("tool_truncation"),
            model=getattr(self.llm, "model", "gpt-4o"),
        )

        # Build composable system prompt
        if self._custom_system_prompt:
            final_prompt = self._custom_system_prompt
        elif system_prompt := ctx_config.get("system_prompt"):
            final_prompt = system_prompt
        else:
            final_prompt = self._build_system_prompt()

        self.context_manager.set_system_prompt(final_prompt)

    def _init_context_chips(self):
        """Initialize context chips system."""
        from nanocode.context_chips import ContextChipManager

        self.chip_manager = ContextChipManager(cwd=self.config.get("base_dir"))
        logger.info("Context chips system initialized")

    async def init_async(self):
        """Async initialization - load model registry from API."""
        await self.context_manager.init_async()

    def _get_agents_info(self) -> str:
        if not self.nanocode_registry:
            return ""
        lines = []
        for agent in self.nanocode_registry.list():
            mode = agent.mode.value if hasattr(agent.mode, "value") else agent.mode
            lines.append(f"- {agent.name}: {mode} agent (native={agent.native})")
        return "\n".join(lines)

    def _get_tools_info(self) -> str:
        if not self.tool_registry:
            return ""
        lines = []
        for name, tool in self.tool_registry._tools.items():
            desc = getattr(tool, "description", "") or ""
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def _get_mcp_info(self) -> str:
        if not hasattr(self, "mcp_manager") or not self.mcp_manager:
            return ""
        return "\n".join(f"- {name}" for name in self.mcp_manager._clients.keys())

    def _get_lsp_info(self) -> str:
        if not hasattr(self, "lsp_manager") or not self.lsp_manager:
            return ""
        return "\n".join(f"- {server_id}" for server_id in self.lsp_manager._servers.keys())

    def _get_skills_info(self) -> str:
        if not hasattr(self, "skills_manager") or not self.skills_manager:
            return ""
        lines = []
        for name, skill in self.skills_manager.skills.items():
            desc = getattr(skill, "description", "") or ""
            if len(desc) > 500:
                desc = desc[:500] + "..."
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def _build_system_prompt(self) -> str:
        """Build system prompt using Jinja2 templates and context chips."""
        cwd = os.getcwd()
        config_file = (
            str(self.config.config_path)
            if hasattr(self.config, "config_path")
            else "config.yaml"
        )

        # Use Jinja2 template rendering
        prompt = render_system_prompt(
            agents=self._get_agents_info(),
            tools=self._get_tools_info(),
            skills=self._get_skills_info(),
            mcp_servers=self._get_mcp_info(),
            lsp_servers=self._get_lsp_info(),
            cwd=cwd,
            config_file=config_file,
        )

        # Use context chips for additional context
        try:
            chip_manager = get_chip_manager()
            extra_context = chip_manager.build_context_section()
            prompt += extra_context
        except Exception as e:
            logger.debug(f"Context chips not available: {e}")

        # Add guidance about virtualized filesystem (Phase 4)
        prompt += """

# Filesystem & Tool Usage Guidelines
- Use `read`, `write`, and `edit` tools (NOT bash) to access:
  - `/skills/*` paths (skills are stored in database, not filesystem)
  - `/memory/*` paths (memories are stored in database, not filesystem)
- Bash tool is for workspace operations only (`/workspace/*` paths)
- Do NOT use bash commands (cat, ls, grep, etc.) to access skill or memory directories
- If you need to read a skill, use: `read("/skills/<name>/SKILL.md")`
- If you need to read memory, use: `read("/memory/MEMORY.md")`
"""

        # Check for additional .system_prompts/*.md files (except template.md)
        system_prompts_dir = Path(cwd) / ".system_prompts"
        if system_prompts_dir.exists():
            for f in sorted(system_prompts_dir.glob("*.md")):
                if f.name not in ("template.md",):
                    prompt += f"\n\n# From {f.name}\n"
                    prompt += f.read_text()
            for f in sorted(system_prompts_dir.glob("*.txt")):
                prompt += f"\n\n# From {f.name}\n"
                prompt += f.read_text()

        # Compose negative-prompting blocks
        try:
            from nanocode.prompts.blocks import compose_negative_blocks
            prompt += "\n\n" + compose_negative_blocks()
        except Exception:
            pass

        # Inject structural repo map for workspace awareness
        try:
            from nanocode.repo_map import generate_repo_map
            repo_map = generate_repo_map(Path(cwd))
            prompt += "\n\n" + repo_map
        except Exception:
            pass

        # Check for AGENTS.md in cwd or parent
        for agents_file in [Path(cwd) / "AGENTS.md", Path(cwd).parent / "AGENTS.md"]:
            if agents_file.exists():
                prompt += f"\n\n# From {agents_file.name}\n"
                prompt += agents_file.read_text()
                break

        # Check for GEMINI.md
        for gemini_file in [Path(cwd) / "GEMINI.md", Path(cwd).parent / "GEMINI.md"]:
            if gemini_file.exists():
                prompt += f"\n\n# From {gemini_file.name}\n"
                prompt += gemini_file.read_text()
                break

        return prompt

    def _init_mcp(self):
        """Initialize MCP connections."""
        self.mcp_manager = MCPManager(call_llm=self._mcp_sampling_call_llm)
        self._mcp_available = {}

        mcp_servers = self.config.mcp_servers
        for name, server_config in mcp_servers.items():
            self._mcp_available[name] = server_config.get("enabled", True)
            if self._mcp_available[name]:
                self.mcp_manager.add_server(name, server_config)

    async def _mcp_sampling_call_llm(
        self,
        messages: list,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: list[dict] | None = None,
    ):
        """Call the LLM for MCP sampling requests."""
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}, *messages]
        kwargs = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        return await self.llm.chat(messages, tools=tools, **kwargs)

    def _init_modified_files(self):
        """Initialize modified files tracker."""
        from nanocode.modified_files import ModifiedFilesTracker

        self.modified_files = ModifiedFilesTracker()

    def _init_planning(self):
        """Initialize planning system."""
        self.planner = TaskPlanner(self.llm, self.tool_registry)
        self.plan_executor = PlanExecutor(self.planner, self.tool_executor)
        self.plan_monitor = PlanMonitor(self.llm)

    def _init_drift_watchdog(self):
        """Initialize drift watchdog."""
        from nanocode.drift import create_drift_watchdog

        self.drift_watchdog = create_drift_watchdog(self.drift_mode)
        logger.debug(f"Drift watchdog initialized: mode={self.drift_mode}")

    def _init_multimodal(self):
        """Initialize multimodal support."""
        self.multimodal = MultimodalManager(self.llm)

    def _init_snapshot(self):
        """Initialize snapshot manager for git-based snapshots at step boundaries."""
        base_dir = str(self.config.get("base_dir", "."))
        session_id = getattr(self, "_session_id", None) or "default"
        self.snapshot_manager = create_snapshot_manager(base_dir, session_id)
        logger.debug(
            f"Snapshot manager initialized: {self.snapshot_manager._repo_dir}"
        )

    def _handle_mcp_tool(self, **kwargs):
        """Handle MCP tool calls."""
        return {"status": "not implemented"}

    def _check_context_overflow(self) -> tuple[bool, int]:
        """Check if context is approaching overflow. Returns (is_overflow, current_tokens)."""
        from nanocode.context import TokenCounter

        total = TokenCounter.count_messages_tokens(self.context_manager._messages)
        if self.context_manager._system_parts:
            total += sum(p.tokens for p in self.context_manager._system_parts)

        usable_context = (
            self.context_manager._context_limit - self.context_manager._reserved_tokens
        )
        is_overflow = total >= usable_context

        if is_overflow:
            logger.info(
                f"[{self.current_agent.name if self.current_agent else 'unknown'}] Context overflow: {total} >= {usable_context}"
            )

        return is_overflow, total

    def _find_prunable_tool_results(self, messages) -> tuple[list[tuple[int, int]], int]:
        """Find tool results that can be pruned. Returns (to_remove, pruned_tokens)."""
        PRUNE_PROTECT = 40000
        PRUNE_PROTECTED_TOOLS = {"skill"}

        total = 0
        pruned = 0
        to_remove = []
        turns = 0

        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.role == "user":
                turns += 1
            if turns < 2:
                continue
            if msg.role == "assistant" and getattr(msg, "summary", None):
                break

            for j in range(len(msg.parts) - 1, -1, -1):
                part = msg.parts[j]
                if part.part_type != MessagePartType.TOOL_RESULT:
                    continue
                if (getattr(part, "tool_name", None) or "") in PRUNE_PROTECTED_TOOLS:
                    continue
                estimate = len(str(part.content)) // 4
                total += estimate
                if total > PRUNE_PROTECT:
                    pruned += estimate
                    to_remove.append((i, j))

        return to_remove, pruned

    def _prune_old_tool_results(self) -> int:
        """Prune old tool results to free context space. Returns number of messages pruned."""
        messages = self.context_manager._messages
        if len(messages) < 6:
            return 0

        to_remove, pruned = self._find_prunable_tool_results(messages)
        if pruned <= 20000:
            return 0

        for i, j in reversed(to_remove):
            for i, j in reversed(to_remove):
                msg = messages[i]
                if j < len(msg.parts):
                    del msg.parts[j]
                    msg.tokens = max(1, msg.tokens - estimate)
            logger.info(
                f"[{self.current_agent.name if self.current_agent else 'unknown'}] Pruned {len(to_remove)} tool results ({pruned} tokens)"
            )
            return len(to_remove)

    async def _check_pending_todos(self) -> list[str]:
        """Check for pending todos that need completion. Returns list of pending todo contents."""
        session_id = getattr(self, "_session_id", None)
        if not session_id:
            return []

        todo_service = get_todo_service()
        todos = todo_service.get_todos(session_id)
        pending = [t.content for t in todos if t.status == "pending"]
        return pending

    async def _compact_context(self) -> str:
        """Compact context by summarizing old messages. Returns summary text."""
        if not self.llm:
            return ""

        messages = self.context_manager._messages
        if len(messages) < 4:
            return ""

        recent = messages[-self.context_manager.preserve_last_n :]
        older = messages[: -self.context_manager.preserve_last_n]

        if not older:
            return ""

        conversation = "\n".join(f"{m.role}: {m.get_text_content()}" for m in older)

        prompt = f"""Provide a detailed summary for continuing our conversation.
Focus on information that would be helpful for continuing the conversation, including what we did, what we're doing, which files we're working on, and what we're going to do next.
The summary that you construct will be used so that another agent can read it and continue the work.
Do not call any tools. Respond only with the summary text.

## Template
## Goal
[What goal(s) is the user trying to accomplish?]

## Instructions
- [What important instructions did the user give you that are relevant]
- [If there is a plan or spec, include information about it so next agent can continue using it]

## Discoveries
[What notable things were learned during this conversation that would be useful for the next agent to know when continuing the work]

## Accomplished
[What work has been completed, what work is still in progress, and what work is left?]

## Relevant files / directories
[Construct a structured list of relevant files that have been read, edited, or created that pertain to the task at hand.]

---
Conversation:
{conversation}
"""

        try:
            from nanocode.llm import Message as LLMMessage

            response = await self.llm.chat([LLMMessage("user", prompt)])
            summary_text = (
                response.content
                or f"[{len(older)} messages from earlier in the conversation]"
            )

            self.context_manager._messages = [msg for msg in recent]
            self.context_manager.add_message(
                "assistant", f"[Previous conversation summarized]\n\n{summary_text}"
            )

            logger.info(
                f"[{self.current_agent.name if self.current_agent else 'unknown'}] Context compacted: {len(older)} messages summarized"
            )
            return summary_text
        except Exception as e:
            logger.warning(
                f"[{self.current_agent.name}] Context compaction failed: {e}"
            )
            return ""

    async def _chat_with_retry(
        self,
        messages: list,
        tools: list = None,
        max_retries: int = 3,
        on_token: callable = None,
    ) -> Any:
        """Chat with retry on tool ID mismatch errors and exponential backoff."""
        import asyncio

        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                return await self.llm.chat(
                    messages=messages, tools=tools, on_token=on_token
                )
            except Exception as e:
                error_str = str(e)
                retryable, reason = is_retryable_error(e)

                if not retryable:
                    logger.error(
                        f"[{self.current_agent.name if self.current_agent else 'unknown'}] Non-retryable error: {error_str[:500]}"
                    )
                    raise

                retry_count += 1

                if retry_count >= max_retries:
                    logger.error(
                        f"[{self.current_agent.name if self.current_agent else 'unknown'}] Max retries ({max_retries}) reached"
                    )
                    logger.error(
                        f"[{self.current_agent.name}] Last error: {error_str[:500]}"
                    )
                    raise

                delay = calculate_retry_delay(retry_count, error_str)
                logger.warning(
                    f"[{self.current_agent.name if self.current_agent else 'unknown'}] Retry {retry_count}/{max_retries}: {reason}, waiting {delay:.1f}s"
                )

                await asyncio.sleep(delay)

                fresh_messages = []
                seen_user = False
                for msg in messages:
                    role = (
                        msg.get("role")
                        if isinstance(msg, dict)
                        else getattr(msg, "role", None)
                    )
                    if role == "system":
                        fresh_messages.append(
                            msg if isinstance(msg, dict) else msg.to_dict()
                        )
                    elif role == "user" and not seen_user:
                        fresh_messages.append(
                            msg if isinstance(msg, dict) else msg.to_dict()
                        )
                        seen_user = True

                result = await self.llm.chat(
                    messages=fresh_messages, tools=tools, on_token=on_token
                )
                return result

        raise last_error or Exception("Max retries exceeded")

    def _extract_commands_from_output(self, output: str) -> list[str]:
        """Extract executable commands from file content (bash, curl, etc)."""
        import re

        if not output:
            return []
        commands = []
        # Find bash code blocks
        bash_blocks = re.findall(r"```bash\n(.*?)```", output, re.DOTALL)
        for block in bash_blocks:
            for line in block.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    commands.append(line)
        # Also find inline commands (command at start of line)
        inline = re.findall(
            r"^\s*(mkdir|curl|wget|pip|npm|yarn|apt|yum)\s+\S+", output, re.MULTILINE
        )
        for cmd in inline:
            commands.append(cmd.strip())
        return commands

    async def _save_checkpoint(self, step_number: int, tool_calls: list = None):
        """Save agent state for durable execution.

        This implements the durable execution pattern from the blog post.
        Each tool-call turn is checkpointed so the loop can resume after restarts.
        """
        from nanocode import storage
        from nanocode.storage.models import AgentCheckpoint

        if not self.context_manager or not hasattr(self.context_manager, "session_id"):
            return

        session_id = self.context_manager.session_id
        if not session_id:
            return

        try:
            db = await storage.get_db()
            async with db.session() as session:
                import uuid
                from datetime import datetime

                state_data = {
                    "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in (tool_calls or [])],
                    "agent_name": self.current_agent.name if self.current_agent else None,
                    "state": self.state.state if hasattr(self.state, "state") else str(self.state),
                    "task": getattr(self.state, "task", None),
                }

                messages = self.context_manager.prepare_messages() if hasattr(self.context_manager, "prepare_messages") else []
                messages_snapshot = messages[:50]  # Truncate to avoid huge blobs

                checkpoint = AgentCheckpoint(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    step_number=step_number,
                    state_data=state_data,
                    messages_snapshot=messages_snapshot,
                    created_at=datetime.now(),
                )
                session.add(checkpoint)
                await session.commit()
                logger.debug(f"Checkpoint saved: step {step_number} for session {session_id}")

        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")

    async def _load_latest_checkpoint(self, session_id: str) -> dict | None:
        """Load the latest checkpoint for a session."""
        from sqlalchemy import desc, select

        from nanocode import storage
        from nanocode.storage.models import AgentCheckpoint

        try:
            db = await storage.get_db()
            async with db.session() as session:
                stmt = (
                    select(AgentCheckpoint)
                    .where(AgentCheckpoint.session_id == session_id)
                    .order_by(desc(AgentCheckpoint.step_number))
                    .limit(1)
                )
                result = await session.execute(stmt)
                cp = result.scalar_one_or_none()
                if cp:
                    return {
                        "step_number": cp.step_number,
                        "state_data": cp.state_data,
                        "messages_snapshot": cp.messages_snapshot,
                        "created_at": cp.created_at,
                    }
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
        return None

    async def _handle_doom_loop(self, tool_name: str, args: dict, agent_name: str) -> tuple[bool, str | None]:
        """Handle doom loop detection. Returns (blocked, error_message)."""
        if self.yolo:
            return False, None

        if not self.doom_loop_handler.check_tool_call(tool_name, args):
            return False, None

        loop_info = self.doom_loop_handler.detection.get_loop_info()
        if loop_info and loop_info.get("show_warning", True):
            warning = self.doom_loop_handler.get_loop_warning()
            if warning:
                logger.warning(f"[{agent_name}] DOOM LOOP DETECTED for '{tool_name}': {warning}")
                if self.debug:
                    console.print(f"\n[red]{warning}[/red]\n")

        if not self.current_agent:
            return False, None

        doom_action = self.permission_handler.check_permission(
            self.current_agent, "doom_loop", {"tool": tool_name, "args": args},
        )

        if doom_action == PermissionAction.DENY:
            msg = f"Error: Doom loop detected - tool '{tool_name}' called repeatedly with same arguments. Permission denied."
            logger.warning(f"[{agent_name}] Doom loop permission DENIED for '{tool_name}'")
            return True, msg

        if doom_action == PermissionAction.ASK:
            try:
                await self.permission_handler.request_permission(
                    self.current_agent, "doom_loop", {"tool": tool_name, "args": args},
                )
                self.doom_loop_handler.reset()
                return False, None
            except Exception as e:
                logger.error(f"[{agent_name}] Doom loop permission denied: {e}")
                return True, f"Error: Doom loop detected - permission denied by user."

        self.doom_loop_handler.reset(tool_name)
        return False, None

    def _call_tool_start_callback(self, tool_name: str, args: dict, agent_name: str):
        """Call on_tool_start callback if set."""
        if hasattr(self, "_on_tool_start") and self._on_tool_start:
            try:
                self._on_tool_start(tool_name, args)
            except Exception as e:
                logger.warning(f"[{agent_name}] on_tool_start callback failed: {e}")

    def _call_tool_complete_callback(self, tool_name: str, result, agent_name: str):
        """Call on_tool_complete callback if set."""
        if hasattr(self, "_on_tool_complete") and self._on_tool_complete:
            try:
                self._on_tool_complete(tool_name, self.tool_executor.format_result(result))
            except Exception as e:
                logger.warning(f"[{agent_name}] on_tool_complete callback failed: {e}")

    async def _check_tool_permission(self, tool_name: str, args: dict, agent_name: str) -> PermissionAction | None:
        """Check tool permission. Returns None if no agent (allow), otherwise the action."""
        if not self.current_agent:
            return PermissionAction.ALLOW
        if self.yolo:
            logger.debug(f"[YOLO] Auto-allowing '{tool_name}'")
            return PermissionAction.ALLOW
        action = self.permission_handler.check_permission(self.current_agent, tool_name, args)
        logger.debug(f"[{agent_name}] Permission check for '{tool_name}': {action.value}")
        return action

    async def _handle_tool_calls(self, tool_calls: list) -> list[dict]:
        """Handle tool calls from LLM with permission checking and doom loop detection."""
        agent_name = self.current_agent.name if self.current_agent else "unknown"
        import time
        start = time.monotonic()
        logger.info(f"[{agent_name}] Handling {len(tool_calls)} tool call(s)")

        try:
            step_number = getattr(self, "_current_step", 0) + 1
            self._current_step = step_number
            await self._save_checkpoint(step_number, tool_calls)
        except Exception:
            pass

        results = []
        for i, tc in enumerate(tool_calls):
            tool_name = tc.name
            args = tc.arguments
            logger.debug(f"[{agent_name}] Tool call {i + 1}/{len(tool_calls)}: {tool_name}({args})")

            self._call_tool_start_callback(tool_name, args, agent_name)

            doom_blocked, doom_error = await self._handle_doom_loop(tool_name, args, agent_name)
            if doom_blocked:
                results.append({"tool_call_id": tc.id, "tool_name": tool_name, "result": doom_error, "success": False})
                continue

            action = await self._check_tool_permission(tool_name, args, agent_name)
            if action == PermissionAction.DENY:
                logger.warning(f"[{agent_name}] Permission DENIED for '{tool_name}'")
                results.append({"tool_call_id": tc.id, "tool_name": tool_name, "result": f"Error: Permission denied for tool '{tool_name}'", "success": False})
                continue
            if action == PermissionAction.ASK:
                logger.info(f"[{agent_name}] Requesting permission for '{tool_name}'")
                try:
                    await self.permission_handler.request_permission(self.current_agent, tool_name, args)
                    logger.debug(f"[{agent_name}] Permission granted for '{tool_name}'")
                except Exception as e:
                    logger.error(f"[{agent_name}] Permission request failed for '{tool_name}': {e}")
                    results.append({"tool_call_id": tc.id, "tool_name": tool_name, "result": f"Error: {str(e)}", "success": False})
                    continue

            logger.debug(f"[{agent_name}] Executing tool: {tool_name}")
            exec_result = await self.tool_executor.execute(tool_name, args, self._session_id, agent_name)
            self._call_tool_complete_callback(tool_name, exec_result, agent_name)

            tool_logger.debug(f"[{agent_name}] Tool call: {tool_name}({args}) -> success={exec_result.success}")
            results.append({
                "tool_call_id": tc.id,
                "tool_name": tool_name,
                "arguments": args,
                "result": self.tool_executor.format_result(exec_result),
                "success": exec_result.success,
            })

        logger.debug(f"[{agent_name}] Finished handling {len(tool_calls)} tool call(s) in {time.monotonic() - start:.2f}s")
        return results

    async def _spawn_background_review(self):
        """Fire-and-forget background review of the just-completed turn.

        Runs a lightweight LLM call that evaluates whether memory or
        skill updates are warranted. The result is logged and optionally
        surfaced to the user.
        """
        if not self._review_enabled:
            return
        if not self._review_memory and not self._review_skills:
            return

        from nanocode.agents.review import spawn_background_review

        messages_snapshot = self.context_manager.prepare_messages()
        if not messages_snapshot:
            return

        try:
            summary = await spawn_background_review(
                self,
                messages_snapshot,
                review_memory=self._review_memory,
                review_skills=self._review_skills,
            )
            if summary:
                logger.info("[background review] %s", summary)
        except Exception as e:
            logger.debug("Background review failed: %s", e)

    def _format_thinking(self, thinking: str) -> str:
        """Format thinking content for display."""
        lines = thinking.strip().split("\n")
        formatted = "\n".join(f"  {line}" for line in lines)
        return f"[thought]| Thinking:[/thought]\n{formatted}"

    def _get_cache_key(self, messages: list, tools: list[dict] | None) -> str:
        """Generate a cache key from messages and tools."""
        parts = []
        for msg in messages:
            if hasattr(msg, "to_dict"):
                parts.append(json.dumps(msg.to_dict(), sort_keys=True))
            elif isinstance(msg, dict):
                parts.append(json.dumps(msg, sort_keys=True))

        if tools:
            parts.append(json.dumps(tools, sort_keys=True))

        key = "".join(parts)

        # DEBUG: Log what we're hashing
        logger.warning(f"[CACHE KEY DEBUG] Number of messages: {len(messages)}")
        for i, msg in enumerate(messages):
            if hasattr(msg, "to_dict"):
                d = msg.to_dict()
            elif isinstance(msg, dict):
                d = msg
            else:
                d = {}
            role = d.get("role", "?")
            content = d.get("content", "") or ""
            if isinstance(content, list):
                content = str(content[:2])  # First 2 items only
            logger.warning(
                f"[CACHE KEY DEBUG] Msg {i}: role={role}, content_len={len(str(content))}, content_preview={str(content)[:80]}"
            )

        cache_key = hashlib.sha256(key.encode()).hexdigest()
        logger.warning(f"[CACHE KEY DEBUG] Final cache key: {cache_key}")
        return cache_key

    def _messages_to_text(self, messages: list) -> str:
        """Convert messages to a text string for caching."""
        parts = []
        for msg in messages:
            if hasattr(msg, "content"):
                parts.append(f"{msg.role}: {msg.content}")
            elif isinstance(msg, dict):
                parts.append(f"{msg.get('role', 'unknown')}: {msg.get('content', '')}")
        return "\n".join(parts)

    def _check_cache(
        self, messages: list, tools: list[dict] | None
    ):
        """Check if we have a cached response for these messages."""
        if not self.prompt_cache:
            return None

        cache_key = self._get_cache_key(messages, tools)
        cached = self.prompt_cache.get(cache_key)

        if cached:
            cache_logger.info(
                f"Cache HIT: {len(messages)} messages, {len(cached.content)} chars"
            )
            # Convert cached response to LLMResponse
            tool_calls = []
            if cached.tool_calls:
                from nanocode.tools import ToolCall
                for tc in cached.tool_calls:
                    tool_calls.append(
                        ToolCall(name=tc.get("name", ""), arguments=tc.get("arguments", {}))
                    )
            
            from nanocode.llm.base import LLMResponse
            return LLMResponse(
                content=cached.content,
                thinking=cached.thinking,
                tool_calls=tool_calls,
            )
        return None

    def _put_cache(
        self, messages: list, tools: list[dict] | None, response
    ) -> None:
        """Store the response in cache.
        
        Accepts either LLMResponse or pipeline Message objects.
        """
        if not self.prompt_cache:
            return

        cache_key = self._get_cache_key(messages, tools)

        # Handle both LLMResponse and pipeline Message objects
        if hasattr(response, "content"):
            # LLMResponse object
            content = response.content
            thinking = getattr(response, "thinking", None)
            tool_calls = getattr(response, "tool_calls", [])
            tool_calls_data = []
            if tool_calls:
                tool_calls_data = [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in tool_calls
                ]
        elif hasattr(response, "parts"):
            # Pipeline Message object
            from nanocode.agent_pipeline import AgentPipeline
            pipeline = AgentPipeline(llm=None)
            content = pipeline.get_text_content(response)
            thinking = "\n\n".join(pipeline.get_all_thinking(response))
            tool_calls = pipeline.get_tool_calls(response)
            tool_calls_data = [
                {"name": tc.name, "arguments": tc.arguments}
                for tc in tool_calls
            ]
        else:
            logger.warning("Unknown response type for caching")
            return

        cached = CachedResponse(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls_data,
            model=getattr(self.llm, "model", None),
        )

        self.prompt_cache.put(cache_key, cached)
        cache_logger.info(
            f"Cached: {len(messages)} messages, {len(content) if content else 0} chars"
        )

    async def process_input(
        self,
        user_input: str,
        show_thinking: bool = True,
        show_messages: bool = False,
        on_token: callable = None,
        on_tool_start: callable = None,
        on_tool_complete: callable = None,
    ) -> str:
        """Process a user input through the agent."""
        import traceback

        try:
            return await self._process_input_impl(
                user_input,
                show_thinking,
                show_messages,
                on_token=on_token,
                on_tool_start=on_tool_start,
                on_tool_complete=on_tool_complete,
            )
        except asyncio.CancelledError:
            logger.error("LLM request cancelled (timeout)")
            raise
        except Exception as e:
            if "Expecting value" in str(e) or isinstance(e, json.JSONDecodeError):
                logger.error(f"JSON parsing error in process_input: {e}")
                return f"Error: Failed to parse LLM response - {e}"
            traceback.print_exc()
            raise

    def _setup_processing(self, user_input: str, on_token, on_tool_start, on_tool_complete) -> str:
        """Initialize state for a processing session. Returns agent_name."""
        agent_name = self.current_agent.name if self.current_agent else "unknown"
        if self._session_logger:
            self._session_logger.info(f"[{agent_name}] Processing input: {user_input}")
        else:
            logger.info(f"[{agent_name}] Processing input: {user_input}")

        self.state.state = AgentState.EXECUTING
        self.state.task = user_input

        if hasattr(self, "task_tool"):
            self.task_tool.update_description(self.current_agent)

        self.context_manager.add_message("user", user_input)
        logger.debug(f"[{agent_name}] User message added to context")

        self._on_token = on_token
        self._on_tool_start = on_tool_start
        self._on_tool_complete = on_tool_complete
        return agent_name

    def _display_llm_request(self, messages: list, show_messages: bool):
        """Display LLM request info for debugging."""
        if self.debug:
            console.print(f"\n[debug][DEBUG] Sending {len(messages)} messages to LLM...[/debug]")
            for i, msg in enumerate(messages):
                role = msg.role if hasattr(msg, "role") else msg.get("role", "?")
                if role == "system":
                    continue
                content = msg.content if hasattr(msg, "content") else str(msg.get("content", ""))
                display = content[:200] + "..." if len(content) > 200 else content
                console.print(f"  [dim]{i}: {role}: {display}[/dim]")

        if show_messages:
            console.print("\n[debug]=== LLM REQUEST ===[/debug]")
            for i, msg in enumerate(messages):
                content = msg.content if hasattr(msg, "content") else str(msg.get("content", ""))
                role = msg.role if hasattr(msg, "role") else msg.get("role", "?")
                print(f"\n[{i}] {role.upper()}:")
                print(content if len(content) > 0 else content)
            print("\n")

    async def _make_first_llm_request(self, messages: list, tools: list, user_input: str, agent_name: str):
        """Make first LLM request or return cached response."""
        _trace("_make_first_llm_request START")
        cached_response = self._check_cache(messages, tools)
        _trace(f"  cache_check: {'HIT' if cached_response else 'MISS'}")
        logger.debug(f"[DEBUG] User input: '{user_input}'")
        logger.debug(f"[DEBUG] Context messages before LLM: {len(messages)}")
        if cached_response:
            cache_logger.warning(f"[{agent_name}] Using CACHED response (this is a bug if input changed!)")
            logger.warning(f"[{agent_name}] Cache hit! Messages: {len(messages)}, User input: {user_input[:50]}")
            if self.debug:
                console.print("\n[warning][WARN] CACHE HIT - Previous response reused![/warning]")
            self._last_message = None
            return cached_response

        session_id = getattr(self.context_manager, "session_id", "default")
        _trace(f"  calling pipeline.process_stream (session={session_id}, n_messages={len(messages)})")
        message = await self.pipeline.process_stream(
            session_id=session_id,
            messages=messages,
            tools=tools,
            on_token=self._on_token,
        )
        _trace(f"  pipeline returned, message has {len(message.parts)} parts")
        self._last_message = message
        self._put_cache(messages, tools, message)
        response = self.pipeline.to_llm_response(message)
        _trace(f"  LLM response: has_tool_calls={response.has_tool_calls}, content_len={len(response.content or '')}, error={response.error!r}")
        if response.error:
            err_msg = f"LLM API error: {response.error}"
            logger.error(f"[{agent_name}] {err_msg}")
            raise RuntimeError(err_msg)
        logger.info(f"[{agent_name}] LLM response received")
        logger.info(f"[{agent_name}] Thinking: {response.thinking[:100] if response.thinking else 'None'}...")
        return response

    def _display_llm_response(self, response, show_messages: bool, show_thinking: bool):
        """Display LLM response info for debugging."""
        if self.debug:
            console.print("\n[debug][DEBUG] LLM Response:[/debug]")
            if response.thinking:
                console.print(f"  [thought]| Thinking:[/thought]\n{response.thinking}")
            if response.has_tool_calls:
                console.print(f"  [tool_call]Tool Calls: {[tc.name for tc in response.tool_calls]}[/tool_call]")
            else:
                console.print(f"  [content]Content: {response.content}[/content]")

        if show_messages:
            console.print("\n[debug]=== LLM RESPONSE ===[/debug]")
            if response.thinking:
                console.print(f"\n[thought]| Thinking:[/thought]\n{response.thinking}")
            if response.has_tool_calls:
                print("\nTool Calls:")
                for tc in response.tool_calls:
                    print(f"  - {tc.name}: {tc.arguments}")
            print(f"\nContent:\n{response.content if response.content else '(empty)'}")
            print()

        if response.thinking and show_thinking and self.debug:
            console.print(self._format_thinking(response.thinking))

    async def _execute_tool_iteration(
        self, iteration: int, max_agent_steps: int, final_response, tool_results_history: list, show_thinking: bool, agent_name: str
    ):
        """Run a single tool-call iteration. Returns next final_response."""
        is_last_step = iteration >= max_agent_steps

        if hasattr(self, "snapshot_manager") and getattr(self.snapshot_manager, "enabled", True):
            try:
                last_snapshot_hash = await self.snapshot_manager.track()
                if last_snapshot_hash and self.debug:
                    logger.debug(f"[{agent_name}] Snapshot taken: {last_snapshot_hash[:8]}...")
            except Exception as e:
                logger.debug(f"[{agent_name}] Snapshot failed: {e}")

        logger.info(f"[{agent_name}] Tool call iteration {iteration}/{max_agent_steps}: {[tc.name for tc in final_response.tool_calls]}")

        tool_results = await self._handle_tool_calls(final_response.tool_calls)
        tool_results_history.extend(tool_results)

        for tr in tool_results:
            result_content = self.context_manager.truncate_tool_result(tr["result"])
            self.context_manager.add_tool_result(tr["tool_name"], tr["tool_call_id"], result_content)

        messages = self.context_manager.prepare_messages()

        is_overflow, tokens = self._check_context_overflow()
        if is_overflow:
            logger.info(f"[{agent_name}] Context overflow in iteration {iteration}")
            pruned = self._prune_old_tool_results()
            if pruned == 0:
                await self._compact_context()
            messages = self.context_manager.prepare_messages()

        if final_response.thinking:
            self._all_thinking.append(final_response.thinking)
            if show_thinking and self.debug:
                console.print(self._format_thinking(final_response.thinking))

        if is_last_step:
            messages.append({"role": "user", "content": MAX_STEPS_MESSAGE})
            logger.debug(f"[{agent_name}] Forcing text-only response (max steps reached)")
            return await self._chat_with_pipeline(messages, None, on_token=self._on_token)

        return await self._chat_with_pipeline(messages, tools, on_token=self._on_token)

    def _format_tool_result_for_augmented(self, tr: dict) -> str:
        """Format a single tool result for augmented content (like opencode)."""
        tool_name = tr["tool_name"]
        args = tr.get("arguments", {})
        result_str = str(tr["result"])
        if tool_name == "bash":
            return f"\n$ {args.get('command', '')}\n  {result_str}"
        elif tool_name in ("glob", "grep"):
            pattern = args.get("pattern", "")
            root = args.get("path", "")
            suffix = f" in {root}" if root else ""
            icon = {"glob": "✱", "grep": "✱"}.get(tool_name, "✱")
            return f"\n{icon} {tool_name.capitalize()} \"{pattern}\"{suffix}\n  {result_str}"
        elif tool_name == "read":
            filepath = args.get("path", "")
            extra = ""
            if "offset" in args or "limit" in args:
                opts = ", ".join(f"{k}={v}" for k, v in args.items() if k in ("offset", "limit"))
                extra = f" [{opts}]"
            return f"\n→ Read {filepath}{extra}\n  {result_str}"
        elif tool_name == "write":
            return f"\n← Write {args.get('path', '')}\n  {result_str}"
        elif tool_name == "edit":
            return f"\n← Edit {args.get('path', '')}\n  {result_str}"
        elif tool_name == "webfetch":
            return f"\n% WebFetch {args.get('url', '')}\n  {result_str}"
        elif tool_name == "skill":
            return f"\n→ Skill \"{args.get('name', '')}\"\n  {result_str}"
        return f"\n⚙ {tool_name}\n  {result_str}"

    def _build_augmented_content(self, content: str, response, tool_results_history: list, show_messages: bool) -> str:
        """Build augmented content with thinking and tool use info."""
        augmented = content
        if response.thinking:
            augmented += f"\n\n[thought]| Thinking:[/thought] {response.thinking}"

        if tool_results_history:
            tool_info = "".join(self._format_tool_result_for_augmented(tr) for tr in tool_results_history)
            augmented += tool_info
            if show_messages:
                tool_summary = "\n\n[Tool Summary]"
                for tr in tool_results_history:
                    tool_summary += f"\n- {tr['tool_name']}: executed"
                augmented += tool_summary
        return augmented

    async def _handle_post_tool_continuation(self, tool_results_history: list, tools: list, agent_name: str) -> tuple[str, list]:
        """After tool loop, force continuation to write complete content. Returns (content, updated_history)."""
        messages = self.context_manager.prepare_messages()
        messages.append({
            "role": "user",
            "content": "IMPORTANT: 1) Use 'todo(action='write', todos=[...])' to track your progress on each step. 2) Write COMPLETE content to every file you created. Do NOT use 'touch' or create empty files. Use the 'write' tool with full content for: README.md, pyproject.toml, source files, test files, etc.",
        })
        max_agent_steps = self.get_agent_steps() if self.get_agent_steps() else 20
        iteration = 0
        while iteration < max_agent_steps:
            iteration += 1
            final_response = await self._chat_with_pipeline(messages, tools, on_token=self._on_token)
            if not final_response.has_tool_calls:
                content = final_response.content
                if content:
                    self.context_manager.add_message("assistant", content)
                return content, tool_results_history
            tool_results = await self._handle_tool_calls(final_response.tool_calls)
            tool_results_history.extend(tool_results)
            for tr in tool_results:
                result_content = self.context_manager.truncate_tool_result(tr["result"])
                self.context_manager.add_tool_result(tr["tool_name"], tr["tool_call_id"], result_content)
            self.context_manager.add_message("assistant", None, tool_calls=final_response.tool_calls)
            messages = self.context_manager.prepare_messages()
            if any("mkdir" in str(tr.get("result", "")) or "touch" in str(tr.get("result", "")) for tr in tool_results):
                messages.append({"role": "user", "content": "Write COMPLETE content to all files and update your todo list with 'todo(action='write', todos=[...])'. Every file must have full, working content."})
            else:
                messages.append({"role": "user", "content": "Update todo list with 'todo(action='write', todos=[...])' and continue executing the next step. Write complete content to all files."})
        return final_response.content, tool_results_history

    async def _auto_execute_commands(self, tool_results: list[dict], agent_name: str):
        """Auto-execute commands found in read tool results."""
        for tr in tool_results:
            if not (self.auto_execute and tr["tool_name"] == "read"):
                continue
            result_content = self.context_manager.truncate_tool_result(tr["result"])
            commands = self._extract_commands_from_output(result_content)
            if not commands:
                continue
            logger.info(f"[{agent_name}] Auto-executing {len(commands)} commands from file content")
            for cmd in commands:
                try:
                    exec_result = await self.tool_registry.get("bash").execute(command=cmd)
                    logger.info(f"[{agent_name}] Auto-exec '{cmd[:30]}...': {exec_result.success}")
                except Exception as e:
                    logger.warning(f"[{agent_name}] Auto-exec failed: {e}")

    async def _handle_context_overflow(self, messages: list, agent_name: str) -> list:
        """Handle context overflow by pruning or compacting. Returns updated messages."""
        is_overflow, tokens = self._check_context_overflow()
        if not is_overflow:
            return messages
        logger.info(f"[{agent_name}] Context overflow detected ({tokens} tokens)")
        pruned = self._prune_old_tool_results()
        if pruned == 0:
            await self._compact_context()
            return messages
        return self.context_manager.prepare_messages()

    async def _run_tool_iteration_loop(
        self, initial_response, tools, tool_results_history, show_thinking, agent_name
    ) -> tuple[str, list]:
        """Run the tool iteration loop. Returns (content, tool_results_history)."""
        messages = self.context_manager.prepare_messages()
        messages = await self._handle_context_overflow(messages, agent_name)

        final_response = await self._chat_with_pipeline(messages, tools)
        if final_response.thinking:
            self._all_thinking.append(final_response.thinking)
            if show_thinking and self.debug:
                console.print(self._format_thinking(final_response.thinking))

        max_agent_steps = self.get_agent_steps() if self.get_agent_steps() else 20
        iteration = 0
        while final_response.has_tool_calls and iteration < max_agent_steps:
            iteration += 1
            final_response = await self._execute_tool_iteration(
                iteration, max_agent_steps, final_response, tool_results_history, show_thinking, agent_name
            )

        if iteration >= max_agent_steps:
            logger.warning(f"[{agent_name}] Hit max iterations ({max_agent_steps})")
        elif final_response.has_tool_calls:
            self.context_manager.add_message("user", AUTO_CONTINUE_MESSAGE)
            logger.info(f"[{agent_name}] Auto-continue: injected continue message")
            messages = self.context_manager.prepare_messages()
            final_response = await self._chat_with_pipeline(messages, tools, on_token=self._on_token)
            if not final_response.has_tool_calls:
                self.context_manager.add_message("assistant", final_response.content)
                return final_response.content, tool_results_history

        return final_response.content, tool_results_history

    async def _handle_tool_call_response_flow(
        self, response, tools, show_thinking, agent_name
    ) -> tuple[str, list]:
        """Handle the tool call response flow. Returns (content, tool_results_history)."""
        logger.info(f"[{agent_name}] LLM requested {len(response.tool_calls)} tool call(s): {[tc.name for tc in response.tool_calls]}")
        if self.debug:
            console.print(f"\n[debug][DEBUG] Handling {len(response.tool_calls)} tool calls...[/debug]")

        tool_results_history: list = []
        tool_results = await self._handle_tool_calls(response.tool_calls)
        tool_results_history.extend(tool_results)
        if hasattr(self, "_last_tool_results"):
            self._last_tool_results.extend(tool_results)

        for tr in tool_results:
            if self.debug:
                console.print(f"\n[debug][DEBUG] Tool {tr['tool_name']} result:[/debug] {tr['result']}")

        self.context_manager.add_message("assistant", None, tool_calls=response.tool_calls)
        for tr in tool_results:
            result_content = self.context_manager.truncate_tool_result(tr["result"])
            self.context_manager.add_tool_result(tr["tool_name"], tr["tool_call_id"], result_content)

        await self._auto_execute_commands(tool_results, agent_name)

        return await self._run_tool_iteration_loop(
            response, tools, tool_results_history, show_thinking, agent_name
        )

    async def _check_and_handle_detected_commands(self, content: str, agent_name: str) -> str:
        """Check for text-to-tool commands and reprompt signals. Returns possibly modified content."""
        detected = detect_commands_in_text(content)
        if detected:
            logger.warning(f"[{agent_name}] Detected {len(detected)} command(s) in text that were not executed")
            if self.debug:
                console.print("\n[warning][WARN] Detected unexecuted commands:[/warning]")
                for cmd in detected:
                    console.print(f"  - [{cmd.tool_name}] {cmd.command[:60]}...")

        should_reprompt, reason = should_reprompt_for_tools(content, tools_were_expected=bool(self.tool_registry.get_schemas()))
        if should_reprompt:
            logger.warning(f"[{agent_name}] Model didn't use tools: {reason}")
            if self.debug:
                console.print(f"\n[warning][WARN] {reason}[/warning]")
            warning_msg = format_detected_commands_message(detected)
            if warning_msg:
                content += warning_msg
        return content

    async def _handle_pending_todos_flow(self, augmented: str, tools, agent_name) -> str:
        """Handle pending todos by prompting the model to complete them."""
        pending_todos = await self._check_pending_todos()
        if not pending_todos:
            return augmented
        logger.info(f"[{agent_name}] {len(pending_todos)} pending todos, prompting to complete")
        messages = self.context_manager.prepare_messages()
        messages.append({
            "role": "user",
            "content": f"You have {len(pending_todos)} pending todo(s). Please complete them before responding:\n" +
                      "\n".join(f"- {t}" for t in pending_todos)
        })
        continuation = await self._chat_with_pipeline(messages, tools)
        if continuation and continuation.content:
            self.context_manager.add_message("assistant", continuation.content)
            augmented += f"\n\n{continuation.content}"
            if continuation.has_tool_calls:
                more_results = await self._handle_tool_calls(continuation.tool_calls)
        return augmented

    async def _process_input_impl(
        self,
        user_input: str,
        show_thinking: bool = True,
        show_messages: bool = False,
        on_token: callable = None,
        on_tool_start: callable = None,
        on_tool_complete: callable = None,
    ) -> str:
        """Process a user input through the agent."""
        _trace("_process_input_impl ENTERED")
        agent_name = self._setup_processing(user_input, on_token, on_tool_start, on_tool_complete)
        _trace(f"_process_input_impl agent_name={agent_name}")
        tool_results_history = []
        _start_time = time.monotonic()

        try:
            tools = self.tool_registry.get_schemas()
            logger.debug(f"[{agent_name}] Total tools available: {len(tools)}")
            logger.debug(f"[{agent_name}] === FIRST LLM REQUEST ===")
            messages = self.context_manager.prepare_messages()
            logger.debug(f"[{agent_name}] Context has {len(messages)} messages")

            self._display_llm_request(messages, show_messages)
            self._last_tool_results = []
            self._all_thinking = []

            logger.debug(f"[{agent_name}] Sending request to LLM...")
            _trace("_process_input_impl: calling _make_first_llm_request")
            response = await self._make_first_llm_request(messages, tools, user_input, agent_name)
            _trace(f"_process_input_impl: got response, has_tool_calls={response.has_tool_calls}, content={response.content[:80] if response.content else 'empty'!r}")
            self._display_llm_response(response, show_messages, show_thinking)

            if response.has_tool_calls:
                _trace(f"_process_input_impl: handling tool calls: {[tc.name for tc in response.tool_calls]}")
                content, tool_results_history = await self._handle_tool_call_response_flow(
                    response, tools, show_thinking, agent_name
                )
                _trace(f"_process_input_impl: tool flow done, content empty={not content}, n_tool_results={len(tool_results_history)}")
            else:
                content = response.content

            if tool_results_history:
                content, tool_results_history = await self._handle_post_tool_continuation(
                    tool_results_history, tools, agent_name
                )

            content = await self._check_and_handle_detected_commands(content, agent_name)
            self.context_manager.add_message("assistant", content)

            if tool_results_history:
                elapsed = time.monotonic() - _start_time
                await self._generate_summary(tool_results_history)
                self.state.last_summary = {**(self.state.last_summary or {}), "elapsed": elapsed}

            augmented = self._build_augmented_content(content, response, tool_results_history, show_messages)
            augmented = await self._handle_pending_todos_flow(augmented, tools, agent_name)
            _trace(f"_process_input_impl: augmented len={len(augmented)}, content empty={not content}, tool_results={len(tool_results_history)}")

            self.state.state = AgentState.COMPLETE
            asyncio.create_task(self._spawn_background_review())
            logger.debug(f"[{agent_name}] Returning augmented content: {augmented}")
            return augmented

        except asyncio.CancelledError:
            self.state.state = AgentState.ERROR
            partial = ""
            if hasattr(self, "_all_thinking") and self._all_thinking:
                for thinking in self._all_thinking:
                    partial += f"[thought]| Thinking:[/thought] {thinking}\n\n"
            if tool_results_history:
                partial += "Tool results (partial - request cancelled):\n"
                for tr in tool_results_history:
                    partial += f"- {tr['tool_name']}: {tr['result'][:200]}...\n"
            return partial if partial else "Request cancelled"
            raise
        except Exception as e:
            self.state.state = AgentState.ERROR
            self.state.error = str(e)
            self.state.last_traceback = traceback.format_exc()
            return f"Error: {str(e)}"

    async def _chat_with_pipeline(
        self,
        messages: list,
        tools: list = None,
        on_token: callable = None,
    ):
        """Use the event pipeline to get LLM response (matches opencode architecture).
        
        This replaces _chat_with_retry() with the new pipeline approach.
        Returns LLMResponse for backward compatibility.
        """
        if not hasattr(self, "pipeline") or not self.pipeline:
            # Pipeline not initialized - this shouldn't happen in normal operation
            logger.error("Pipeline not initialized! Cannot process LLM request.")
            raise RuntimeError("Pipeline not initialized. Call _init_pipeline() first.")
        
        # Use pipeline to process stream
        session_id = getattr(self.context_manager, "session_id", "default")
        message = await self.pipeline.process_stream(
            session_id=session_id,
            messages=messages,
            tools=tools,
            on_token=on_token,
        )
        
        # Convert Message to LLMResponse for backward compatibility
        response = self.pipeline.to_llm_response(message)
        if response.error:
            logger.error(f"LLM pipeline error in _chat_with_pipeline: {response.error}")
            raise RuntimeError(f"LLM API error: {response.error}")
        return response

    async def execute_task(self, task: str) -> dict:
        """Execute a long-horizon task with planning."""
        self.state.state = AgentState.PLANNING
        self.state.task = task

        tools = self.tool_registry.get_schemas()

        history = [
            {"role": m.role, "content": m.content}
            for m in self.context_manager._messages
        ]

        context = PlanningContext(
            task=task,
            tools=[
                json.loads(t.get("function", {}).get("parameters", "{}")) for t in tools
            ],
            history=history,
        )

        plan = await self.planner.create_plan(context)
        self.state.plan = plan

        self.state.state = AgentState.EXECUTING

        result = await self.plan_executor.execute_plan(
            plan,
            max_retries=self.config.planning.get("max_retries", 3),
            checkpoint_enabled=self.config.planning.get("checkpoint_enabled", True),
        )

        if result.get("success"):
            self.state.state = AgentState.COMPLETE
            return {"success": True, "summary": f"Completed {len(plan.steps)} steps"}
        else:
            self.state.state = AgentState.ERROR
            return {"success": False, "error": result.get("error")}

    async def resume_from_checkpoint(self, checkpoint_id: str) -> dict:
        """Resume from a checkpoint."""
        plan = self.plan_executor.load_checkpoint(checkpoint_id)

        if not plan:
            return {"success": False, "error": "Checkpoint not found"}

        self.state.plan = plan
        self.state.state = AgentState.EXECUTING

        result = await self.plan_executor.execute_plan(plan)

        return result

    async def connect_mcp(self):
        """Connect to MCP servers."""
        await self.mcp_manager.connect_all()

    async def disconnect_mcp(self):
        """Disconnect from MCP servers."""
        await self.mcp_manager.disconnect_all()

    def get_state(self) -> dict:
        """Get current agent state."""
        state = self.state.to_dict()
        if self.prompt_cache:
            state["cache_stats"] = self.prompt_cache.get_stats()
        return state

    def get_cache_stats(self) -> dict | None:
        """Get prompt cache statistics."""
        if self.prompt_cache:
            return self.prompt_cache.get_stats()
        return None

    def clear_cache(self) -> bool:
        """Clear the prompt cache."""
        if self.prompt_cache:
            self.prompt_cache.clear()
            cache_logger.info("Prompt cache cleared")
            return True
        return False

    async def _reprompt_attempt(
        self, attempt: int, max_retries: int, tools: list, agent_name: str
    ) -> tuple[str, bool]:
        """Run a single re-prompt attempt. Returns (response, should_stop)."""
        messages = self.context_manager._messages
        last_content = ""
        for msg in reversed(messages):
            if msg.role == "assistant":
                last_content = msg.content or ""
                break

        detected = detect_commands_in_text(last_content)
        should_reprompt, reason = should_reprompt_for_tools(last_content, tools_were_expected=bool(tools))

        if not should_reprompt and not detected:
            logger.info(f"[{agent_name}] Re-prompt succeeded on attempt {attempt}")
            return last_content, True

        reprompt_msg = create_reprompt_message(detected)
        self.context_manager.add_message("user", reprompt_msg)

        if self.debug:
            console.print(f"\n[warning][WARN] Re-prompting for tools (attempt {attempt}/{max_retries}):[/warning]")
            console.print(f"  Reason: {reason}")
            if detected:
                console.print(f"  Detected commands: {len(detected)}")

        messages = self.context_manager.prepare_messages()
        response = await self._chat_with_pipeline(messages, tools, on_token=self._on_token)

        if response.has_tool_calls:
            tool_results = await self._handle_tool_calls(response.tool_calls)
            for tr in tool_results:
                result_content = self.context_manager.truncate_tool_result(tr["result"])
                self.context_manager.add_message("tool", result_content, tool_call_id=tr["tool_call_id"])

        self.context_manager.add_message("assistant", response.content)
        return "", False

    async def reprompt_for_tools(
        self,
        max_retries: int = 2,
        show_thinking: bool = True,
        show_messages: bool = True,
    ) -> str:
        """Re-prompt the model to use tools when it didn't."""
        agent_name = self.current_agent.name if self.current_agent else "unknown"
        logger.info(f"[{agent_name}] Re-prompting for tool use")
        tools = self.tool_registry.get_schemas()

        for attempt in range(1, max_retries + 1):
            response, should_stop = await self._reprompt_attempt(attempt, max_retries, tools, agent_name)
            if should_stop:
                return response

        logger.warning(f"[{agent_name}] Max re-prompt retries ({max_retries}) reached")
        for msg in reversed(self.context_manager._messages):
            if msg.role == "assistant":
                return msg.content or ""
        return ""

    async def _generate_summary(self, tool_results: list = None):
        """Generate a session summary after processing."""
        if not hasattr(self, "_summary_generator"):
            self._summary_generator = SessionSummaryGenerator(self.llm)

        messages = []
        for msg in self.context_manager._messages:
            messages.append(
                {
                    "role": msg.role,
                    "content": (
                        msg.get_text_content()
                        if hasattr(msg, "get_text_content")
                        else str(msg)
                    ),
                }
            )

        try:
            summary = await self._summary_generator.summarize(messages, tool_results)
            self.state.last_summary = {
                "additions": summary.additions,
                "deletions": summary.deletions,
                "files": summary.files,
                "text": summary.text,
            }
        except Exception as e:
            logger.warning(f"Failed to save session summary: {e}")
            pass
