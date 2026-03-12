"""Core agent implementation."""

import asyncio
import json
from typing import Any, Optional

from agent.llm import LLMBase, Message, create_llm
from agent.tools import ToolRegistry, ToolExecutor
from agent.tools.builtin import register_builtin_tools
from agent.tools.file_tracker import FileTracker
from agent.state import AgentState, AgentStateData, ExecutionPlan
from agent.planning import TaskPlanner, PlanExecutor, PlanMonitor, PlanningContext
from agent.mcp import MCPManager, FilesystemMCPServer, GitMCPServer
from agent.multimodal import MultimodalManager
from agent.lsp import LSPServerManager
from agent.context import ContextManager, ContextStrategy
from agent.config import get_config


class AutonomousAgent:
    """Main autonomous agent class."""

    def __init__(self, config: dict = None):
        self.config = config or get_config()
        self.state = AgentStateData()
        
        self._init_file_tracker()
        self._init_llm()
        self._init_tools()
        self._init_context()
        self._init_mcp()
        self._init_planning()
        self._init_multimodal()

    def _init_file_tracker(self):
        """Initialize file tracker for auto-reload on modification."""
        cache_dir = self.config.get("file_tracker.cache_dir", ".agent/cache")
        self.file_tracker = FileTracker(cache_dir)

    def _init_llm(self):
        """Initialize LLM provider."""
        use_registry = self.config.get("llm.use_model_registry", False)
        default_model = self.config.get("llm.default_model")
        
        if use_registry and default_model:
            from agent.llm.router import ProviderRouter, get_router
            
            providers = self.config.get("llm.providers", {})
            router = get_router()
            
            for provider, config in providers.items():
                router.add_explicit_provider(provider, config)
            
            provider_config = router.get_provider_config(default_model)
            
            from agent.llm import OpenAILLM, AnthropicLLM, OllamaLLM
            
            if provider_config.provider == "anthropic":
                self.llm = AnthropicLLM(
                    api_key=provider_config.api_key,
                    model=provider_config.model,
                )
            elif provider_config.provider == "ollama":
                self.llm = OllamaLLM(
                    base_url=provider_config.base_url,
                    model=provider_config.model,
                )
            else:
                self.llm = OpenAILLM(
                    base_url=provider_config.base_url,
                    api_key=provider_config.api_key or "dummy",
                    model=provider_config.model,
                )
        else:
            providers = self.config.providers
            default = self.config.default_provider
            
            if default in providers:
                provider_config = providers[default]
                self.llm = create_llm(default, **provider_config)
            else:
                self.llm = create_llm("openai", api_key="dummy", model="gpt-4")

    def _init_tools(self):
        """Initialize tool system."""
        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)
        
        register_builtin_tools(self.tool_registry, self.config.tools, self.file_tracker)
        
        self.tool_registry.register_handler("mcp", self._handle_mcp_tool)

    def _init_context(self):
        """Initialize context manager."""
        ctx_config = self.config.get("context", {})
        
        strategy_str = ctx_config.get("strategy", "sliding_window")
        strategy = ContextStrategy(strategy_str)
        
        self.context_manager = ContextManager(
            max_tokens=ctx_config.get("max_tokens", 8000),
            strategy=strategy,
            preserve_system=ctx_config.get("preserve_system", True),
            preserve_last_n=ctx_config.get("preserve_last_n", 3),
            llm=self.llm,
        )
        
        if system_prompt := ctx_config.get("system_prompt"):
            self.context_manager.set_system_prompt(system_prompt)

    def _init_mcp(self):
        """Initialize MCP connections."""
        self.mcp_manager = MCPManager()
        
        mcp_servers = self.config.mcp_servers
        for name, server_config in mcp_servers.items():
            self.mcp_manager.add_server(
                name=name,
                base_url=server_config.get("url"),
                headers=server_config.get("headers"),
            )

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
        """Handle tool calls from LLM."""
        results = []
        for tc in tool_calls:
            tool_name = tc.name
            args = tc.arguments
            
            result = await self.tool_executor.execute(tool_name, args)
            
            results.append({
                "tool_call_id": tc.id,
                "tool_name": tool_name,
                "result": self.tool_executor.format_result(result),
                "success": result.success,
            })
        
        return results

    async def process_input(self, user_input: str) -> str:
        """Process a user input through the agent."""
        self.state.state = AgentState.EXECUTING
        self.state.task = user_input
        
        self.context_manager.add_message("user", user_input)
        
        try:
            tools = self.tool_registry.get_schemas()
            messages = self.context_manager.prepare_messages()
            
            response = await self.llm.chat(
                messages=messages,
                tools=tools if tools else None,
            )
            
            if response.has_tool_calls:
                tool_results = await self._handle_tool_calls(response.tool_calls)
                
                for tr in tool_results:
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
            self.state.state = AgentState.COMPLETE
            
            return content
            
        except Exception as e:
            self.state.state = AgentState.ERROR
            self.state.error = str(e)
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
