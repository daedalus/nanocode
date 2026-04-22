"""Core agent implementation."""

import hashlib
import json
import logging
import traceback
from enum import Enum

from rich.console import Console
from rich.theme import Theme

from nanocode.agents import AgentInfo, PermissionAction, get_agent_registry
from nanocode.agents.permission import (
    PermissionHandler,
)


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


custom_theme = Theme({
    "thought": "yellow italic",
    "tool_call": "red",
    "tool_result": "cyan",
    "content": "green",
    "debug": "cyan",
    "warning": "yellow",
})

console = Console(theme=custom_theme)
from nanocode.config import get_config
from nanocode.context import ContextManager, ContextStrategy
from nanocode.hooks import HookManager
from nanocode.llm.base import LLMResponse
from nanocode.lsp import LSPServerManager
from nanocode.mcp import MCPManager
from nanocode.multimodal import MultimodalManager
from nanocode.planning import PlanExecutor, PlanMonitor, PlanningContext, TaskPlanner
from nanocode.session_manager import get_session_manager
from nanocode.session_summary import SessionSummaryGenerator
from nanocode.state import AgentState, AgentStateData
from nanocode.storage.cache import CachedResponse, PromptCache, get_prompt_cache
from nanocode.tools import ToolExecutor, ToolRegistry
from nanocode.tools.builtin import register_builtin_tools
from nanocode.tools.file_tracker import FileTracker
from nanocode.tools.text_detector import (
    create_reprompt_message,
    detect_commands_in_text,
    format_detected_commands_message,
    should_reprompt_for_tools,
)

DEFAULT_SYSTEM_PROMPT = """You are NanoCode, an autonomous CLI coding agent."""

SYSTEM_PROMPT_TEMPLATE = """You are NanoCode, an autonomous CLI coding agent.

# Tool Invocation - CRITICAL

**EVERY user request is a NEW task.** Start fresh - don't reference previous tasks unless user asks.

When user gives a command like "read ./README.md" or "write a bubble sort":
- This is a NEW request - ignore previous context for this task
- Call the appropriate tool IMMEDIATELY
- Do NOT explain, ask confirmation, or discuss previous requests
- Do NOT repeat what you did before - do the NEW task

Examples:
- "read file.txt" → call read tool with path="file.txt"  
- "write a bubble sort" → call write tool with a file path and algorithm code
- "search X" → call grep tool
- "list files" → call ls tool

**CRITICAL**: For any task, CALL TOOLS. Don't explain, don't discuss, just execute.

**EXCEPTION**: If input is ONLY a greeting ("hi", "hello", "hey") → respond conversationally, no tool.

# Core Principles

## Tone and Style
- Be concise and direct. Keep responses under 4 lines.
- No preambles ("Okay, I will...") or postambles ("I have finished...").
- Use GitHub-flavored markdown. Monospace rendering.
- **Focus on findings, not summaries** - present findings first with file:line refs.

## Proactiveness
- Only be proactive when the user explicitly asks.
- Never commit changes unless explicitly requested.
- NEVER revert changes you didn't make.

## Decision Making
- Distinguish **Directives** (action) from **Inquiries** (analysis).
- For Inquiries: research and propose, but DON'T modify files until Directive.
- For Directives: work autonomously unless critically underspecified.
- If request is ambiguous, ask clarification first.

# Capabilities

## Available Agents
{agents}

## Available Tools
{tools}

## Skills
{skills}

## MCP Servers
{mcp_servers}

## LSP Servers
{lsp_servers}

# Workflow

## Research → Strategy → Execution → Validate
1. **Research**: Use grep, glob, read to understand codebase
2. **Strategy**: Formulate plan. Break complex tasks into subtasks
3. **Execute**: Implement changes. Include tests
4. **Validate**: Run tests, linting, type-checking. **NEVER assume success**

## Validation Requirements
- Run project-specific lint/typecheck (e.g., `npm run lint`, `ruff`, `mypy`)
- Run tests after code changes
- For bug fixes: empirically reproduce failure before fix

## DOOM LOOP Prevention
- NEVER repeat same tool calls (ls → ls → ls)
- NEVER call ls/glob more than twice without reading files
- After glob finds files → IMMEDIATELY read them

# Code Quality

## Engineering Standards
- Follow workspace conventions: naming, formatting, typing
- Check existing code patterns before adding new code
- Verify libraries in package.json, Cargo.toml, requirements.txt
- NEVER bypass type systems (no casts unless necessary)
- NEVER disable warnings or linters

## Security
- Never expose or log secrets, API keys, credentials
- Never stage/commit unless explicitly instructed

## Code Style
- DO NOT ADD COMMENTS unless explicitly requested
- Use file:line references in responses (e.g., src/app.ts:42)

# Context Efficiency
- Full history passed each turn - early context is expensive
- Reduce unnecessary turns
- Use grep/glob with conservative limits
- Combine searches and reads in parallel
- Provide enough context to avoid extra turns

# Tool Usage
- Execute independent tool calls in parallel
- Use sequential only when tools depend on each other
- For multiple edits to same file: use sequential turns

# Skills
Skills provide specialized capabilities. To activate:
- Use `/skill <name>` to view skill details
- Use `/skill <name> <input>` to execute a skill

# Tool Invocation - MANDATORY
When user requests a file operation (read, write, edit, search):
- Use the read tool to read files
- Use the write tool to write files
- Use the grep tool to search files
- ALWAYS call the appropriate tool - NEVER respond with just text

User input "read ./README.md" means: call the read tool with path="./README.md"
User input "write file.py" means: use the write tool
User input "search for X" means: use the grep tool

## DO NOT Explain - Just Execute
- When user gives specific command like "read ./README.md", JUST execute it
- Do NOT ask for confirmation
- Do NOT explain what you're about to do
- Do NOT output "I'll read that file for you"
- IMMEDIATELY call the read tool with the given path

# Code Review
When asked to review code:
- Prioritize bugs, risks, behavioral regressions, missing tests
- Present findings first (file:line refs, ordered by severity)
- Keep summaries brief
- If no findings, state explicitly

# Final Answer Structure
- Lead with quick explanation
- Use file:line references
- Suggest natural next steps (tests, commits)
- Avoid dumping large outputs - reference paths only

# Git
- Current directory is git repository
- NEVER stage or commit unless explicitly instructed
- Check git status, diff, log before committing

# Environment
- Working directory: {cwd}
- Config file: {config_file}"""

