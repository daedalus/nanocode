"""Subagent delegation tool.

Spawning child agents with isolated context, restricted toolsets,
and optional credential overrides. Supports single-task and batch modes.

Each child gets:
  - A fresh conversation (no parent history)
  - Its own tool registry (restricted)
  - A focused system prompt built from the delegated goal + context
  - An optional different LLM provider/model

The parent's context only sees the delegation call and the result,
never the child's intermediate tool calls or reasoning.
"""

import asyncio
import json
import logging
import uuid

from nanocode.llm import create_llm
from nanocode.session.processor import SessionProcessor
from nanocode.tools import Tool, ToolExecutor, ToolRegistry, ToolResult

logger = logging.getLogger("nanocode.delegate")

# Tools that children must never have access to
DELEGATE_BLOCKED_TOOLS = frozenset({
    "delegate_task",
    "question",
    "task",
    "todowrite",
    "mcp",
})

MAX_DEPTH = 1

DELEGATE_DESCRIPTION = """Spawn a child agent to handle a task autonomously.

Use delegation when a task is self-contained, complex, and benefits from
independent execution — the child gets its own conversation, tools, and
optional model.

Modes:
  - Single: provide 'goal' (+ optional context, toolsets, role)
  - Batch:  provide 'tasks' array [{{goal, context, toolsets, role}}, ...]

The 'role' parameter controls whether the child can further delegate:
'leaf' (default) cannot; 'orchestrator' can spawn its own children.

Child agents have the following tools blocked for safety:
{blocked_tools}

Available tools for child agents:
{tools_list}

When to use:
  - Task requires independent research or exploration
  - Task has clear goal and can run in isolation
  - Multiple independent tasks that can run in parallel

When NOT to use:
  - Simple operations that can be done directly
  - Tasks requiring access to tools that are blocked
"""


class Subagent:
    """A lightweight isolated agent for delegated tasks."""

    def __init__(
        self,
        goal: str,
        context: str | None = None,
        tools: list[str] | None = None,
        parent_config: dict | None = None,
        parent_tool_registry: ToolRegistry | None = None,
        parent_llm=None,
        # Credential overrides
        override_provider: str | None = None,
        override_model: str | None = None,
        override_base_url: str | None = None,
        override_api_key: str | None = None,
        # Runtime settings
        max_iterations: int = 25,
        role: str = "leaf",
        depth: int = 0,
        session_id: str | None = None,
    ):
        self._goal = goal
        self._context = context
        self._max_iterations = max_iterations
        self._role = role
        self._depth = depth
        self._session_id = session_id or f"subagent-{uuid.uuid4().hex[:12]}"
        self._config = parent_config or {}

        system_prompt = self._build_system_prompt(goal, context, role, depth)
        self._init_llm(override_provider, override_model, override_base_url, override_api_key, parent_llm)
        self._init_tools(tools, parent_tool_registry)
        self._init_context(system_prompt)

    def _build_system_prompt(
        self, goal: str, context: str | None, role: str, depth: int
    ) -> str:
        parts = [
            "You are a focused subagent working on a delegated task.",
            "",
            f"Your goal: {goal}",
        ]
        if context:
            parts.extend(["", f"Background context:\n{context}"])
        parts.extend([
            "",
            "Focus only on this task. Do not ask questions, do not delegate further.",
            "Report your findings clearly when done.",
        ])
        if role == "orchestrator":
            parts.append("You CAN use the delegate_task tool to spawn your own child agents if needed.")
        return "\n".join(parts)

    def _init_llm(
        self,
        override_provider: str | None,
        override_model: str | None,
        override_base_url: str | None,
        override_api_key: str | None,
        parent_llm=None,
    ):
        if override_provider or override_model:
            provider: str = override_provider or str(getattr(parent_llm, "provider", "openai"))
            model: str = override_model or str(getattr(parent_llm, "model", "gpt-4o"))
            kwargs = {"model": model}
            if override_base_url:
                kwargs["base_url"] = override_base_url
            if override_api_key:
                kwargs["api_key"] = override_api_key
            self.llm = create_llm(provider, **kwargs)
        elif parent_llm is not None:
            self.llm = parent_llm
        else:
            from nanocode.llm.router import get_router
            router = get_router()
            default_model = self._config.get("llm.default_model", "openai/gpt-4o")
            provider_config = router.get_provider_config(default_model)
            self.llm = create_llm(
                provider_config.provider,
                base_url=provider_config.base_url,
                api_key=provider_config.api_key or "dummy",
                model=provider_config.model,
            )

    def _init_tools(
        self,
        allowed_tools: list[str] | None,
        parent_tool_registry: ToolRegistry | None,
    ):
        self.tool_registry = ToolRegistry()
        if parent_tool_registry:
            for name, tool in parent_tool_registry._tools.items():
                if name in DELEGATE_BLOCKED_TOOLS:
                    continue
                if allowed_tools and name not in allowed_tools:
                    continue
                self.tool_registry._tools[name] = tool

        self.tool_executor = ToolExecutor(self.tool_registry)

    def _init_context(self, system_prompt: str):
        from nanocode.context import ContextManager
        ctx_config = self._config.get("context", {})
        self.context_manager = ContextManager(
            max_tokens=ctx_config.get("max_tokens", 8000),
            preserve_system=ctx_config.get("preserve_system", True),
            preserve_last_n=ctx_config.get("preserve_last_n", 3),
            llm=self.llm,
            model=getattr(self.llm, "model", "gpt-4o"),
        )
        self.context_manager.set_system_prompt(system_prompt)

    async def run(self) -> str:
        """Execute the delegated task and return the result."""
        self.context_manager.add_message("user", self._goal)

        iteration = 0
        final_content = []

        while iteration < self._max_iterations:
            iteration += 1
            logger.info(
                "Subagent %s iteration %d/%d",
                self._session_id, iteration, self._max_iterations,
            )

            messages = self.context_manager.prepare_messages()
            tools = self.tool_registry.get_schemas()

            pipeline = self._get_pipeline()
            message = await pipeline.process_stream(
                session_id=self._session_id,
                messages=messages,
                tools=tools,
            )
            response = pipeline.to_llm_response(message)

            if response.thinking:
                pass

            if response.content:
                final_content.append(response.content)

            if not response.has_tool_calls:
                break

            self.context_manager.add_message(
                "assistant", None, tool_calls=response.tool_calls
            )

            for tc in response.tool_calls:
                tr = await self.tool_executor.execute(
                    tc.name, dict(tc.arguments) if hasattr(tc, "arguments") else {},
                    session_id=self._session_id,
                    agent_name="subagent",
                )
                content = str(tr.content) if tr.content else (tr.error or "")
                self.context_manager.add_tool_result(tc.name, tc.id, content)

        result = "\n".join(final_content) if final_content else "Task completed."
        logger.info("Subagent %s finished (%d iterations)", self._session_id, iteration)
        return result

    _pipeline_cache = None

    def _get_pipeline(self):
        if self._pipeline_cache is None:
            from nanocode.agent_pipeline import AgentPipeline
            self._pipeline_cache = AgentPipeline(
                llm=self.llm,
                processor=SessionProcessor(headless=True),
                context_manager=self.context_manager,
                tool_registry=self.tool_registry,
            )
        return self._pipeline_cache


