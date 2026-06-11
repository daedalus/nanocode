"""Tool system for the autonomous agent."""

import asyncio
import inspect
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from nanocode.hooks import HookAction, HookEvent, HookManager, HookResult
from nanocode.tools.parallel import (
    ToolParallelismManager,
    ToolAccessMode,
    get_parallelism_manager,
)

logger = logging.getLogger("nanocode.tools")


@dataclass
class ToolResult:
    """Result from tool execution."""

    content: Any = None
    success: bool = True
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "content": self.content,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def ok(cls, content: Any, metadata: dict = None) -> "ToolResult":
        """Create a successful result."""
        return cls(success=True, content=content, metadata=metadata or {})

    @classmethod
    def err(cls, error: str, content: Any = None) -> "ToolResult":
        """Create an error result."""
        return cls(success=False, content=content, error=error)


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    name: str
    arguments: dict
    id: str = None

    def __post_init__(self):
        if self.id is None:
            import uuid
            self.id = f"call_{self.name}_{uuid.uuid4().hex[:8]}"

    @property
    def tool_name(self) -> str:
        """Alias for name for backward compatibility."""
        return self.name

    @tool_name.setter
    def tool_name(self, value: str):
        """Alias setter for name."""
        self.name = value

    @property
    def call_id(self) -> str:
        """Alias for id for backward compatibility."""
        return self.id

    @call_id.setter
    def call_id(self, value: str):
        """Alias setter for id."""
        self.id = value

    def __repr__(self):
        return f"ToolCall({self.name}, {self.arguments})"


