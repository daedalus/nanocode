"""Core agent implementation."""

import json
import logging
import traceback
from typing import Optional

from nanocode.llm import create_llm
from nanocode.tools import ToolRegistry, ToolExecutor
from nanocode.tools.builtin import register_builtin_tools
from nanocode.tools.file_tracker import FileTracker
from nanocode.state import AgentState, AgentStateData
from nanocode.planning import TaskPlanner, PlanExecutor, PlanMonitor, PlanningContext
from nanocode.mcp import MCPManager
from nanocode.multimodal import MultimodalManager
from nanocode.lsp import LSPServerManager
from nanocode.context import ContextManager, ContextStrategy
from nanocode.config import get_config
from nanocode.agents import AgentInfo, get_agent_registry, PermissionAction
from nanocode.agents.permission import (
    PermissionHandler,
)
from nanocode.session_summary import SessionSummaryGenerator

tool_logger = logging.getLogger("nanocode.tools")


class AutonomousAgent:
    """Main autonomous agent class."""

    def __init__(self, config: Optional[dict] = None):
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

    def _init_agents(self):
        """Initialize agent system."""
        self.agent_registry = get_agent_registry()
        self.current_agent = self.agent_registry.get_default()
        self.permission_handler = PermissionHandler()

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
        agent = self.agent_registry.get(agent_name)
        if agent is None:
            return False
        self.current_agent = agent
        if agent.system_prompt:
            self.context_manager.set_system_prompt(agent.system_prompt)
        return True

    def get_current_agent(self) -> Optional[AgentInfo]:
        """Get the current agent."""
        return self.current_agent

    def list_agents(self) -> list[AgentInfo]:
        """List available agents."""
        return self.agent_registry.list_primary()

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
        use_storage = self.config.get("storage.enabled", True)

    def _init_file_tracker(self):
        """Initialize file tracker for auto-reload on modification."""
        cache_dir = self.config.get("file_tracker.cache_dir", ".agent/cache")
        self.file_tracker = FileTracker(cache_dir)

    def _init_llm(self):
        """Initialize LLM provider."""
        use_registry = self.config.get("llm.use_model_registry", False)
        default_model = self.config.get("llm.default_model")
        user_agent = self.config.get("llm.user_agent", "nanocode/1.0")

        if use_registry and default_model:
            from nanocode.llm.router import get_router

            providers = self.config.get("llm.providers", {})
            router = get_router()

            for provider, config in providers.items():
                router.add_explicit_provider(provider, config)

            provider_config = router.get_provider_config(default_model)

            from nanocode.llm import OpenAILLM, AnthropicLLM, OllamaLLM

            if provider_config.provider == "anthropic":
                self.llm = AnthropicLLM(
                    api_key=provider_config.api_key,
                    model=provider_config.model,
                    user_agent=user_agent,
                )
            elif provider_config.provider == "ollama":
                self.llm = OllamaLLM(
                    base_url=provider_config.base_url,
                    model=provider_config.model,
                    user_agent=user_agent,
                )
            else:
                self.llm = OpenAILLM(
                    base_url=provider_config.base_url,
                    api_key=provider_config.api_key or "dummy",
                    model=provider_config.model,
                    user_agent=user_agent,
                )
        else:
            providers = self.config.providers
            default = self.config.default_provider

            if default in providers:
                provider_config = providers[default]
                self.llm = create_llm(default, **provider_config, user_agent=user_agent)
            else:
                self.llm = create_llm(
                    "openai", api_key="dummy", model="gpt-4", user_agent=user_agent
                )

    def _init_tools(self):
        """Initialize tool system."""
        from nanocode.tools.task import create_task_tool
        from nanocode.doom_loop import create_doom_loop_handler

        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)

        register_builtin_tools(
            self.tool_registry, self.config.tools, self.file_tracker, self.lsp_manager
        )

        self.task_tool = create_task_tool(self.agent_registry, self.permission_handler)
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
        results = []
        for tc in tool_calls:
            tool_name = tc.name
            args = tc.arguments

            is_doom_loop = self.doom_loop_handler.check_tool_call(tool_name, args)
            if is_doom_loop:
                warning = self.doom_loop_handler.get_loop_warning()
                if warning:
                    print(f"\n\033[91m{warning}\033[0m\n")

                if self.current_agent:
                    doom_action = self.permission_handler.check_permission(
                        self.current_agent, "doom_loop", {"tool": tool_name, "args": args}
                    )
                    if doom_action == PermissionAction.DENY:
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

            if self.current_agent:
                action = self.permission_handler.check_permission(
                    self.current_agent, tool_name, args
                )
                if action == PermissionAction.DENY:
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
                    try:
                        await self.permission_handler.request_permission(
                            self.current_agent, tool_name, args
                        )
                    except Exception as e:
                        results.append(
                            {
                                "tool_call_id": tc.id,
                                "tool_name": tool_name,
                                "result": f"Error: {str(e)}",
                                "success": False,
                            }
                        )
                        continue

            result = await self.tool_executor.execute(tool_name, args)

            tool_logger.debug(f"Tool call: {tool_name}({args}) -> success={result.success}")

            results.append(
                {
                    "tool_call_id": tc.id,
                    "tool_name": tool_name,
                    "result": self.tool_executor.format_result(result),
                    "success": result.success,
                }
            )

        return results

    def _format_thinking(self, thinking: str) -> str:
        """Format thinking content for display."""
        lines = thinking.strip().split("\n")
        formatted = "\n".join(f"  {line}" for line in lines)
        return f"\033[90m\033[3mThinking:\n{formatted}\033[0m"

    async def process_input(self, user_input: str, show_thinking: bool = True) -> str:
        """Process a user input through the agent."""
        self.state.state = AgentState.EXECUTING
        self.state.task = user_input

        if hasattr(self, "task_tool"):
            self.task_tool.update_description(self.current_agent)

        self.context_manager.add_message("user", user_input)

        tool_results_history = []

        try:
            tools = self.tool_registry.get_schemas()
            messages = self.context_manager.prepare_messages()

            if self.debug:
                print(f"\n\033[96m[DEBUG] Sending {len(messages)} messages to LLM...\033[0m")
                for i, msg in enumerate(messages):
                    content = (
                        msg.content
                        if hasattr(msg, "content")
                        else str(msg.get("content", ""))[:100]
                    )
                    role = msg.role if hasattr(msg, "role") else msg.get("role", "?")
                    print(f"  \033[90m{i}: {role}: {content}...\033[0m")

            response = await self.llm.chat(
                messages=messages,
                tools=tools if tools else None,
            )

            if self.debug:
                print("\n\033[96m[DEBUG] LLM Response:\033[0m")
                if response.thinking:
                    print(f"  \033[93mThinking: {response.thinking[:200]}...\033[0m")
                if response.has_tool_calls:
                    print(f"  \033[91mTool Calls: {[tc.name for tc in response.tool_calls]}\033[0m")
                else:
                    print(f"  \033[92mContent: {response.content[:200]}...\033[0m")

            if response.thinking and show_thinking:
                print(f"\n{self._format_thinking(response.thinking)}")

            if response.has_tool_calls:
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
                    result_content = self.context_manager.truncate_tool_result(result_content)
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

        history = [{"role": m.role, "content": m.content} for m in self.context_manager._messages]

        context = PlanningContext(
            task=task,
            tools=[json.loads(t.get("function", {}).get("parameters", "{}")) for t in tools],
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
        return self.state.to_dict()

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
                        msg.get_text_content() if hasattr(msg, "get_text_content") else str(msg)
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
