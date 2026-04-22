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

logger = logging.getLogger("nanocode.tools")


@dataclass
class ToolResult:
    """Result from tool execution."""

    success: bool
    content: Any
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "content": self.content,
            "error": self.error,
            "metadata": self.metadata,
        }


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
            if isinstance(attr, type) and issubclass(attr, ToolClass) and attr is not ToolClass:
                try:
                    try:
                        instance = attr()
                    except TypeError:
                        instance = attr.__new__(attr)
                        if hasattr(instance, "name") and hasattr(instance, "description"):
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

    def __init__(self, registry: ToolRegistry, hook_manager: HookManager | None = None):
        self.registry = registry
        self.hook_manager = hook_manager
        self.execution_history: list[dict] = []
        logger.debug("ToolExecutor initialized")

    async def execute(self, tool_name: str, arguments: dict, session_id: str | None = None, agent_name: str | None = None) -> ToolResult:
        """Execute a tool by name with arguments."""
        logger.debug(f"ToolExecutor.execute('{tool_name}', {arguments})")

        # Run pre-tool hooks
        if self.hook_manager:
            hook_result = await self.hook_manager.run_pre_tool_hooks(
                tool_name, arguments, session_id, agent_name
            )
            if hook_result.action == HookAction.DENY:
                logger.warning(f"Tool '{tool_name}' blocked by pre-hook: {hook_result.message}")
                return ToolResult(
                    success=False,
                    content=None,
                    error=hook_result.message or "Tool blocked by hook",
                )
            if hook_result.modified_args:
                arguments = hook_result.modified_args
                logger.debug(f"Tool args modified by hook: {arguments}")

        tool = self.registry.get(tool_name)

        if not tool:
            logger.debug(
                f"Tool '{tool_name}' not found in registry, checking handlers..."
            )
            if handler := self.registry._handlers.get(tool_name):
                try:
                    logger.debug(f"Executing handler for '{tool_name}'")
                    result = await handler(**arguments)
                    result_obj = ToolResult(success=True, content=result)
                except Exception as e:
                    logger.error(f"Handler for '{tool_name}' failed: {e}")
                    result_obj = ToolResult(success=False, content=None, error=str(e))
            else:
                logger.warning(f"Unknown tool: '{tool_name}'")
                result_obj = ToolResult(
                    success=False, content=None, error=f"Unknown tool: {tool_name}"
                )
        else:
            logger.debug(f"Executing tool '{tool_name}'")
            result_obj = await tool.execute(**arguments)

        # Run post-tool hooks
        if self.hook_manager:
            await self.hook_manager.run_post_tool_hooks(
                tool_name,
                arguments,
                result_obj.content,
                result_obj.success,
                session_id,
                agent_name,
            )

        self.execution_history.append(
            {
                "tool": tool_name,
                "arguments": arguments,
                "result": result_obj.to_dict(),
            }
        )

        if result_obj.success:
            logger.info(f"Tool '{tool_name}' executed successfully")
        else:
            logger.warning(f"Tool '{tool_name}' failed: {result_obj.error}")

        return result_obj

    async def execute_multiple(
        self, tool_calls: list[tuple[str, dict]]
    ) -> list[ToolResult]:
        """Execute multiple tools in parallel."""
        logger.debug(f"execute_multiple: {len(tool_calls)} tools")
        tasks = [self.execute(name, args) for name, args in tool_calls]
        return await asyncio.gather(*tasks)

    def format_result(self, result: ToolResult) -> str:
        """Format tool result for LLM consumption."""
        if result.success:
            # Preserve string output as-is to avoid JSON encoding artifacts
            if isinstance(result.content, str):
                return result.content
            return json.dumps(result.content, default=str)
        else:
            return f"Error: {result.error}"
