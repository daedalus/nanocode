"""Tests for tool system."""

import pytest
import tempfile
import os
from pathlib import Path

from nanocode.tools import Tool, ToolResult, ToolRegistry, ToolExecutor, FuncTool, SyncFuncTool


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
        from nanocode.tools.builtin import ReadFileTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello, World!")

        tool = ReadFileTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt")

        assert result.success is True
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir):
        """Test write file tool."""
        from nanocode.tools.builtin import WriteFileTool

        tool = WriteFileTool(root_dir=temp_dir)
        result = await tool.execute(path="output.txt", content="Test content")

        assert result.success is True

        output_path = os.path.join(temp_dir, "output.txt")
        assert Path(output_path).read_text() == "Test content"

    @pytest.mark.asyncio
    async def test_glob(self, temp_dir):
        """Test glob tool."""
        from nanocode.tools.builtin import GlobTool

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
        from nanocode.tools.builtin import ListDirTool

        Path(os.path.join(temp_dir, "file1.txt")).touch()
        Path(os.path.join(temp_dir, "file2.txt")).touch()

        tool = ListDirTool(root_dir=temp_dir)
        result = await tool.execute()

        assert result.success is True
        assert "file1.txt" in result.content


class TestNewTools:
    """Test newly added tools."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_batch_tool(self):
        """Test batch tool executes multiple tools."""
        from nanocode.tools.builtin import BatchTool
        from nanocode.tools import ToolRegistry, ToolExecutor

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        tool = BatchTool(tool_executor=executor)

        result = await tool.execute(tool_calls=[])

        assert result.success is True
        assert "0" in result.content

    @pytest.mark.asyncio
    async def test_batch_tool_with_calls(self, temp_dir):
        """Test batch tool with actual tool calls."""
        from nanocode.tools.builtin import BatchTool, ReadFileTool
        from nanocode.tools import ToolRegistry, ToolExecutor

        registry = ToolRegistry()
        registry.register(ReadFileTool(root_dir=temp_dir))
        executor = ToolExecutor(registry)
        tool = BatchTool(tool_executor=executor)

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello, World!")

        result = await tool.execute(
            tool_calls=[{"tool": "read", "parameters": {"path": "test.txt"}}]
        )

        assert result.success is True
        assert result.metadata["successful"] == 1
        assert "Hello" in result.metadata["results"][0]["result"].content

    @pytest.mark.asyncio
    async def test_batch_tool_disallowed(self):
        """Test batch tool blocks disallowed tools."""
        from nanocode.tools.builtin import BatchTool
        from nanocode.tools import ToolRegistry, ToolExecutor

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        tool = BatchTool(tool_executor=executor)

        result = await tool.execute(tool_calls=[{"tool": "batch", "parameters": {}}])

        assert result.metadata["failed"] == 1
        assert "not allowed" in result.metadata["results"][0]["error"]

    @pytest.mark.asyncio
    async def test_batch_tool_max_limit(self):
        """Test batch tool enforces max limit."""
        from nanocode.tools.builtin import BatchTool
        from nanocode.tools import ToolRegistry, ToolExecutor

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        tool = BatchTool(tool_executor=executor)

        calls = [{"tool": "nonexistent", "parameters": {}} for _ in range(26)]
        result = await tool.execute(tool_calls=calls)

        assert result.success is False
        assert "Maximum" in result.error

    @pytest.mark.asyncio
    async def test_multiedit_tool(self, temp_dir):
        """Test multiedit tool."""
        from nanocode.tools.builtin import MultiEditTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World\nGoodbye World")

        tool = MultiEditTool()
        result = await tool.execute(
            filePath=test_file,
            edits=[
                {"oldString": "World", "newString": "Universe"},
            ],
        )

        assert result.success is True
        content = Path(test_file).read_text()
        assert "Universe" in content

    @pytest.mark.asyncio
    async def test_apply_patch_tool(self, temp_dir):
        """Test apply_patch tool."""
        from nanocode.tools.builtin import ApplyPatchTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World")

        patch = f"""--- a/{test_file}
+++ b/{test_file}
@@ -1 +1 @@
-Hello World
+Hello Universe
"""

        tool = ApplyPatchTool()
        result = await tool.execute(patchText=patch)

        assert result.success is True
        content = Path(test_file).read_text()
        assert "Universe" in content

    @pytest.mark.asyncio
    async def test_question_tool(self):
        """Test question tool."""
        from nanocode.tools.builtin import QuestionTool

        tool = QuestionTool()
        result = await tool.execute(questions=[{"question": "What is your name?"}])

        assert result.success is True
        assert "What is your name?" in result.content

    @pytest.mark.asyncio
    async def test_question_tool_multiple(self):
        """Test question tool with multiple questions."""
        from nanocode.tools.builtin import QuestionTool

        tool = QuestionTool()
        result = await tool.execute(
            questions=[
                {"question": "What is your name?"},
                {"question": "How old are you?"},
            ]
        )

        assert result.success is True
        assert "What is your name?" in result.content
        assert "How old are you?" in result.content
