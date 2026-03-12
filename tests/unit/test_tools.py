"""Tests for tool system."""

import pytest
import tempfile
import os
from pathlib import Path

from agent.tools import Tool, ToolResult, ToolRegistry, ToolExecutor, FuncTool, SyncFuncTool


class TestToolResult:
    """Test tool result."""

    def test_success_result(self):
        """Test successful result."""
        result = ToolResult(success=True, content="Hello")
        
        assert result.success is True
        assert result.content == "Hello"
        assert result.error is None

    def test_error_result(self):
        """Test error result."""
        result = ToolResult(success=False, content=None, error="Something went wrong")
        
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_to_dict(self):
        """Test serialization."""
        result = ToolResult(success=True, content="test", metadata={"key": "value"})
        
        d = result.to_dict()
        
        assert d["success"] is True
        assert d["content"] == "test"
        assert d["metadata"]["key"] == "value"


class MockTool(Tool):
    """Mock tool for testing."""
    
    def __init__(self, should_succeed: bool = True):
        super().__init__(
            name="mock_tool",
            description="A mock tool for testing",
        )
        self.should_succeed = should_succeed
    
    async def execute(self, **kwargs) -> ToolResult:
        if self.should_succeed:
            return ToolResult(success=True, content=f"Executed with {kwargs}")
        return ToolResult(success=False, content=None, error="Mock error")


class TestToolRegistry:
    """Test tool registry."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry."""
        return ToolRegistry()

    def test_register_tool(self, registry):
        """Test registering a tool."""
        tool = MockTool()
        registry.register(tool)
        
        assert registry.has_tool("mock_tool")
        assert registry.get("mock_tool") == tool

    def test_unregister_tool(self, registry):
        """Test unregistering a tool."""
        tool = MockTool()
        registry.register(tool)
        
        registry.unregister("mock_tool")
        
        assert not registry.has_tool("mock_tool")

    def test_list_tools(self, registry):
        """Test listing tools."""
        registry.register(MockTool())
        
        tools = registry.list_tools()
        
        assert len(tools) >= 1

    def test_get_schemas(self, registry):
        """Test getting tool schemas."""
        registry.register(MockTool())
        
        schemas = registry.get_schemas()
        
        assert len(schemas) >= 1
        assert schemas[0]["type"] == "function"

    def test_register_handler(self, registry):
        """Test registering custom handler."""
        def custom_handler(**kwargs):
            return "handled"
        
        registry.register_handler("custom", custom_handler)
        
        assert "custom" in registry._handlers


class TestToolExecutor:
    """Test tool executor."""

    @pytest.fixture
    def executor(self):
        """Create executor with registry."""
        registry = ToolRegistry()
        registry.register(MockTool(should_succeed=True))
        return ToolExecutor(registry)

    @pytest.mark.asyncio
    async def test_execute_tool(self, executor):
        """Test executing a tool."""
        result = await executor.execute("mock_tool", {"arg": "value"})
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, executor):
        """Test executing unknown tool."""
        result = await executor.execute("nonexistent_tool", {})
        
        assert result.success is False
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_format_result(self, executor):
        """Test formatting result."""
        result = ToolResult(success=True, content={"key": "value"})
        formatted = executor.format_result(result)
        
        assert "key" in formatted


class TestFuncTool:
    """Test function-based tools."""

    @pytest.mark.asyncio
    async def test_async_func_tool(self):
        """Test async function tool."""
        async def greet(name: str) -> str:
            return f"Hello, {name}!"
        
        tool = FuncTool(greet)
        
        result = await tool.execute(name="World")
        
        assert result.success is True
        assert result.content == "Hello, World!"

    @pytest.mark.asyncio
    async def test_sync_func_tool(self):
        """Test sync function tool."""
        def add(a: int, b: int) -> int:
            return a + b
        
        tool = SyncFuncTool(add)
        
        result = await tool.execute(a=2, b=3)
        
        assert result.success is True
        assert result.content == 5

    def test_func_tool_schema(self):
        """Test function tool schema generation."""
        def multiply(x: int, y: int = 1) -> int:
            return x * y
        
        tool = FuncTool(multiply)
        schema = tool.get_schema()
        
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "multiply"
        assert "x" in schema["function"]["parameters"]["properties"]
        assert "y" in schema["function"]["parameters"]["properties"]

    def test_validate_args(self):
        """Test argument validation."""
        def divide(a: int, b: int) -> float:
            return a / b
        
        tool = FuncTool(divide)
        
        valid, error = tool.validate_args({"a": 10, "b": 2})
        assert valid is True
        
        valid, error = tool.validate_args({"a": 10})
        assert valid is False
        assert "Missing required argument: b" in error


class TestBuiltinTools:
    """Test built-in tools."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_read_file(self, temp_dir):
        """Test read file tool."""
        from agent.tools.builtin import ReadFileTool
        
        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello, World!")
        
        tool = ReadFileTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt")
        
        assert result.success is True
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir):
        """Test write file tool."""
        from agent.tools.builtin import WriteFileTool
        
        tool = WriteFileTool(root_dir=temp_dir)
        result = await tool.execute(path="output.txt", content="Test content")
        
        assert result.success is True
        
        output_path = os.path.join(temp_dir, "output.txt")
        assert Path(output_path).read_text() == "Test content"

    @pytest.mark.asyncio
    async def test_glob(self, temp_dir):
        """Test glob tool."""
        from agent.tools.builtin import GlobTool
        
        Path(os.path.join(temp_dir, "file1.py")).touch()
        Path(os.path.join(temp_dir, "file2.txt")).touch()
        Path(os.path.join(temp_dir, "file3.py")).touch()
        
        tool = GlobTool(root_dir=temp_dir)
        result = await tool.execute(pattern="*.py")
        
        assert result.success is True
        assert result.metadata["count"] == 2

    @pytest.mark.asyncio
    async def test_ls(self, temp_dir):
        """Test ls tool."""
        from agent.tools.builtin import ListDirTool
        
        Path(os.path.join(temp_dir, "file1.txt")).touch()
        Path(os.path.join(temp_dir, "file2.txt")).touch()
        
        tool = ListDirTool(root_dir=temp_dir)
        result = await tool.execute()
        
        assert result.success is True
        assert "file1.txt" in result.content