logger = logging.getLogger("nanocode.agent")
logger = logging.getLogger("nanocode.agent")
tool_logger = logging.getLogger("nanocode.tools")
cache_logger = logging.getLogger("nanocode.cache")


class SessionLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that includes session_id in all log messages."""
    
    def process(self, msg, kwargs):
        session_id = self.extra.get('session_id', 'unknown') if self.extra else 'unknown'
        return f"[session={session_id}] {msg}", kwargs


def get_session_logger(session_id: str = None):
    """Get a logger that includes session_id in all log messages."""
    base_logger = logging.getLogger("nanocode.agent")
    if session_id:
        hashed = hashlib.sha256(session_id.encode()).hexdigest()[:8]
        return SessionLoggerAdapter(base_logger, {'session_id': hashed})
    return base_logger


_current_session_id: str | None = None


def set_current_session_id(session_id: str) -> None:
    """Set the current session ID globally."""
    global _current_session_id
    _current_session_id = session_id


def get_current_session_id() -> str | None:
    """Get the current session ID."""
    return _current_session_id


class AutonomousAgent:
    """Main autonomous agent class."""

    def __init__(self, config: dict | None = None, session_id: str = None, verbose: bool = False, yolo: bool = False, drift_alert: bool = False, drift_intervene: bool = False):
        self.config = config or get_config()
        self.state = AgentStateData()
        self.debug = verbose
        self.yolo = yolo
        self.drift_mode = "intervene" if drift_intervene else ("alert" if drift_alert else "off")
        self._session_id = session_id
        self._session_logger = None

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
        self._init_context()
        self._init_planning()
        self._init_multimodal()
        self._init_drift_watchdog() if self.drift_mode != "off" else None
        self._init_cache()

    def _init_session(self):
        """Initialize session management."""
        self.session_manager = get_session_manager()
        if self._session_id:
            self.session = self.session_manager.get(self._session_id)
            if self.session:
                logger.info(f"Resumed session: {self._session_id}")
            else:
                logger.warning(f"Session not found: {self._session_id}, creating new")
                self.session = self.session_manager.create(f"Session - resumed from {self._session_id}")
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
        session_id = getattr(self, '_session_id', 'no-session')
        logger.warning(f"CACHE INIT: session={session_id}, _session_logger={self._session_logger}")
        if self._session_logger:
            self._session_logger.info(f"Cache: {'enabled' if cache_enabled else 'disabled'}")
        if cache_enabled:
            try:
                cache_dir = self.config.cache_dir
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.prompt_cache = get_prompt_cache()
                cache_logger.info(f"Prompt cache enabled: {self.prompt_cache.db_path}")
            except Exception as e:
                cache_logger.warning(f"Failed to initialize prompt cache: {e}")

    def _init_agents(self):
        """Initialize agent system."""
        logger.info("Initializing agent system")
        self.nanocode_registry = get_agent_registry()
        self.current_agent = self.nanocode_registry.get_default()
        self.permission_handler = PermissionHandler()
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
        self.file_tracker = FileTracker(cache_dir)

    def _init_llm(self):
        """Initialize LLM provider."""
        use_registry = self.config.get("llm.use_model_registry", False)
        default_model = self.config.get("llm.default_model")
        default_provider = self.config.default_provider
        user_agent = self.config.get("llm.user_agent", "nanocode/1.0")
        proxy = self.config.proxy

        # FIRST: Use default_provider from config when set (before registry logic)
        if default_provider:
            providers = self.config.providers
            if default_provider in providers:
                provider_config = providers[default_provider].copy()
                model = provider_config.pop("model", default_model)
                max_tokens = provider_config.pop("max_tokens", None)
                logger.info(f"Using default_provider: {default_provider}, model: {model}")
                logger.info(f"URL: {provider_config.get('base_url')}")
                from nanocode.llm import create_llm
                llm = create_llm(default_provider, model=model, user_agent=user_agent, proxy=proxy, debug=self.debug, **provider_config)
                if max_tokens:
                    llm.max_tokens = max_tokens
                self.llm = llm
                return
            else:
                logger.warning(f"Provider {default_provider} not in providers: {list(providers.keys())}")

        # Only use registry if no default_provider
            from nanocode.llm.router import get_router

            providers = self.config.get("llm.providers", {})
            router = get_router()

            for provider, config in providers.items():
                router.add_explicit_provider(provider, config)

            provider_config = router.get_provider_config(default_model)
            logger.info(f"Model: {default_model} -> Provider: {provider_config.provider}, URL: {provider_config.base_url}")

            from nanocode.llm import OpenAILLM
            from nanocode.llm.providers.anthropic import AnthropicLLM
            from nanocode.llm.providers.ollama import OllamaLLM

            if provider_config.provider == "anthropic":
                self.llm = AnthropicLLM(
                    api_key=provider_config.api_key,
                    model=provider_config.model,
                    user_agent=user_agent,
                    proxy=proxy,
                )
            elif provider_config.provider == "ollama":
                self.llm = OllamaLLM(
                    base_url=provider_config.base_url,
                    model=provider_config.model,
                    user_agent=user_agent,
                    proxy=proxy,
                )
            else:
                self.llm = OpenAILLM(
                    base_url=provider_config.base_url,
                    api_key=provider_config.api_key or "dummy",
                    model=provider_config.model,
                    user_agent=user_agent,
                    proxy=proxy,
                )
        else:
            providers = self.config.providers
            default = self.config.default_provider

            if default in providers:
                provider_config = providers[default]
                self.llm = create_llm(
                    default, **provider_config, user_agent=user_agent, proxy=proxy, debug=self.debug
                )
            else:
                self.llm = create_llm(
                    "openai",
                    api_key="dummy",
                    model="gpt-4",
                    user_agent=user_agent,
                    proxy=proxy,
                    debug=self.debug,
                )

    def _init_hooks(self):
        """Initialize hook system."""

        self.hook_manager = HookManager(base_dir=self.config.get("base_dir", "."))
        self.hook_manager.discover_hooks()
        logger.info(f"Hook system initialized: {len(sum(self.hook_manager.hooks.values(), []))} hooks loaded")

    def _init_tools(self):
        """Initialize tool system."""
        from nanocode.doom_loop import create_doom_loop_handler
        from nanocode.tools.task import create_task_tool

        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry, self.hook_manager)

        register_builtin_tools(
            self.tool_registry, self.config.tools, self.file_tracker, self.lsp_manager
        )

        self.task_tool = create_task_tool(
            self.nanocode_registry, self.permission_handler
        )
        self.task_tool.set_parent_agent(self)
        self.tool_registry.register(self.task_tool)

        self.tool_registry.register_handler("mcp", self._handle_mcp_tool)

        self.doom_loop_handler = create_doom_loop_handler()

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
        if system_prompt := ctx_config.get("system_prompt"):
            final_prompt = system_prompt
        else:
            final_prompt = self._build_system_prompt()

        self.context_manager.set_system_prompt(final_prompt)

    async def init_async(self):
        """Async initialization - load model registry from API."""
        await self.context_manager.init_async()

    def _build_system_prompt(self) -> str:
        """Build system prompt from template with dynamic capabilities."""
        import os
        from pathlib import Path
        
        # Start with base prompt
        prompt = SYSTEM_PROMPT_TEMPLATE
        
        # Get agents
        agents_info = []
        if self.nanocode_registry:
            for agent in self.nanocode_registry.list():
                mode = agent.mode.value if hasattr(agent.mode, 'value') else agent.mode
                agents_info.append(f"- {agent.name}: {mode} agent (native={agent.native})")
        
        # Get tools
        tools_info = []
        if self.tool_registry:
            for name, tool in self.tool_registry._tools.items():
                desc = getattr(tool, 'description', '') or ''
                tools_info.append(f"- {name}: {desc}")
        
        # Get MCP servers
        mcp_info = []
        if hasattr(self, 'mcp_manager') and self.mcp_manager:
            for name in self.mcp_manager._clients.keys():
                mcp_info.append(f"- {name}")
        
        # Get LSP servers
        lsp_info = []
        if hasattr(self, 'lsp_manager') and self.lsp_manager:
            for server_id in self.lsp_manager._servers.keys():
                lsp_info.append(f"- {server_id}")
        
        # Get skills
        skill_info = []
        if hasattr(self, 'skills_manager') and self.skills_manager:
            for name, skill in self.skills_manager.skills.items():
                desc = getattr(skill, 'description', '') or ''
                skill_info.append(f"- {name}: {desc}")
        
        # Get current directory and config
        cwd = os.getcwd()
        config_file = str(self.config.config_path) if hasattr(self.config, 'config_path') else "config.yaml"
        
        # Check for .system_prompts/ directory
        system_prompts_dir = Path(cwd) / ".system_prompts"
        extra_prompts = ""
        if system_prompts_dir.exists():
            for f in sorted(system_prompts_dir.glob("*.md")):
                extra_prompts += f"\n\n# From {f.name}\n"
                extra_prompts += f.read_text()
            for f in sorted(system_prompts_dir.glob("*.txt")):
                extra_prompts += f"\n\n# From {f.name}\n"
                extra_prompts += f.read_text()

        # Check for AGENTS.md in cwd or parent
        for agents_file in [Path(cwd) / "AGENTS.md", Path(cwd).parent / "AGENTS.md"]:
            if agents_file.exists():
                extra_prompts += f"\n\n# From {agents_file.name}\n"
                extra_prompts += agents_file.read_text()
                break

        # Check for GEMINI.md
        for gemini_file in [Path(cwd) / "GEMINI.md", Path(cwd).parent / "GEMINI.md"]:
            if gemini_file.exists():
                extra_prompts += f"\n\n# From {gemini_file.name}\n"
                extra_prompts += gemini_file.read_text()
                break
        
        # Format template
        return prompt.format(
            agents="\n".join(agents_info) if agents_info else "- (no custom agents)",
            tools="\n".join(tools_info) if tools_info else "- (built-in only)",
            skills="\n".join(skill_info) if skill_info else "- (none installed)",
            mcp_servers="\n".join(mcp_info) if mcp_info else "- (none configured)",
            lsp_servers="\n".join(lsp_info) if lsp_info else "- (none configured)",
            cwd=cwd,
            config_file=config_file,
        ) + extra_prompts

    def _init_mcp(self):
        """Initialize MCP connections."""
        self.mcp_manager = MCPManager()
        self._mcp_available = {}

        mcp_servers = self.config.mcp_servers
        for name, server_config in mcp_servers.items():
            self._mcp_available[name] = server_config.get("enabled", True)
            if self._mcp_available[name]:
                self.mcp_manager.add_server(name, server_config)

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

    def _handle_mcp_tool(self, **kwargs):
        """Handle MCP tool calls."""
        return {"status": "not implemented"}

    async def _handle_tool_calls(self, tool_calls: list) -> list[dict]:
        """Handle tool calls from LLM with permission checking and doom loop detection."""
        agent_name = self.current_agent.name if self.current_agent else "unknown"
        logger.info(f"[{agent_name}] Handling {len(tool_calls)} tool call(s)")

        results = []
        for i, tc in enumerate(tool_calls):
            tool_name = tc.name
            args = tc.arguments
            logger.debug(
                f"[{agent_name}] Tool call {i + 1}/{len(tool_calls)}: {tool_name}({args})"
            )

            is_doom_loop = self.doom_loop_handler.check_tool_call(tool_name, args)
            if is_doom_loop:
                loop_info = self.doom_loop_handler.detection.get_loop_info()
                should_show_warning = loop_info.get("show_warning", True) if loop_info else True
                
                if should_show_warning:
                    warning = self.doom_loop_handler.get_loop_warning()
                    if warning:
                        logger.warning(
                            f"[{agent_name}] DOOM LOOP DETECTED for '{tool_name}': {warning}"
                        )
                        if self.debug:
                            console.print(f"\n[red]{warning}[/red]\n")
                
                doom_loop_msg = f"\n[DOOM LOOP WARNING] {self.doom_loop_handler.get_loop_warning()}\n"

                if self.current_agent:
                    doom_action = self.permission_handler.check_permission(
                        self.current_agent,
                        "doom_loop",
                        {"tool": tool_name, "args": args},
                    )
                    if doom_action == PermissionAction.DENY:
                        logger.warning(
                            f"[{agent_name}] Doom loop permission DENIED for '{tool_name}'"
                        )
                        results.append(
                            {
                                "tool_call_id": tc.id,
                                "tool_name": tool_name,
                                "result": f"Error: Doom loop detected - tool '{tool_name}' called repeatedly with same arguments. Permission denied.{doom_loop_msg}",
                                "success": False,
                            }
                        )
                        continue
                    elif doom_action == PermissionAction.ASK:
                        logger.info(
                            f"[{agent_name}] Requesting permission to break doom loop for '{tool_name}'"
                        )
                        try:
                            await self.permission_handler.request_permission(
                                self.current_agent, "doom_loop", {"tool": tool_name, "args": args}
                            )
                            logger.debug(
                                f"[{agent_name}] Doom loop permission granted for '{tool_name}'"
                            )
                            # Reset doom loop state after permission granted
                            self.doom_loop_handler.reset()  # Reset all, not just tool_name
                        except Exception as e:
                            logger.error(
                                f"[{agent_name}] Doom loop permission denied for '{tool_name}': {e}"
                            )
                            results.append(
                                {
                                    "tool_call_id": tc.id,
                                    "tool_name": tool_name,
                                    "result": f"Error: Doom loop detected - permission denied by user.{doom_loop_msg}",
                                    "success": False,
                                }
                            )
                            continue
                    else:
                        # Permission granted - reset doom loop state for this tool
                        self.doom_loop_handler.reset(tool_name)
                        results.append(
                            {
                                "tool_call_id": tc.id,
                                "tool_name": tool_name,
                                "result": doom_loop_msg + "Tool executed but doom loop detected.",
                                "success": True,
                            }
                        )
                        continue

            if self.current_agent:
                if self.yolo:
                    action = PermissionAction.ALLOW
                    logger.debug(f"[YOLO] Auto-allowing '{tool_name}'")
                else:
                    action = self.permission_handler.check_permission(
                        self.current_agent, tool_name, args
                    )
                    logger.debug(
                        f"[{agent_name}] Permission check for '{tool_name}': {action.value}"
                    )

                if action == PermissionAction.DENY:
                    logger.warning(
                        f"[{agent_name}] Permission DENIED for '{tool_name}'"
                    )
                    results.append(
                        {
                            "tool_call_id": tc.id,
                            "tool_name": tool_name,
                            "result": f"Error: Permission denied for tool '{tool_name}'",
                            "success": False,
                        }
                    )
                    continue
                if action == PermissionAction.ASK:
                    logger.info(
                        f"[{agent_name}] Requesting permission for '{tool_name}'"
                    )
                    try:
                        await self.permission_handler.request_permission(
                            self.current_agent, tool_name, args
                        )
                        logger.debug(
                            f"[{agent_name}] Permission granted for '{tool_name}'"
                        )
                    except Exception as e:
                        logger.error(
                            f"[{agent_name}] Permission request failed for '{tool_name}': {e}"
                        )
                        results.append(
                            {
                                "tool_call_id": tc.id,
                                "tool_name": tool_name,
                                "result": f"Error: {str(e)}",
                                "success": False,
                            }
                        )
                        continue

            logger.debug(f"[{agent_name}] Executing tool: {tool_name}")
            result = await self.tool_executor.execute(tool_name, args, self._session_id, agent_name)

            if result.success:
                logger.info(f"[{agent_name}] Tool '{tool_name}' succeeded")
            else:
                logger.warning(
                    f"[{agent_name}] Tool '{tool_name}' failed: {result.error}"
                )

            tool_logger.debug(
                f"[{agent_name}] Tool call: {tool_name}({args}) -> success={result.success}"
            )

            results.append(
                {
                    "tool_call_id": tc.id,
                    "tool_name": tool_name,
                    "result": self.tool_executor.format_result(result),
                    "success": result.success,
                }
            )

        logger.debug(f"[{agent_name}] Finished handling {len(tool_calls)} tool call(s)")
        return results

    def _format_thinking(self, thinking: str) -> str:
        """Format thinking content for display."""
        lines = thinking.strip().split("\n")
        formatted = "\n".join(f"  {line}" for line in lines)
        return f"[thought]| Thinking:[/thought]\n{formatted}"

    def _get_cache_key(self, messages: list, tools: list[dict] | None) -> str:
        """Generate a cache key from messages and tools."""
        import hashlib

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
            logger.warning(f"[CACHE KEY DEBUG] Msg {i}: role={role}, content_len={len(str(content))}, content_preview={str(content)[:80]}")
        
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
    ) -> LLMResponse | None:
        """Check if we have a cached response for these messages."""
        if not self.prompt_cache:
            return None

        cache_key = self._get_cache_key(messages, tools)
        cached = self.prompt_cache.get(cache_key)

        if cached:
            cache_logger.info(
                f"Cache HIT: {len(messages)} messages, {len(cached.content)} chars"
            )
            return LLMResponse(
                content=cached.content,
                thinking=cached.thinking,
                tool_calls=[
                    type("ToolCall", (), tc)() for tc in (cached.tool_calls or [])
                ]
                if cached.tool_calls
                else [],
            )
        return None

    def _put_cache(
        self, messages: list, tools: list[dict] | None, response: LLMResponse
    ) -> None:
        """Store the response in cache."""
        if not self.prompt_cache:
            return

        cache_key = self._get_cache_key(messages, tools)

        cached = CachedResponse(
            content=response.content,
            thinking=response.thinking,
            tool_calls=[
                {"name": tc.name, "arguments": tc.arguments}
                for tc in response.tool_calls
            ]
            if response.tool_calls
            else [],
            model=getattr(self.llm, "model", None),
        )

        self.prompt_cache.put(cache_key, cached)
        cache_logger.info(
            f"Cached: {len(messages)} messages, {len(response.content) if response.content else 0} chars"
        )

    async def process_input(
        self, user_input: str, show_thinking: bool = True, show_messages: bool = False
    ) -> str:
        """Process a user input through the agent."""
        import traceback
        try:
            return await self._process_input_impl(user_input, show_thinking, show_messages)
        except Exception as e:
            if "Expecting value" in str(e) or isinstance(e, json.JSONDecodeError):
                logger.error(f"JSON parsing error in process_input: {e}")
                return f"Error: Failed to parse LLM response - {e}"
            traceback.print_exc()
            raise

    async def _process_input_impl(
        self, user_input: str, show_thinking: bool = True, show_messages: bool = False
    ) -> str:
        """Process a user input through the agent."""
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

        tool_results_history = []

        try:
            tools = self.tool_registry.get_schemas()
            logger.debug(f"[{agent_name}] Total tools available: {len(tools)}")

            # DEBUG: Print what we send to LLM
            logger.debug(f"[{agent_name}] === FIRST LLM REQUEST ===")

            messages = self.context_manager.prepare_messages()
            logger.debug(f"[{agent_name}] Context has {len(messages)} messages")
# DEBUG: Print all messages being sent to LLM
            # logger.warning(f"[DEBUG LLM] ===== MESSAGES TO LLM =====")
            # for i, m in enumerate(messages):
            #     role = m.get("role", "?") if isinstance(m, dict) else getattr(m, "role", "?")
            #     content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
            #     if content:
            #         logger.warning(f"[DEBUG LLM] Msg {i}: {role}: {str(content)[:200]}")

            if self.debug:
                console.print(f"\n[debug][DEBUG] Sending {len(messages)} messages to LLM...[/debug]")
                for i, msg in enumerate(messages):
                    content = (
                        msg.content
                        if hasattr(msg, "content")
                        else str(msg.get("content", ""))
                    )
                    role = msg.role if hasattr(msg, "role") else msg.get("role", "?")
                    console.print(f"  [dim]{i}: {role}: {content}[/dim]")

            if show_messages:
                console.print("\n[debug]=== LLM REQUEST ===[/debug]")
                for i, msg in enumerate(messages):
                    content = (
                        msg.content
                        if hasattr(msg, "content")
                        else str(msg.get("content", ""))
                    )
                    role = msg.role if hasattr(msg, "role") else msg.get("role", "?")
                    print(f"\n[{i}] {role.upper()}:")
                    print(content if len(content) > 0 else content)
                print("\n")

            # Track for show_thinking/show_messages output
            self._last_tool_results = []
            self._last_thinking = None

            logger.debug(f"[{agent_name}] Sending request to LLM...")

            cached_response = self._check_cache(messages, tools)
            logger.debug(f"[DEBUG] User input: '{user_input}'")
            logger.debug(f"[DEBUG] Context messages before LLM: {len(messages)}")
            if cached_response:
                cache_logger.warning(f"[{agent_name}] Using CACHED response (this is a bug if input changed!)")
                logger.warning(f"[{agent_name}] Cache hit! Messages: {len(messages)}, User input: {user_input[:50]}")
                if self.debug:
                    console.print("\n[warning][WARN] CACHE HIT - Previous response reused![/warning]")
                response = cached_response
            else:
                response = await self.llm.chat(
                    messages=messages,
                    tools=tools if tools else None,
                )
                self._put_cache(messages, tools, response)
                logger.info(f"[{agent_name}] LLM response received")

            # Track thinking for output
            if hasattr(self, '_last_thinking') and response.thinking:
                self._last_thinking = response.thinking

            if self.debug:
                console.print("\n[debug][DEBUG] LLM Response:[/debug]")
                if response.thinking:
                    console.print(f"  [thought]| Thinking:[/thought]\n{response.thinking}")
                if response.has_tool_calls:
                    console.print(
                        f"  [tool_call]Tool Calls: {[tc.name for tc in response.tool_calls]}[/tool_call]"
                    )
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
                print(
                    f"\nContent:\n{response.content if response.content else '(empty)'}"
                )
                print()

            if response.thinking and show_thinking and self.debug:
                # Only print thinking when debug is explicitly enabled
                console.print(self._format_thinking(response.thinking))

            if response.has_tool_calls:
                logger.info(
                    f"[{agent_name}] LLM requested {len(response.tool_calls)} tool call(s): {[tc.name for tc in response.tool_calls]}"
                )
                if self.debug:
                    console.print(
                        f"\n[debug][DEBUG] Handling {len(response.tool_calls)} tool calls...[/debug]"
                    )
                
                tool_results = await self._handle_tool_calls(response.tool_calls)
                tool_results_history.extend(tool_results)
                if hasattr(self, '_last_tool_results'):
                    self._last_tool_results.extend(tool_results)

                for tr in tool_results:
                    if self.debug:
                        console.print(
                            f"\n[debug][DEBUG] Tool {tr['tool_name']} result:[/debug] {tr['result']}"
                        )
                    result_content = tr["result"]
                    result_content = self.context_manager.truncate_tool_result(
                        result_content
                    )
                
                # Add assistant message with tool_calls FIRST (before tool results)
                # This ensures correct order: user → assistant → tool result
                self.context_manager.add_message(
                    "assistant",
                    None,
                    tool_calls=response.tool_calls,
                )
                
                # Then add tool results
                for tr in tool_results:
                    result_content = tr["result"]
                    result_content = self.context_manager.truncate_tool_result(
                        result_content
                    )
                    self.context_manager.add_tool_result(
                        tr["tool_name"],
                        tr["tool_call_id"],
                        result_content,
                    )

                messages = self.context_manager.prepare_messages()
                # Debug: log tool result in messages
                for i, m in enumerate(messages):
                    if m.get("role") == "tool":
                        logger.info(f"[{agent_name}] Message {i} tool result: {m.get('content', '')[:100]}...")
                final_response = await self.llm.chat(messages=messages, tools=tools if tools else None)

                # Track thinking from second response
                if final_response.thinking and show_thinking and self.debug:
                    self._last_thinking = final_response.thinking
                    console.print(self._format_thinking(final_response.thinking))

                # Continue handling tool calls in a loop until no more are requested
                # Use agent's configured steps limit, or default to 10
                max_agent_steps = self.get_agent_steps() or 10
                iteration = 0
                while final_response.has_tool_calls and iteration < max_agent_steps:
                    iteration += 1
                    is_last_step = iteration >= max_agent_steps
                    logger.info(
                        f"[{agent_name}] Second LLM requested {len(final_response.tool_calls)} tool call(s): {[tc.name for tc in final_response.tool_calls]} (iteration {iteration}/{max_agent_steps})"
                    )

                    tool_results = await self._handle_tool_calls(final_response.tool_calls)
                    tool_results_history.extend(tool_results)

                    for tr in tool_results:
                        result_content = tr["result"]
                        result_content = self.context_manager.truncate_tool_result(result_content)
                        self.context_manager.add_tool_result(
                            tr["tool_name"],
                            tr["tool_call_id"],
                            result_content,
                        )

                    messages = self.context_manager.prepare_messages()

                    # Track thinking from each iteration
                    if final_response.thinking:
                        self._last_thinking = final_response.thinking
                        if show_thinking and self.debug:
                            console.print(self._format_thinking(final_response.thinking))

                    # On last step, inject MAX_STEPS message and disable tools (like opencode)
                    if is_last_step:
                        max_steps_msg = (
                            "\nCRITICAL - MAXIMUM STEPS REACHED\n\n"
                            "The maximum number of steps allowed for this task has been reached. "
                            "Tools are disabled until next user input. Respond with text only.\n\n"
                            "STRICT REQUIREMENTS:\n"
                            "1. Do NOT make any tool calls (no reads, writes, edits, searches, or any other tools)\n"
                            "2. MUST provide a text response summarizing work done so far\n"
                            "3. This constraint overrides ALL other instructions\n\n"
                            "Any attempt to use tools is a critical violation. Respond with text ONLY."
                        )
                        messages = self.context_manager.prepare_messages()
                        messages.append({"role": "user", "content": max_steps_msg})
                        logger.debug(f"[{agent_name}] Forcing text-only response (max steps reached)")
                        final_response = await self.llm.chat(messages=messages, tools=None)
                    else:
                        final_response = await self.llm.chat(messages=messages, tools=tools if tools else None)

                if iteration >= max_agent_steps:
                    logger.warning(f"[{agent_name}] Hit max iterations ({max_agent_steps})")

                content = final_response.content
            else:
                content = response.content

            # Force retry WITHOUT tools - explicitly tell model to respond, not call more tools
            if not content and tool_results_history:
                logger.info(f"[{agent_name}] Empty response - forcing NO-TOOLS retry")
                messages = self.context_manager.prepare_messages()
                # Add explicit instruction not to call tools
                messages.append({"role": "user", "content": "DO NOT call any more tools. Analyze the tool results above and provide your final answer to the user."})
                retry_response = await self.llm.chat(messages=messages, tools=None)
                content = retry_response.content
                
            # Final fallback
            if not content:
                if tool_results_history:
                    content = "Tools executed successfully. Results shown above."
                else:
                    content = "(no response)"

                # Text-to-Tool Detection: Handle model outputs text that looks like commands
                detected = detect_commands_in_text(content)
                if detected:
                    logger.warning(
                        f"[{agent_name}] Detected {len(detected)} command(s) in text that were not executed"
                    )
                    if self.debug:
                        console.print("\n[warning][WARN] Detected unexecuted commands:[/warning]")
                        for cmd in detected:
                            console.print(f"  - [{cmd.tool_name}] {cmd.command[:60]}...")

                # Check if model should have used tools but didn't
                tools = self.tool_registry.get_schemas()
                should_reprompt, reason = should_reprompt_for_tools(
                    content,
                    tools_were_expected=bool(tools)
                )

                if should_reprompt:
                    logger.warning(f"[{agent_name}] Model didn't use tools: {reason}")
                    if self.debug:
                        console.print(f"\n[warning][WARN] {reason}[/warning]")

                    # Add detected commands warning to content
                    warning_msg = format_detected_commands_message(detected)
                    if warning_msg:
                        content += warning_msg

            self.context_manager.add_message("assistant", content)

            await self._generate_summary(tool_results_history)

            # Build augmented content with thinking and tool use info
            augmented = content
            
            # Always include thinking if available
            if show_thinking and hasattr(self, '_last_thinking') and self._last_thinking:
                augmented += f"\n\n[thought]| Thinking:[/thought] {self._last_thinking}"
            
            # Include tool use info (full output, not truncated)
            if tool_results_history:
                if show_thinking:
                    tool_info = "\n\n[thought]| Tool Use:[/thought]"
                    for tr in tool_results_history:
                        result_str = str(tr['result'])
                        # Include full result for display
                        tool_info += f"\n- {tr['tool_name']}:\n{result_str}"
                    augmented += tool_info
                    
                if show_messages:
                    tool_summary = "\n\n[Tool Summary]"
                    for tr in tool_results_history:
                        tool_summary += f"\n- {tr['tool_name']}: executed"
                    augmented += tool_summary
            
            self.state.state = AgentState.COMPLETE

            return augmented

        except Exception as e:
            self.state.state = AgentState.ERROR
            self.state.error = str(e)
            self.state.last_traceback = traceback.format_exc()
            return f"Error: {str(e)}"

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

    async def reprompt_for_tools(
        self,
        max_retries: int = 2,
        show_thinking: bool = True,
        show_messages: bool = False,
    ) -> str:
        """Re-prompt the model to use tools when it didn't.

        Call this after process_input if you suspect the model didn't use
        tools when it should have.

        Args:
            max_retries: Maximum number of re-prompt attempts
            show_thinking: Whether to show thinking blocks
            show_messages: Whether to show message details

        Returns:
            The model's response after re-prompting
        """
        agent_name = self.current_agent.name if self.current_agent else "unknown"
        logger.info(f"[{agent_name}] Re-prompting for tool use")

        tools = self.tool_registry.get_schemas()
        detected = []
        attempt = 0

        while attempt < max_retries:
            attempt += 1

            # Detect commands in the last assistant message
            messages = self.context_manager._messages
            last_content = ""
            for msg in reversed(messages):
                if msg.role == "assistant":
                    last_content = msg.content or ""
                    break

            detected = detect_commands_in_text(last_content)
            should_reprompt, reason = should_reprompt_for_tools(
                last_content,
                tools_were_expected=bool(tools)
            )

            if not should_reprompt and not detected:
                # Model is now using tools properly or response is complete
                logger.info(f"[{agent_name}] Re-prompt succeeded on attempt {attempt}")
                return last_content

            # Add re-prompt message
            reprompt_msg = create_reprompt_message(detected)
            self.context_manager.add_message(
                "user",
                reprompt_msg,
            )

            if self.debug:
                console.print(f"\n[warning][WARN] Re-prompting for tools (attempt {attempt}/{max_retries}):[/warning]")
                console.print(f"  Reason: {reason}")
                if detected:
                    console.print(f"  Detected commands: {len(detected)}")

            # Process the re-prompt
            messages = self.context_manager.prepare_messages()
            response = await self.llm.chat(
                messages=messages,
                tools=tools if tools else None,
            )

            if response.has_tool_calls:
                logger.info(f"[{agent_name}] Re-prompt produced {len(response.tool_calls)} tool calls")
                # Handle the tool calls
                tool_results = await self._handle_tool_calls(response.tool_calls)
                for tr in tool_results:
                    result_content = tr["result"]
                    result_content = self.context_manager.truncate_tool_result(result_content)
                    self.context_manager.add_message(
                        "tool",
                        result_content,
                        tool_call_id=tr["tool_call_id"],
                    )

            # Add assistant response
            self.context_manager.add_message("assistant", response.content)

        # Max retries reached
        logger.warning(f"[{agent_name}] Max re-prompt retries ({max_retries}) reached")
        messages = self.context_manager._messages
        for msg in reversed(messages):
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