def _build_tools_list(tool_registry: ToolRegistry | None) -> str:
    if tool_registry is None:
        return "  - (tools not available)"
    available = []
    for name, tool in tool_registry._tools.items():
        if name in DELEGATE_BLOCKED_TOOLS:
            continue
        desc = getattr(tool, "description", "") or ""
        available.append(f"  - {name}: {desc}")
    return "\n".join(available) if available else "  - (no tools available)"


class DelegateTool(Tool):
    """Tool for spawning child agents with isolated context."""

    def __init__(
        self,
        parent_tool_registry: ToolRegistry | None = None,
        parent_config: dict | None = None,
    ):
        self._parent_tool_registry = parent_tool_registry
        self._parent_config = parent_config or {}
        self._parent_llm = None
        self._delegate_depth: int = 0

        tools_list = _build_tools_list(parent_tool_registry)
        blocked = ", ".join(sorted(DELEGATE_BLOCKED_TOOLS))
        description = DELEGATE_DESCRIPTION.format(
            blocked_tools=blocked, tools_list=tools_list
        )

        super().__init__(
            name="delegate_task",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The task for the child agent to accomplish",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional background context for the child agent",
                    },
                    "toolsets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of tool names the child can use (default: all except blocked)",
                    },
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "goal": {"type": "string"},
                                "context": {"type": "string"},
                                "toolsets": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "role": {
                                    "type": "string",
                                    "enum": ["leaf", "orchestrator"],
                                },
                            },
                        },
                        "description": "Batch mode: array of task objects (each with 'goal')",
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional model override (e.g., 'openai/gpt-4o-mini')",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["leaf", "orchestrator"],
                        "description": "'leaf' (default) cannot delegate further. 'orchestrator' can.",
                    },
                },
            },
        )

    def set_parent_llm(self, llm):
        self._parent_llm = llm

    def set_delegate_depth(self, depth: int):
        self._delegate_depth = depth

    def _normalize_role(self, role: str | None) -> str:
        if role not in ("leaf", "orchestrator"):
            logger.warning("Unknown delegate_task role '%s', coercing to 'leaf'", role)
            return "leaf"
        return role

    def _resolve_model_overrides(self, model: str | None) -> dict:
        if not model or "/" not in model:
            return {"provider": None, "model": None, "base_url": None, "api_key": None}
        return {
            "provider": model.split("/")[0],
            "model": model,
            "base_url": None,
            "api_key": None,
        }

    def _build_task_list(self, kwargs: dict) -> ToolResult | list:
        goal = kwargs.get("goal", "")
        context = kwargs.get("context")
        toolsets = kwargs.get("toolsets")
        tasks = kwargs.get("tasks")
        role = self._normalize_role(kwargs.get("role", "leaf"))

        if tasks and isinstance(tasks, list):
            task_list = []
            for i, t in enumerate(tasks):
                if not isinstance(t, dict):
                    return ToolResult(
                        success=False,
                        error=f"Task {i} must be an object, got {type(t).__name__}.",
                    )
                if not t.get("goal", "").strip():
                    return ToolResult(
                        success=False,
                        error=f"Task {i} is missing a 'goal'.",
                    )
                t.setdefault("toolsets", toolsets)
                task_list.append(t)
            return task_list

        if goal and isinstance(goal, str) and goal.strip():
            return [{
                "goal": goal,
                "context": context,
                "toolsets": toolsets,
                "role": role,
            }]

        return ToolResult(
            success=False,
            error="Provide either 'goal' (single task) or 'tasks' (batch).",
        )

    def _create_subagent(self, task: dict, override: dict, role: str, depth: int) -> Subagent:
        return Subagent(
            goal=task["goal"],
            context=task.get("context"),
            tools=task.get("toolsets"),
            parent_config=self._parent_config,
            parent_tool_registry=self._parent_tool_registry,
            parent_llm=self._parent_llm,
            override_provider=override.get("provider"),
            override_model=override.get("model"),
            override_base_url=override.get("base_url"),
            override_api_key=override.get("api_key"),
            max_iterations=self._parent_config.get("delegation.max_iterations", 25),
            role=role,
            depth=depth,
        )

    async def _run_single_subagent(self, goal_text: str, child: Subagent) -> dict:
        try:
            result = await child.run()
            return {"goal": goal_text, "result": result, "success": True}
        except Exception as e:
            logger.error("Subagent failed: %s", e)
            return {"goal": goal_text, "result": str(e), "success": False}

    async def _run_batch_subagents(self, tasks_to_run: list) -> list[dict]:
        async def _run_one(gt: str, ch: Subagent) -> dict:
            try:
                r = await ch.run()
                return {"goal": gt, "result": r, "success": True}
            except Exception as e:
                return {"goal": gt, "result": str(e), "success": False}

        batch_results = await asyncio.gather(
            *[_run_one(g, c) for _, g, c in tasks_to_run],
            return_exceptions=True,
        )

        results = []
        for i, br in enumerate(batch_results):
            if isinstance(br, dict):
                results.append(br)
            elif isinstance(br, Exception):
                results.append({
                    "goal": tasks_to_run[i][1],
                    "result": str(br),
                    "success": False,
                })
        return results

    async def execute(self, **kwargs) -> ToolResult:
        role = self._normalize_role(kwargs.get("role", "leaf"))
        depth = self._delegate_depth

        if depth >= MAX_DEPTH:
            return ToolResult(
                success=False,
                error=f"Delegation depth limit reached (depth={depth}, max={MAX_DEPTH}).",
            )

        override = self._resolve_model_overrides(kwargs.get("model"))
        task_list = self._build_task_list(kwargs)
        if isinstance(task_list, ToolResult):
            return task_list

        logger.info(
            "DelegateTask: spawning %d subagent(s) (depth=%d, role=%s)",
            len(task_list), depth, role,
        )

        tasks_to_run = []
        for t in task_list:
            child_role = t.get("role", role)
            child = self._create_subagent(t, override, child_role, depth + 1)
            tasks_to_run.append((t["goal"], child))

        if len(tasks_to_run) == 1:
            results = [await self._run_single_subagent(tasks_to_run[0][0], tasks_to_run[0][1])]
        else:
            results = await self._run_batch_subagents(tasks_to_run)

        return ToolResult(
            success=True,
            content=json.dumps({"results": results}, indent=2),
            metadata={
                "subagent_count": len(results),
                "success_count": sum(1 for r in results if r.get("success")),
            },
        )


def create_delegate_tool(
    tool_registry: ToolRegistry | None = None,
    config: dict | None = None,
) -> DelegateTool:
    """Create and configure the delegate tool."""
    return DelegateTool(
        parent_tool_registry=tool_registry,
        parent_config=config,
    )
