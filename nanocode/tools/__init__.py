"""Tool system for the autonomous agent."""

import asyncio
import inspect
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Optional

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


class ToolExecutor:
    """Executes tools with proper error handling and result formatting."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.execution_history: list[dict] = []
        logger.debug("ToolExecutor initialized")

    async def execute(self, tool_name: str, arguments: dict) -> ToolResult:
        """Execute a tool by name with arguments."""
        logger.debug(f"ToolExecutor.execute('{tool_name}', {arguments})")

        tool = self.registry.get(tool_name)

        if not tool:
            logger.debug(
                f"Tool '{tool_name}' not found in registry, checking handlers..."
            )
            if handler := self.registry._handlers.get(tool_name):
                try:
                    logger.debug(f"Executing handler for '{tool_name}'")
                    result = await handler(**arguments)
                    return ToolResult(success=True, content=result)
                except Exception as e:
                    logger.error(f"Handler for '{tool_name}' failed: {e}")
                    return ToolResult(success=False, content=None, error=str(e))
            logger.warning(f"Unknown tool: '{tool_name}'")
            return ToolResult(
                success=False, content=None, error=f"Unknown tool: {tool_name}"
            )

        logger.debug(f"Executing tool '{tool_name}'")
        result = await tool.execute(**arguments)

        self.execution_history.append(
            {
                "tool": tool_name,
                "arguments": arguments,
                "result": result.to_dict(),
            }
        )

        if result.success:
            logger.info(f"Tool '{tool_name}' executed successfully")
        else:
            logger.warning(f"Tool '{tool_name}' failed: {result.error}")

        return result

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
