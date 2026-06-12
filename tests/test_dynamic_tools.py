"""Tests for the Dynamic Tools system."""

import pytest
import tempfile
from pathlib import Path

from nanocode.dynamic_tools import (
    DynamicToolManager,
    DynamicToolExecutor,
    ASTToolParser,
    ToolSchema,
    get_dynamic_tool_manager,
    reset_dynamic_tool_manager,
)


class TestToolSchema:
    """Tests for ToolSchema dataclass."""

    def test_schema_creation(self):
        """Test creating a schema."""
        schema = ToolSchema(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            source_file="test.py",
            function_name="test_tool",
        )
        assert schema.name == "test_tool"
        assert schema.description == "A test tool"

    def test_to_openai_schema(self):
        """Test converting to OpenAI schema."""
        schema = ToolSchema(
            name="test",
            description="Test tool",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            source_file="test.py",
            function_name="test",
        )
        openai = schema.to_openai_schema()
        assert openai["type"] == "function"
        assert openai["function"]["name"] == "test"


class TestASTToolParser:
    """Tests for ASTToolParser."""

    def test_parse_file(self, tmp_path):
        """Test parsing a Python file."""
        tool_file = tmp_path / "test_tool.py"
        tool_file.write_text('''"""Test tool module."""


def my_tool(param1: str, param2: int = 10) -> str:
    """A test tool function.
    
    Args:
        param1: First parameter
        param2: Second parameter with default
    
    Returns:
        Result string
    """
    return f"{param1} {param2}"
''')

        parser = ASTToolParser()
        schemas = parser.parse_file(str(tool_file))

        assert len(schemas) == 1
        assert schemas[0].name == "my_tool"
        assert "param1" in schemas[0].parameters["properties"]
        assert "param2" in schemas[0].parameters["properties"]

    def test_parse_private_functions(self, tmp_path):
        """Test that private functions are skipped."""
        tool_file = tmp_path / "test_tool.py"
        tool_file.write_text('''"""Test module."""


def public_tool():
    """Public tool."""
    pass


def _private_tool():
    """Private tool - should be skipped."""
    pass
''')

        parser = ASTToolParser()
        schemas = parser.parse_file(str(tool_file))

        assert len(schemas) == 1
        assert schemas[0].name == "public_tool"

    def test_parse_no_docstring(self, tmp_path):
        """Test that functions without docstrings are skipped."""
        tool_file = tmp_path / "test_tool.py"
        tool_file.write_text('''"""Test module."""


def no_docstring():
    pass
''')

        parser = ASTToolParser()
        schemas = parser.parse_file(str(tool_file))

        assert len(schemas) == 0

    def test_parse_async_function(self, tmp_path):
        """Test parsing async functions."""
        tool_file = tmp_path / "test_tool.py"
        tool_file.write_text('''"""Test module."""


async def async_tool():
    """An async tool."""
    pass
''')

        parser = ASTToolParser()
        schemas = parser.parse_file(str(tool_file))

        assert len(schemas) == 1
        assert schemas[0].is_async is True


class TestDynamicToolExecutor:
    """Tests for DynamicToolExecutor."""

    def test_execute_tool(self, tmp_path):
        """Test executing a tool."""
        tool_file = tmp_path / "test_tool.py"
        tool_file.write_text('''"""Test tool."""


def add(a: int, b: int) -> int:
    """Add two numbers.
    
    Args:
        a: First number
        b: Second number
    
    Returns:
        Sum
    """
    return a + b
''')

        executor = DynamicToolExecutor()
        result = executor.execute_tool(str(tool_file), "add", {"a": 5, "b": 3})

        assert result["success"] is True
        assert result["result"] == 8

    def test_execute_tool_error(self, tmp_path):
        """Test executing a tool that fails."""
        tool_file = tmp_path / "test_tool.py"
        tool_file.write_text('''"""Test tool."""


def fail_tool():
    """A tool that fails."""
    raise ValueError("Intentional error")
''')

        executor = DynamicToolExecutor()
        result = executor.execute_tool(str(tool_file), "fail_tool", {})

        assert result["success"] is False
        assert "error" in result


class TestDynamicToolManager:
    """Tests for DynamicToolManager."""

    def test_init(self, tmp_path):
        """Test initialization."""
        manager = DynamicToolManager(tools_dir=str(tmp_path / "tools"))
        assert manager.tools_dir == tmp_path / "tools"

    def test_discover(self, tmp_path):
        """Test discovering tools."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "test_tool.py"
        tool_file.write_text('''"""Test tool."""


def my_tool():
    """A test tool."""
    pass
''')

        manager = DynamicToolManager(tools_dir=str(tools_dir))
        schemas = manager.discover()

        assert len(schemas) == 1
        assert schemas[0].name == "my_tool"

    def test_get_schema(self, tmp_path):
        """Test getting schema by name."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "test.py"
        tool_file.write_text('''"""Test."""


def my_tool():
    """My tool."""
    pass
''')

        manager = DynamicToolManager(tools_dir=str(tools_dir))
        manager.discover()

        schema = manager.get_schema("my_tool")
        assert schema is not None
        assert schema.name == "my_tool"

    def test_list_tools(self, tmp_path):
        """Test listing tools."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "test.py"
        tool_file.write_text('''"""Test."""


def tool_a():
    """Tool A."""
    pass


def tool_b():
    """Tool B."""
    pass
''')

        manager = DynamicToolManager(tools_dir=str(tools_dir))
        manager.discover()

        tools = manager.list_tools()
        assert "tool_a" in tools
        assert "tool_b" in tools

    def test_execute(self, tmp_path):
        """Test executing a tool by name."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "calc.py"
        tool_file.write_text('''"""Calculator."""


def multiply(a: int, b: int) -> int:
    """Multiply two numbers.
    
    Args:
        a: First number
        b: Second number
    
    Returns:
        Product
    """
    return a * b
''')

        manager = DynamicToolManager(tools_dir=str(tools_dir))
        manager.discover()

        result = manager.execute("multiply", {"a": 4, "b": 5})
        assert result["success"] is True
        assert result["result"] == 20

    def test_execute_not_found(self, tmp_path):
        """Test executing non-existent tool."""
        manager = DynamicToolManager(tools_dir=str(tmp_path))
        result = manager.execute("nonexistent", {})
        assert result["success"] is False

    def test_register_tool(self, tmp_path):
        """Test registering a tool from function."""
        manager = DynamicToolManager(tools_dir=str(tmp_path))

        def my_func(x: str) -> str:
            """My function."""
            return x.upper()

        manager.register_tool("my_func", my_func)
        assert "my_func" in manager.list_tools()

    def test_get_schemas(self, tmp_path):
        """Test getting all schemas."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "test.py"
        tool_file.write_text('''"""Test."""


def tool_a():
    """Tool A."""
    pass
''')

        manager = DynamicToolManager(tools_dir=str(tools_dir))
        manager.discover()

        schemas = manager.get_schemas()
        assert len(schemas) == 1


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_dynamic_tool_manager_singleton(self):
        """Test global instance is singleton."""
        reset_dynamic_tool_manager()
        m1 = get_dynamic_tool_manager()
        m2 = get_dynamic_tool_manager()
        assert m1 is m2

    def test_reset_dynamic_tool_manager(self):
        """Test resetting global instance."""
        m1 = get_dynamic_tool_manager()
        reset_dynamic_tool_manager()
        m2 = get_dynamic_tool_manager()
        assert m1 is not m2
