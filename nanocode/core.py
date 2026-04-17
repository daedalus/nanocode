"""Core agent implementation."""

import json
import logging
import traceback

from nanocode.agents import AgentInfo, PermissionAction, get_agent_registry
from nanocode.agents.permission import (
    PermissionHandler,
)
from nanocode.config import get_config
from nanocode.context import ContextManager, ContextStrategy
from nanocode.llm import create_llm
from nanocode.llm.base import LLMResponse
from nanocode.lsp import LSPServerManager
from nanocode.mcp import MCPManager
from nanocode.multimodal import MultimodalManager
from nanocode.planning import PlanExecutor, PlanMonitor, PlanningContext, TaskPlanner
from nanocode.session_summary import SessionSummaryGenerator
from nanocode.state import AgentState, AgentStateData
from nanocode.storage.cache import CachedResponse, PromptCache, get_prompt_cache
from nanocode.tools import ToolExecutor, ToolRegistry
from nanocode.tools.builtin import register_builtin_tools
from nanocode.tools.file_tracker import FileTracker

logger = logging.getLogger("nanocode.agent")
tool_logger = logging.getLogger("nanocode.tools")
cache_logger = logging.getLogger("nanocode.cache")


class AutonomousAgent:
    """Main autonomous agent class."""

    def __init__(self, config: dict | None = None):
        self.config = config or get_config()
        self.state = AgentStateData()
        self.debug = False

        self._init_agents()
        self._init_storage()
        self._init_file_tracker()
        self._init_llm()
        self._init_lsp()
        self._init_tools()
        self._init_context()
        self._init_mcp()
        self._init_planning()
        self._init_multimodal()
        self._init_cache()

    def _init_cache(self):
        """Initialize the prompt cache."""
        self.prompt_cache: PromptCache | None = None
        if self.config.cache_enabled:
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
        cache_dir = self.config.get("file_tracker.cache_dir", ".nanocode/cache")
        self.file_tracker = FileTracker(cache_dir)

    def _init_llm(self):
        """Initialize LLM provider."""
        use_registry = self.config.get("llm.use_model_registry", False)
        default_model = self.config.get("llm.default_model")
        user_agent = self.config.get("llm.user_agent", "nanocode/1.0")
        proxy = self.config.proxy

        if use_registry and default_model:
            from nanocode.llm.router import get_router

            providers = self.config.get("llm.providers", {})
            router = get_router()

            for provider, config in providers.items():
                router.add_explicit_provider(provider, config)

            provider_config = router.get_provider_config(default_model)

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
                    default, **provider_config, user_agent=user_agent, proxy=proxy
                )
            else:
                self.llm = create_llm(
                    "openai",
                    api_key="dummy",
                    model="gpt-4",
                    user_agent=user_agent,
                    proxy=proxy,
                )

    def _init_tools(self):
        """Initialize tool system."""
        from nanocode.doom_loop import create_doom_loop_handler
        from nanocode.tools.task import create_task_tool

        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)

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
        )

        if system_prompt := ctx_config.get("system_prompt"):
            self.context_manager.set_system_prompt(system_prompt)

    def _init_mcp(self):
        """Initialize MCP connections."""
        self.mcp_manager = MCPManager()

        mcp_servers = self.config.mcp_servers
        for name, server_config in mcp_servers.items():
            self.mcp_manager.add_server(name, server_config)

    def _init_planning(self):
        """Initialize planning system."""
        self.planner = TaskPlanner(self.llm, self.tool_registry)
        self.plan_executor = PlanExecutor(self.planner, self.tool_executor)
        self.plan_monitor = PlanMonitor(self.llm)

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
                warning = self.doom_loop_handler.get_loop_warning()
                if warning:
                    logger.warning(
                        f"[{agent_name}] DOOM LOOP DETECTED for '{tool_name}': {warning}"
                    )
                    print(f"\n\033[91m{warning}\033[0m\n")

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
                                "result": f"Error: Doom loop detected - tool '{tool_name}' called repeatedly with same arguments. Permission denied.",
                                "success": False,
                            }
                        )
                        self.doom_loop_handler.reset(tool_name)
                        continue
                    elif doom_action == PermissionAction.ASK:
                        logger.debug(
                            f"[{agent_name}] Doom loop permission ASK for '{tool_name}'"
                        )

            if self.current_agent:
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
            result = await self.tool_executor.execute(tool_name, args)

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
        return f"\033[90m\033[3mThinking:\n{formatted}\033[0m"

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
        return hashlib.sha256(key.encode()).hexdigest()

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

        if tools:
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

        if tools:
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
        agent_name = self.current_agent.name if self.current_agent else "unknown"
        logger.info(f"[{agent_name}] Processing input: {user_input[:100]}...")

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

            messages = self.context_manager.prepare_messages()
            logger.debug(f"[{agent_name}] Context has {len(messages)} messages")

            if self.debug:
                print(
                    f"\n\033[96m[DEBUG] Sending {len(messages)} messages to LLM...\033[0m"
                )
                for i, msg in enumerate(messages):
                    content = (
                        msg.content
                        if hasattr(msg, "content")
                        else str(msg.get("content", ""))[:100]
                    )
                    role = msg.role if hasattr(msg, "role") else msg.get("role", "?")
                    print(f"  \033[90m{i}: {role}: {content}...\033[0m")

            if show_messages:
                print("\n\033[96m=== LLM REQUEST ===\033[0m")
                for i, msg in enumerate(messages):
                    content = (
                        msg.content
                        if hasattr(msg, "content")
                        else str(msg.get("content", ""))
                    )
                    role = msg.role if hasattr(msg, "role") else msg.get("role", "?")
                    print(f"\n[{i}] {role.upper()}:")
                    print(content[:500] if len(content) > 500 else content)
                print("\n")

            logger.debug(f"[{agent_name}] Sending request to LLM...")

            cached_response = self._check_cache(messages, tools)
            if cached_response:
                cache_logger.info(f"[{agent_name}] Using cached response")
                response = cached_response
            else:
                response = await self.llm.chat(
                    messages=messages,
                    tools=tools if tools else None,
                )
                self._put_cache(messages, tools, response)
                logger.info(f"[{agent_name}] LLM response received")

            if self.debug:
                print("\n\033[96m[DEBUG] LLM Response:\033[0m")
                if response.thinking:
                    print(f"  \033[93mThinking: {response.thinking[:200]}...\033[0m")
                if response.has_tool_calls:
                    print(
                        f"  \033[91mTool Calls: {[tc.name for tc in response.tool_calls]}\033[0m"
                    )
                else:
                    print(f"  \033[92mContent: {response.content[:200]}...\033[0m")

            if show_messages:
                print("\n\033[96m=== LLM RESPONSE ===\033[0m")
                if response.thinking:
                    print(f"\nThinking:\n{response.thinking[:500]}")
                if response.has_tool_calls:
                    print(f"\nTool Calls:")
                    for tc in response.tool_calls:
                        print(f"  - {tc.name}: {tc.arguments}")
                print(
                    f"\nContent:\n{response.content[:500] if response.content else '(empty)'}"
                )
                print()

            if response.thinking and show_thinking:
                print(f"\n{self._format_thinking(response.thinking)}")

            if response.has_tool_calls:
                logger.info(
                    f"[{agent_name}] LLM requested {len(response.tool_calls)} tool call(s): {[tc.name for tc in response.tool_calls]}"
                )
                if self.debug:
                    print(
                        f"\n\033[96m[DEBUG] Handling {len(response.tool_calls)} tool calls...\033[0m"
                    )
                tool_results = await self._handle_tool_calls(response.tool_calls)
                tool_results_history.extend(tool_results)

                for tr in tool_results:
                    if self.debug:
                        print(
                            f"\n\033[96m[DEBUG] Tool {tr['tool_name']} result:\033[0m {tr['result'][:200]}..."
                        )
                    result_content = tr["result"]
                    result_content = self.context_manager.truncate_tool_result(
                        result_content
                    )
                    self.context_manager.add_message(
                        "tool",
                        result_content,
                        tool_call_id=tr["tool_call_id"],
                    )

                messages = self.context_manager.prepare_messages()
                final_response = await self.llm.chat(messages=messages)
                content = final_response.content
            else:
                content = response.content

            self.context_manager.add_message("assistant", content)

            await self._generate_summary(tool_results_history)

            self.state.state = AgentState.COMPLETE

            return content

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
        except Exception:
            pass
