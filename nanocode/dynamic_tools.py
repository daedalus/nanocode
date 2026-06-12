"""Dynamic Tools - AST-parse tool files, extract schemas, execute in isolation.

Enhances existing discover_tools() with:
- AST parsing for better schema generation
- Subprocess isolation for execution
- Automatic schema generation from function signatures
- Validation and error handling
"""

import ast
import inspect
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolSchema:
    """Schema for a dynamic tool."""

    name: str
    description: str
    parameters: Dict[str, Any]
    source_file: str
    function_name: str
    is_async: bool = False
    tags: List[str] = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ASTToolParser:
    """Parse Python files using AST to extract tool schemas."""

    def parse_file(self, file_path: str) -> List[ToolSchema]:
        """Parse a Python file and extract tool schemas.

        Args:
            file_path: Path to Python file

        Returns:
            List of ToolSchema objects
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content, filename=file_path)
            schemas = []

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    schema = self._parse_function(node, file_path, content)
                    if schema:
                        schemas.append(schema)

            return schemas

        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return []

    def _parse_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path: str,
        content: str,
    ) -> Optional[ToolSchema]:
        """Parse a function definition into a ToolSchema."""
        # Skip private functions
        if node.name.startswith("_"):
            return None

        # Get docstring
        docstring = ast.get_docstring(node) or ""
        if not docstring:
            return None  # Require docstring for tool

        # Parse parameters
        parameters = self._parse_parameters(node)

        # Check for tags in docstring
        tags = self._extract_tags(docstring)

        return ToolSchema(
            name=node.name,
            description=docstring.split("\n")[0],  # First line
            parameters=parameters,
            source_file=file_path,
            function_name=node.name,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            tags=tags,
        )

    def _parse_parameters(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Dict[str, Any]:
        """Parse function parameters into JSON Schema."""
        properties = {}
        required = []

        for arg in node.args.args:
            if arg.arg in ("self", "cls"):
                continue

            prop = {"type": "string"}  # Default type

            # Try to infer type from annotation
            if arg.annotation:
                prop["type"] = self._annotation_to_type(arg.annotation)

            # Check for default value
            if arg.arg in [a.arg for a in node.args.args]:
                idx = [a.arg for a in node.args.args].index(arg.arg)
                defaults = node.args.defaults
                if idx >= len(node.args.args) - len(defaults):
                    # Has default value
                    default_idx = idx - (len(node.args.args) - len(defaults))
                    default_value = defaults[default_idx]
                    prop["default"] = self._ast_to_python(default_value)
                else:
                    required.append(arg.arg)

            properties[arg.arg] = prop

        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema

    def _annotation_to_type(self, annotation: ast.AST) -> str:
        """Convert AST annotation to JSON Schema type."""
        if isinstance(annotation, ast.Name):
            type_map = {
                "str": "string",
                "int": "integer",
                "float": "number",
                "bool": "boolean",
                "list": "array",
                "dict": "object",
                "List": "array",
                "Dict": "object",
                "Optional": "string",
            }
            return type_map.get(annotation.id, "string")
        elif isinstance(annotation, ast.Constant):
            return "string"
        return "string"

    def _ast_to_python(self, node: ast.AST) -> Any:
        """Convert AST node to Python value."""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            return None
        elif isinstance(node, ast.List):
            return [self._ast_to_python(elt) for elt in node.elts]
        elif isinstance(node, ast.Dict):
            return {
                self._ast_to_python(k): self._ast_to_python(v)
                for k, v in zip(node.keys, node.values)
            }
        return None

    def _extract_tags(self, docstring: str) -> List[str]:
        """Extract tags from docstring."""
        tags = []
        for line in docstring.split("\n"):
            line = line.strip()
            if line.startswith("Tags:"):
                tags_str = line[5:].strip()
                tags = [t.strip() for t in tags_str.split(",")]
            elif line.startswith("#"):
                tags.append(line[1:].strip())
        return tags


class DynamicToolExecutor:
    """Execute dynamic tools in isolated subprocess."""

    def __init__(self, timeout: int = 30):
        """Initialize the executor.

        Args:
            timeout: Execution timeout in seconds
        """
        self.timeout = timeout

    def execute_tool(
        self,
        tool_file: str,
        function_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a tool function in isolation.

        Args:
            tool_file: Path to the tool file
            function_name: Function to execute
            arguments: Function arguments

        Returns:
            Dict with result or error
        """
        # Create a wrapper script
        wrapper_script = self._create_wrapper(tool_file, function_name, arguments)

        try:
            result = subprocess.run(
                [sys.executable, "-c", wrapper_script],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode == 0:
                import json
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"success": True, "output": result.stdout}
            else:
                return {
                    "success": False,
                    "error": result.stderr or "Tool execution failed",
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Tool timed out after {self.timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_wrapper(
        self,
        tool_file: str,
        function_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """Create a wrapper script for isolated execution."""
        import json

        args_json = json.dumps(arguments)

        return f"""
import sys
import json
import importlib.util
import asyncio

# Load the tool module
spec = importlib.util.spec_from_file_location("tool_module", "{tool_file}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Get the function
func = getattr(module, "{function_name}")

# Execute with arguments
args = json.loads('{args_json}')
try:
    result = func(**args)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    print(json.dumps({{"success": True, "result": result}}))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
    sys.exit(1)
"""


class DynamicToolManager:
    """Manage dynamic tools with AST parsing and isolation."""

    def __init__(self, tools_dir: Optional[str] = None):
        """Initialize the dynamic tool manager.

        Args:
            tools_dir: Directory to scan for tools
        """
        if tools_dir is None:
            tools_dir = os.path.join(os.getcwd(), ".nanocode", "tools")
        self.tools_dir = Path(tools_dir)
        self.parser = ASTToolParser()
        self.executor = DynamicToolExecutor()
        self._schemas: Dict[str, ToolSchema] = {}
        self._loaded_modules: Dict[str, Any] = {}

    def discover(self) -> List[ToolSchema]:
        """Discover all tools in the tools directory.

        Returns:
            List of discovered tool schemas
        """
        schemas = []

        if not self.tools_dir.exists():
            return schemas

        for py_file in self.tools_dir.glob("**/*.py"):
            if py_file.name.startswith("_"):
                continue

            file_schemas = self.parser.parse_file(str(py_file))
            for schema in file_schemas:
                self._schemas[schema.name] = schema
                schemas.append(schema)

        logger.info(f"Discovered {len(schemas)} dynamic tools")
        return schemas

    def get_schema(self, tool_name: str) -> Optional[ToolSchema]:
        """Get schema for a tool."""
        return self._schemas.get(tool_name)

    def list_tools(self) -> List[str]:
        """List all discovered tool names."""
        return list(self._schemas.keys())

    def get_schemas(self) -> List[ToolSchema]:
        """Get all discovered schemas."""
        return list(self._schemas.values())

    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a tool by name.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Execution result
        """
        schema = self._schemas.get(tool_name)
        if not schema:
            return {"success": False, "error": f"Tool not found: {tool_name}"}

        return self.executor.execute_tool(
            schema.source_file,
            schema.function_name,
            arguments,
        )

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        """Register a tool from a function.

        Args:
            name: Tool name
            func: Tool function
            description: Tool description
            parameters: JSON Schema for parameters
        """
        if not description:
            description = func.__doc__ or f"Execute {name}"

        if parameters is None:
            parameters = self._generate_schema_from_function(func)

        schema = ToolSchema(
            name=name,
            description=description,
            parameters=parameters,
            source_file=func.__module__ or "",
            function_name=name,
            is_async=inspect.iscoroutinefunction(func),
        )

        self._schemas[name] = schema

    def _generate_schema_from_function(self, func: Callable) -> Dict[str, Any]:
        """Generate JSON Schema from function signature."""
        sig = inspect.signature(func)
        properties = {}
        required = []

        for name, param in sig.parameters.items():
            prop = {"type": "string"}

            if param.annotation != inspect.Parameter.empty:
                type_map = {
                    str: "string",
                    int: "integer",
                    float: "number",
                    bool: "boolean",
                    list: "array",
                    dict: "object",
                }
                prop["type"] = type_map.get(param.annotation, "string")

            if param.default != inspect.Parameter.empty:
                prop["default"] = param.default
            else:
                required.append(name)

            properties[name] = prop

        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema


# Global instance
_dynamic_tool_manager: Optional[DynamicToolManager] = None


def get_dynamic_tool_manager(tools_dir: Optional[str] = None) -> DynamicToolManager:
    """Get or create the global dynamic tool manager."""
    global _dynamic_tool_manager
    if _dynamic_tool_manager is None:
        _dynamic_tool_manager = DynamicToolManager(tools_dir)
    return _dynamic_tool_manager


def reset_dynamic_tool_manager():
    """Reset the global dynamic tool manager."""
    global _dynamic_tool_manager
    _dynamic_tool_manager = None