class Tool(ABC):
    """Base class for agent tools."""

    def __init__(self, name: str, description: str, parameters: dict = None):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        pass

    def get_schema(self) -> dict:
        """Get the JSON schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate_args(self, args: dict) -> tuple[bool, str | None]:
        """Validate tool arguments against schema."""
        required = self.parameters.get("required", [])
        for req in required:
            if req not in args:
                return False, f"Missing required argument: {req}"
        return True, None


class FuncTool(Tool):
    """Tool wrapper around a function."""

    def __init__(
        self, func: Callable[..., Awaitable], name: str = None, description: str = None
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description or func.__doc__ or f"Execute {self.name}"

        sig = inspect.signature(func)
        properties = {}
        required = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            param_type = "string"
            if param.annotation != inspect.Parameter.empty:
                if param.annotation is int:
                    param_type = "integer"
                elif param.annotation is float:
                    param_type = "number"
                elif param.annotation is bool:
                    param_type = "boolean"
                elif param.annotation is list:
                    param_type = "array"
                elif param.annotation is dict:
                    param_type = "object"

            prop = {"type": param_type}
            if param.default != inspect.Parameter.empty:
                prop["default"] = param.default
            properties[param_name] = prop
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        super().__init__(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the wrapped function."""
        try:
            valid, error = self.validate_args(kwargs)
            if not valid:
                return ToolResult(success=False, content=None, error=error)

            result = await self.func(**kwargs)
            return ToolResult(success=True, content=result)
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class SyncFuncTool(FuncTool):
    """Tool wrapper around a synchronous function."""

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the wrapped synchronous function in executor."""
        try:
            valid, error = self.validate_args(kwargs)
            if not valid:
                return ToolResult(success=False, content=None, error=error)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: self.func(**kwargs))
            return ToolResult(success=True, content=result)
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class ToolRegistry:
    """Registry for managing available tools."""

    DEFAULT_TOOL_DIRS = [
        ".nanocode/tools",
        ".nanocode/tool",
        ".opencode/tools",
        ".claude/tools",
        ".codex/tools",
        ".gemini/tools",
        "tools",
        "tool",
    ]
    TOOL_FILE_EXTENSIONS = [".py"]

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._handlers: dict[str, Callable] = {}

    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def register_function(
        self, func: Callable, name: str = None, description: str = None
    ):
        """Register a function as a tool."""
        if asyncio.iscoroutinefunction(func):
            tool = FuncTool(func, name, description)
        else:
            tool = SyncFuncTool(func, name, description)
        self.register(tool)

    def register_handler(self, name: str, handler: Callable):
        """Register a custom handler for a tool name."""
        self._handlers[name] = handler

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        """Get schemas for all tools."""
        return [tool.get_schema() for tool in self._tools.values()]

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def unregister(self, name: str):
        """Unregister a tool."""
        self._tools.pop(name, None)

    def discover_tools(self, base_dir: str = None) -> list[Tool]:
        """Discover tools in configured directories."""
        import os

        base_dir = base_dir or os.getcwd()
        discovered = []

        for tool_dir in self.DEFAULT_TOOL_DIRS:
            tool_path = os.path.join(base_dir, tool_dir)
            if not os.path.isdir(tool_path):
                continue

            for root, dirs, files in os.walk(tool_path):
                for ext in self.TOOL_FILE_EXTENSIONS:
                    for filename in files:
                        if filename.endswith(ext) and not filename.startswith("_"):
                            tool_file = os.path.join(root, filename)
                            try:
                                tool = self._load_tool_file(tool_file)
                                if tool:
                                    discovered.append(tool)
                            except Exception:
                                pass

        return discovered

    def _load_tool_file(self, path: str) -> Tool | None:
        """Load a tool from a Python file."""
        import importlib.util
        import os

        from nanocode import tools

        module_name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        module.Tool = tools.Tool
        module.ToolResult = tools.ToolResult

        try:
            spec.loader.exec_module(module)
        except Exception:
            return None

        ToolClass = module.Tool
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, ToolClass)
                and attr is not ToolClass
            ):
                try:
                    try:
                        instance = attr()
                    except TypeError:
                        instance = attr.__new__(attr)
                        if hasattr(instance, "name") and hasattr(
                            instance, "description"
                        ):
                            pass
                        else:
                            continue
                    if hasattr(instance, "name") and instance.name:
                        return instance
                except Exception:
                    pass

        return None

    def load_discovered_tools(self, base_dir: str = None) -> int:
        """Load all discovered tools."""
        discovered = self.discover_tools(base_dir)
        for tool in discovered:
            self.register(tool)
            logger.info(f"Tool discovered: {tool.name}")

        return len(discovered)


class ToolExecutor:
    """Executes tools with proper error handling and result formatting."""

    def __init__(
        self,
        registry: ToolRegistry,
        hook_manager: HookManager | None = None,
        parallel: bool = True,
    ):
        self.registry = registry
        self.hook_manager = hook_manager
        self.execution_history: list[dict] = []
        self._parallel_enabled = parallel
        self._parallelism_manager = None
        if parallel:
            from nanocode.tools.parallel import get_parallelism_manager
            self._parallelism_manager = get_parallelism_manager()
        logger.debug(f"ToolExecutor initialized (parallel={parallel})")

    async def _run_pre_tool_hooks(
        self, tool_name: str, arguments: dict, session_id: str | None, agent_name: str | None
    ) -> tuple[dict | None, str | None]:
        """Run pre-tool hooks. Returns (modified_args, error_message) or (None, None) if allowed."""
        if not self.hook_manager:
            return None, None
        hook_result = await self.hook_manager.run_pre_tool_hooks(tool_name, arguments, session_id, agent_name)
        if hook_result.action == HookAction.DENY:
            return None, hook_result.message or "Tool blocked by hook"
        if hook_result.modified_args:
            return hook_result.modified_args, None
        return None, None

    async def _execute_handler(self, tool_name: str, arguments: dict) -> ToolResult:
        """Execute a handler for an unregistered tool name."""
        handler = self.registry._handlers.get(tool_name)
        if not handler:
            return ToolResult(success=False, content=None, error=f"Unknown tool: {tool_name}")
        try:
            result = await handler(**arguments)
            return ToolResult(success=True, content=result)
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))

    async def _execute_registered_tool(self, tool_name: str, arguments: dict, agent_name: str | None, session_id: str | None) -> ToolResult:
        """Execute a registered tool with validation and timing."""
        import time
        import json
        start = time.monotonic()
        if agent_name is not None:
            arguments["_agent_name"] = agent_name
        if session_id is not None:
            arguments["_session_id"] = session_id
        agent_info = await self._get_agent_info(agent_name)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as e:
                return ToolResult(success=False, error=f"Invalid JSON arguments for tool '{tool_name}': {e}")
        tool = self.registry.get(tool_name)
        if hasattr(tool, 'validate_args'):
            is_valid, error_msg = tool.validate_args(arguments)
            if not is_valid:
                return ToolResult(success=False, error=error_msg)
        self._inject_agent_schema(tool_name, agent_info)
        arguments.pop("_agent_name", None)
        arguments.pop("_session_id", None)
        result_obj = await tool.execute(**arguments)
        elapsed = time.monotonic() - start
        logger.debug(f"Tool '{tool_name}' executed in {elapsed:.2f}s")
        if elapsed > 5:
            logger.warning(f"Tool '{tool_name}' took {elapsed:.2f}s (>5s slow!)")
        return result_obj

    async def _get_agent_info(self, agent_name: str | None):
        if agent_name is None:
            return None
        try:
            from nanocode.agents import get_agent_registry
            registry = get_agent_registry()
            return registry.get(agent_name)
        except Exception:
            return None

    def _inject_agent_schema(self, tool_name: str, agent_info):
        """Pass agent_info to tools that support get_schema(agent_info)."""
        if agent_info is None:
            return
        tool = self.registry.get(tool_name)
        if hasattr(tool, 'get_schema'):
            try:
                tool.get_schema(agent_info)
            except TypeError:
                try:
                    tool.get_schema()
                except Exception:
                    pass

    async def _run_post_tool_hooks(self, tool_name: str, arguments: dict, result_obj: ToolResult, session_id: str | None, agent_name: str | None):
        if not self.hook_manager:
            return
        await self.hook_manager.run_post_tool_hooks(tool_name, arguments, result_obj.content, result_obj.success, session_id, agent_name)

    def _record_execution(self, tool_name: str, arguments: dict, result_obj: ToolResult):
        self.execution_history.append({"tool": tool_name, "arguments": arguments, "result": result_obj.to_dict()})

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        session_id: str | None = None,
        agent_name: str | None = None,
    ) -> ToolResult:
        """Execute a tool by name with arguments."""
        logger.debug(f"ToolExecutor.execute('{tool_name}', {arguments})")

        modified_args, hook_error = await self._run_pre_tool_hooks(tool_name, arguments, session_id, agent_name)
        if hook_error:
            return ToolResult(success=False, content=None, error=hook_error)
        if modified_args is not None:
            arguments = modified_args

        tool = self.registry.get(tool_name)
        if not tool:
            result_obj = await self._execute_handler(tool_name, arguments)
        else:
            result_obj = await self._execute_registered_tool(tool_name, arguments, agent_name, session_id)

        await self._run_post_tool_hooks(tool_name, arguments, result_obj, session_id, agent_name)
        self._record_execution(tool_name, arguments, result_obj)

        if result_obj.success:
            logger.info(f"Tool '{tool_name}' executed successfully")
        else:
            logger.warning(f"Tool '{tool_name}' failed: {result_obj.error}")

        return result_obj

    async def execute_multiple(
        self,
        tool_calls: list[tuple[str, dict]],
        session_id: str | None = None,
        agent_name: str | None = None,
    ) -> list[ToolResult]:
        """Execute multiple tools with parallel read-only, sequential writes.

        Args:
            tool_calls: List of (tool_name, arguments) tuples
            session_id: Optional session ID
            agent_name: Optional agent name

        Returns:
            List of ToolResult objects in order of input tool_calls
        """
        logger.debug(f"execute_multiple: {len(tool_calls)} tools")

        if not self._parallel_enabled or not self._parallelism_manager:
            # Fallback: execute all in parallel (original behavior)
            tasks = [self.execute(name, args, session_id, agent_name) for name, args in tool_calls]
            return await asyncio.gather(*tasks)

        # Use parallelism manager for smart execution
        return await self._parallelism_manager.execute_parallel(
            self, tool_calls, session_id, agent_name
        )

    def format_result(self, result: ToolResult) -> str:
        """Format tool result for LLM consumption."""
        if result.success:
            parts = []
            if result.content:
                parts.append(str(result.content))
            if result.metadata:
                meta_parts = []
                for key, value in result.metadata.items():
                    if key not in ("cached",):
                        val_str = (
                            str(value)
                            if not isinstance(value, (list, dict))
                            else repr(value)
                        )
                        meta_parts.append(f"{key}={val_str}")
                if meta_parts:
                    parts.append(f"[metadata: {', '.join(meta_parts)}]")
            return "\n\n".join(parts) if parts else "OK"
        else:
            return f"Error: {result.error}"
