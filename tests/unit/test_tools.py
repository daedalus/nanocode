"""Tests for tool system."""

import os
import tempfile
from pathlib import Path

import pytest

from nanocode.tools import (
    FuncTool,
    SyncFuncTool,
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
)


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
        from nanocode.tools import ToolExecutor, ToolRegistry
        from nanocode.tools.builtin import BatchTool

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        tool = BatchTool(tool_executor=executor)

        result = await tool.execute(tool_calls=[])

        assert result.success is True
        assert result.metadata["total"] == 0

    @pytest.mark.asyncio
    async def test_batch_tool_with_calls(self, temp_dir):
        """Test batch tool with actual tool calls."""
        from nanocode.tools import ToolExecutor, ToolRegistry
        from nanocode.tools.builtin import BatchTool, ReadFileTool

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
        from nanocode.tools import ToolExecutor, ToolRegistry
        from nanocode.tools.builtin import BatchTool

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        tool = BatchTool(tool_executor=executor)

        result = await tool.execute(tool_calls=[{"tool": "batch", "parameters": {}}])

        assert result.metadata["failed"] == 1
        assert "not allowed" in result.metadata["results"][0]["error"]

    @pytest.mark.asyncio
    async def test_batch_tool_max_limit(self):
        """Test batch tool enforces max limit."""
        from nanocode.tools import ToolExecutor, ToolRegistry
        from nanocode.tools.builtin import BatchTool

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


class TestSedTool:
    """Test sed (stream editor) tool."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_sed_single_replacement(self, temp_dir):
        """Test sed replaces first occurrence by default."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World\nHello World\nHello World")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt", search="World", replace="Universe")

        assert result.success is True
        assert result.metadata["count"] == 1
        content = Path(test_file).read_text()
        assert content.count("Universe") == 1
        assert content.count("World") == 2

    @pytest.mark.asyncio
    async def test_sed_global_replacement(self, temp_dir):
        """Test sed with global flag replaces all occurrences."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World\nHello World\nHello World")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(
            path="test.txt", search="World", replace="Universe", global_flag=True
        )

        assert result.success is True
        assert result.metadata["count"] == 3
        content = Path(test_file).read_text()
        assert content.count("Universe") == 3
        assert "World" not in content

    @pytest.mark.asyncio
    async def test_sed_file_not_found(self, temp_dir):
        """Test sed with nonexistent file."""
        from nanocode.tools.builtin import SedTool

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="nonexistent.txt", search="foo", replace="bar")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sed_pattern_not_found(self, temp_dir):
        """Test sed when pattern is not found."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(
            path="test.txt", search="NotFound", replace="Replaced"
        )

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sed_creates_backup_on_dry_run(self, temp_dir):
        """Test sed does not create backup by default."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt", search="World", replace="Universe")

        assert result.success is True
        assert not Path(test_file + ".bak").exists()

    @pytest.mark.asyncio
    async def test_sed_path_traversal(self, temp_dir):
        """Test sed blocks path traversal attempts."""
        from nanocode.tools.builtin import SedTool

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(
            path="../etc/passwd", search="root", replace="hacked"
        )

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_sed_absolute_path_outside_root(self, temp_dir):
        """Test sed blocks absolute paths outside root."""
        from nanocode.tools.builtin import SedTool

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(
            path="/etc/hostname", search="test", replace="hacked"
        )

        assert result.success is False

    @pytest.mark.asyncio
    async def test_sed_empty_file(self, temp_dir):
        """Test sed on empty file."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "empty.txt")
        Path(test_file).write_text("")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="empty.txt", search="test", replace="replaced")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_sed_special_characters(self, temp_dir):
        """Test sed with special characters in search/replace."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Price: 100 200")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt", search="100", replace="150")

        assert result.success is True
        content = Path(test_file).read_text()
        assert "150" in content

    @pytest.mark.asyncio
    async def test_sed_newline_in_search(self, temp_dir):
        """Test sed with newline in search string."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        original = "Line 1\nLine 2\nLine 3"
        Path(test_file).write_text(original.replace("\n", " "))

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt", search=" ", replace="\n")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_sed_unicode_content(self, temp_dir):
        """Test sed with unicode content."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("こんにちは世界\nHello 世界")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt", search="世界", replace="地球")

        assert result.success is True
        content = Path(test_file).read_text()
        assert "地球" in content

    @pytest.mark.asyncio
    async def test_sed_binary_file_like_content(self, temp_dir):
        """Test sed with binary-like content."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.bin")
        Path(test_file).write_bytes(b"Hello\x00World\nData\xff\xfe")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="test.bin", search="Hello", replace="Hi")

        assert result.success is True
        content = Path(test_file).read_bytes()
        assert b"Hi\x00World" in content

    @pytest.mark.asyncio
    async def test_sed_symlink_to_absolute(self, temp_dir):
        """Test sed follows symlinks to absolute paths."""
        from nanocode.tools.builtin import SedTool

        os.symlink("/etc", os.path.join(temp_dir, "etc_link"))

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(
            path="etc_link/hostname", search="test", replace="hacked"
        )

        assert result.success is False

    @pytest.mark.asyncio
    async def test_sed_very_large_file(self, temp_dir):
        """Test sed handles large files."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "large.txt")
        large_content = "x" * 1_000_000
        Path(test_file).write_text(large_content)

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="large.txt", search="xxx", replace="y")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_sed_same_search_replace(self, temp_dir):
        """Test sed when search and replace are identical returns no change."""
        from nanocode.tools.builtin import SedTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World")

        tool = SedTool(root_dir=temp_dir)
        result = await tool.execute(path="test.txt", search="Hello", replace="Hello")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()
        content = Path(test_file).read_text()
        assert content == "Hello World"


class TestDiffTool:
    """Test diff tool."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_diff_two_files(self, temp_dir):
        """Test diff between two files."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "file1.txt")
        file2 = os.path.join(temp_dir, "file2.txt")

        Path(file1).write_text("Hello World\nLine 2\nLine 3")
        Path(file2).write_text("Hello Universe\nLine 2\nLine 3")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="file1.txt", path2="file2.txt")

        assert result.success is True
        assert "-Hello Universe" in result.content
        assert "+Hello World" in result.content

    @pytest.mark.asyncio
    async def test_diff_with_original_content(self, temp_dir):
        """Test diff with original content."""
        from nanocode.tools.builtin import DiffTool

        test_file = os.path.join(temp_dir, "test.txt")
        original = "Hello World\nLine 2"
        Path(test_file).write_text("Hello Universe\nLine 2")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="test.txt", original_content=original)

        assert result.success is True
        assert "-Hello World" in result.content
        assert "+Hello Universe" in result.content

    @pytest.mark.asyncio
    async def test_diff_no_differences(self, temp_dir):
        """Test diff when files are identical."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "file1.txt")
        file2 = os.path.join(temp_dir, "file2.txt")

        content = "Hello World\nLine 2\nLine 3"
        Path(file1).write_text(content)
        Path(file2).write_text(content)

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="file1.txt", path2="file2.txt")

        assert result.success is True
        assert result.content == "No differences"

    @pytest.mark.asyncio
    async def test_diff_file1_not_found(self, temp_dir):
        """Test diff with nonexistent first file."""
        from nanocode.tools.builtin import DiffTool

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="nonexistent.txt", path2="other.txt")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_diff_file2_not_found(self, temp_dir):
        """Test diff with nonexistent second file."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "file1.txt")
        Path(file1).write_text("Hello World")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="file1.txt", path2="nonexistent.txt")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_diff_no_path2_or_original(self, temp_dir):
        """Test diff requires either path2 or original_content."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "file1.txt")
        Path(file1).write_text("Hello World")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="file1.txt")

        assert result.success is False
        assert result.error is not None
        assert "must be provided" in result.error.lower()

    @pytest.mark.asyncio
    async def test_diff_added_lines(self, temp_dir):
        """Test diff shows added lines correctly."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "file1.txt")
        file2 = os.path.join(temp_dir, "file2.txt")

        Path(file1).write_text("Line 1\nLine 2")
        Path(file2).write_text("Line 1\nLine 2\nLine 3\nLine 4")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="file2.txt", path2="file1.txt")

        assert result.success is True
        assert "+Line 3" in result.content
        assert "+Line 4" in result.content

    @pytest.mark.asyncio
    async def test_diff_path_traversal(self, temp_dir):
        """Test diff blocks path traversal attempts."""
        from nanocode.tools.builtin import DiffTool

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="../../etc/passwd", path2="test.txt")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_diff_absolute_path_outside_root(self, temp_dir):
        """Test diff blocks absolute paths outside root."""
        from nanocode.tools.builtin import DiffTool

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="/etc/hostname", path2="test.txt")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_diff_empty_file(self, temp_dir):
        """Test diff with empty files."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "empty1.txt")
        file2 = os.path.join(temp_dir, "empty2.txt")

        Path(file1).write_text("")
        Path(file2).write_text("")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="empty1.txt", path2="empty2.txt")

        assert result.success is True
        assert result.content == "No differences"

    @pytest.mark.asyncio
    async def test_diff_empty_vs_nonempty(self, temp_dir):
        """Test diff between empty and non-empty file."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "empty.txt")
        file2 = os.path.join(temp_dir, "content.txt")

        Path(file1).write_text("")
        Path(file2).write_text("Hello World")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="content.txt", path2="empty.txt")

        assert result.success is True
        assert "+Hello World" in result.content

    @pytest.mark.asyncio
    async def test_diff_binary_files(self, temp_dir):
        """Test diff with binary files."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "bin1.bin")
        file2 = os.path.join(temp_dir, "bin2.bin")

        Path(file1).write_bytes(b"Hello\x00World")
        Path(file2).write_bytes(b"Hello\x00Universe")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="bin1.bin", path2="bin2.bin")

        assert result.success is True
        assert "-Hello" in result.content or "+Hello" in result.content

    @pytest.mark.asyncio
    async def test_diff_unicode_content(self, temp_dir):
        """Test diff with unicode content."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "unicode1.txt")
        file2 = os.path.join(temp_dir, "unicode2.txt")

        Path(file1).write_text("こんにちは世界")
        Path(file2).write_text("hello世界")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="unicode1.txt", path2="unicode2.txt")

        assert result.success is True
        assert "こんにちは" in result.content or "hello" in result.content

    @pytest.mark.asyncio
    async def test_diff_special_characters(self, temp_dir):
        """Test diff with special characters."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "special1.txt")
        file2 = os.path.join(temp_dir, "special2.txt")

        Path(file1).write_text("$100 + $200 = $300")
        Path(file2).write_text("€100 + €200 = €300")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="special1.txt", path2="special2.txt")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_diff_very_large_files(self, temp_dir):
        """Test diff with very large files."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "large1.txt")
        file2 = os.path.join(temp_dir, "large2.txt")

        content1 = "x" * 500_000 + "\nmodified line\n" + "y" * 500_000
        content2 = "x" * 500_000 + "\nchanged line\n" + "y" * 500_000

        Path(file1).write_text(content1)
        Path(file2).write_text(content2)

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="large1.txt", path2="large2.txt")

        assert result.success is True
        assert "-changed line" in result.content
        assert "+modified line" in result.content

    @pytest.mark.asyncio
    async def test_diff_with_null_bytes(self, temp_dir):
        """Test diff with null bytes in content."""
        from nanocode.tools.builtin import DiffTool

        file1 = os.path.join(temp_dir, "null1.txt")
        file2 = os.path.join(temp_dir, "null2.txt")

        Path(file1).write_bytes(b"Hello\x00World")
        Path(file2).write_bytes(b"Hello\x00Universe")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="null1.txt", path2="null2.txt")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_diff_symlink_following(self, temp_dir):
        """Test diff prevents following symlinks outside root."""
        from nanocode.tools.builtin import DiffTool

        os.symlink("/etc", os.path.join(temp_dir, "etc_link"))

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="etc_link/hostname", path2="test.txt")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_diff_nonexistent_both_files(self, temp_dir):
        """Test diff when both files don't exist."""
        from nanocode.tools.builtin import DiffTool

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="nonexistent1.txt", path2="nonexistent2.txt")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_diff_original_content_empty(self, temp_dir):
        """Test diff with empty original_content."""
        from nanocode.tools.builtin import DiffTool

        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("Hello World")

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="test.txt", original_content="")

        assert result.success is True
        assert "+Hello World" in result.content

    @pytest.mark.asyncio
    async def test_diff_directory_not_file(self, temp_dir):
        """Test diff when path points to a directory."""
        from nanocode.tools.builtin import DiffTool

        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        tool = DiffTool(root_dir=temp_dir)
        result = await tool.execute(path1="subdir", path2="test.txt")

        assert result.success is False


class TestBashSessionTool:
    """Test BashSessionTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_create_session(self, temp_dir):
        """Test creating a bash session."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        result = await tool.execute(action="create", workdir=temp_dir)

        assert result.success is True
        assert "Created bash session" in result.content
        assert result.metadata["cwd"] == temp_dir

    @pytest.mark.asyncio
    async def test_create_with_custom_id(self, temp_dir):
        """Test creating a session with custom ID."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        result = await tool.execute(
            action="create", session_id="myid", workdir=temp_dir
        )

        assert result.success is True
        assert "myid" in result.content

    @pytest.mark.asyncio
    async def test_run_command(self, temp_dir):
        """Test running a command in a session."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        await tool.execute(action="create", session_id="test1", workdir=temp_dir)
        result = await tool.execute(
            action="run", session_id="test1", command="echo hello"
        )

        assert result.success is True
        assert "hello" in result.content

    @pytest.mark.asyncio
    async def test_run_nonexistent_session(self, temp_dir):
        """Test running command in nonexistent session."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        result = await tool.execute(
            action="run", session_id="nonexistent", command="echo hello"
        )

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_get_session(self, temp_dir):
        """Test getting session state."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        await tool.execute(action="create", session_id="gettest", workdir=temp_dir)
        result = await tool.execute(action="get", session_id="gettest")

        assert result.success is True
        assert result.content["cwd"] == temp_dir

    @pytest.mark.asyncio
    async def test_set_env(self, temp_dir):
        """Test setting environment variable."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        await tool.execute(action="create", session_id="envtest", workdir=temp_dir)
        result = await tool.execute(
            action="set_env", session_id="envtest", key="FOO", value="bar"
        )

        assert result.success is True
        assert "FOO=bar" in result.content

        get_result = await tool.execute(action="get", session_id="envtest")
        assert get_result.content["env"]["FOO"] == "bar"

    @pytest.mark.asyncio
    async def test_list_sessions(self, temp_dir):
        """Test listing sessions."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        await tool.execute(action="create", session_id="session1", workdir=temp_dir)
        await tool.execute(action="create", session_id="session2", workdir=temp_dir)

        result = await tool.execute(action="list")

        assert result.success is True
        assert result.metadata["count"] == 2

    @pytest.mark.asyncio
    async def test_delete_session(self, temp_dir):
        """Test deleting a session."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        await tool.execute(action="create", session_id="deletetest", workdir=temp_dir)
        result = await tool.execute(action="delete", session_id="deletetest")

        assert result.success is True
        assert "Deleted" in result.content

        get_result = await tool.execute(action="get", session_id="deletetest")
        assert get_result.success is False

    @pytest.mark.asyncio
    async def test_cd_updates_cwd(self, temp_dir):
        """Test that cd command updates working directory."""
        from nanocode.tools.builtin import BashSessionTool, _bash_session_manager

        _bash_session_manager._sessions.clear()

        tool = BashSessionTool()
        await tool.execute(action="create", session_id="cdtest", workdir=temp_dir)

        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        result = await tool.execute(
            action="run", session_id="cdtest", command=f"cd {subdir}"
        )

        assert result.success is True


class TestBuiltinSearchTools:
    """Tests for builtin search tools."""

    def test_codesearch_instantiation(self):
        """Test CodeSearchTool can be instantiated."""
        import nanocode.tools.builtin.codesearch as cs

        tool = cs.CodeSearchTool(api_key="test-key")
        assert tool.name == "codesearch"
        assert tool.api_key == "test-key"

    def test_codesearch_no_api_key_attr(self):
        """Test CodeSearchTool api_key defaults to env."""
        import nanocode.tools.builtin.codesearch as cs

        orig_key = os.environ.get("EXA_API_KEY")
        os.environ.pop("EXA_API_KEY", None)
        try:
            tool = cs.CodeSearchTool()
            assert tool.api_key is None
        finally:
            if orig_key:
                os.environ["EXA_API_KEY"] = orig_key

    def test_exasearch_instantiation(self):
        """Test ExaSearchTool can be instantiated."""
        from nanocode.tools.builtin.exa_search import ExaSearchTool

        tool = ExaSearchTool(api_key="test-key")
        assert tool.name == "exa"
        assert tool.api_key == "test-key"

    def test_freeexasearch_basic(self):
        """Test FreeExaSearchTool can be instantiated."""
        from nanocode.tools.builtin.free_search import FreeExaSearchTool

        tool = FreeExaSearchTool()
        assert tool.name == "free_exa"
        assert tool.base_url == "https://mcp.exa.ai/mcp"

    def test_brave_search_instantiation(self):
        """Test BraveSearchTool can be instantiated."""
        from nanocode.tools.builtin.free_search import BraveSearchTool

        tool = BraveSearchTool(api_key="test-key")
        assert tool.name == "brave_search"
        assert tool.api_key == "test-key"

    @pytest.mark.asyncio
    async def test_skill_tool_missing_name(self):
        """Test SkillTool fails without skill name."""
        from unittest.mock import MagicMock

        from nanocode.tools.builtin.skill import SkillTool

        mock_manager = MagicMock()
        tool = SkillTool(mock_manager)

        result = await tool.execute(name="", input="test")
        assert result.success is False
        assert "Skill name is required" in result.error

    def test_skill_tool_instantiation(self):
        """Test SkillTool can be instantiated."""
        from unittest.mock import MagicMock

        from nanocode.tools.builtin.skill import SkillTool

        mock_manager = MagicMock()
        tool = SkillTool(mock_manager)
        assert tool.name == "skill"
        assert tool.skills_manager is mock_manager


class TestSkillToolExecution:
    """Tests for SkillTool execution paths."""

    @pytest.mark.asyncio
    async def test_skill_tool_get_skill_error(self):
        """Test SkillTool fails when get_skill raises."""
        from unittest.mock import MagicMock

        from nanocode.tools.builtin.skill import SkillTool

        mock_manager = MagicMock()
        mock_manager.get_skill.side_effect = FileNotFoundError("Skill not found")
        tool = SkillTool(mock_manager)

        result = await tool.execute(name="skill", input="test")
        assert result.success is False


class TestToolDiscovery:
    """Tests for tool auto-discovery."""

    @pytest.fixture
    def temp_tool_dir(self):
        """Create a temporary directory with test tools."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        with open(os.path.join(tool_dir, "hello_tool.py"), "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class HelloTool(Tool):
    name = "hello"
    description = "Say hello"

    async def execute(self, name: str = "") -> ToolResult:
        return ToolResult(success=True, content=f"Hello, {name}!")
"""
            )

        yield tmpdir

        shutil.rmtree(tmpdir)

    def test_default_tool_dirs(self):
        """Test DEFAULT_TOOL_DIRS contains expected directories."""
        dirs = ToolRegistry.DEFAULT_TOOL_DIRS

        assert ".nanocode/tools" in dirs
        assert ".opencode/tools" in dirs
        assert ".claude/tools" in dirs
        assert ".codex/tools" in dirs
        assert "tools" in dirs

    def test_tool_file_extensions(self):
        """Test TOOL_FILE_EXTENSIONS contains expected extensions."""
        exts = ToolRegistry.TOOL_FILE_EXTENSIONS

        assert ".py" in exts

    def test_discover_tools(self, temp_tool_dir):
        """Test discovering tools in directory."""
        registry = ToolRegistry()
        discovered = registry.discover_tools(temp_tool_dir)

        assert len(discovered) == 1
        assert discovered[0].name == "hello"

    def test_discover_tools_no_tools(self):
        """Test discovering tools with no tools directory."""
        tmpdir = tempfile.mkdtemp()

        registry = ToolRegistry()
        discovered = registry.discover_tools(tmpdir)

        assert len(discovered) == 0

        os.rmdir(tmpdir)

    def test_load_discovered_tools(self, temp_tool_dir):
        """Test loading discovered tools."""
        registry = ToolRegistry()
        count = registry.load_discovered_tools(temp_tool_dir)

        assert count == 1
        assert registry.has_tool("hello")

    def test_discover_tools_multiple_directories(self):
        """Test discovering tools from multiple directories."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        dirs = [
            (".nanocode/tool", "nanocode_tool"),
            (".opencode/tools", "opencode_tool"),
            ("tools", "project_tool"),
        ]

        for tool_subdir, tool_name in dirs:
            tool_dir = os.path.join(tmpdir, tool_subdir)
            os.makedirs(tool_dir)
            with open(os.path.join(tool_dir, f"{tool_name}.py"), "w") as f:
                f.write(
                    f"""
from nanocode.tools import Tool, ToolResult


class {tool_name.title().replace("_", "")}Tool(Tool):
    name = "{tool_name}"
    description = "A {tool_name} tool"

    async def execute(self, input: str = "") -> ToolResult:
        return ToolResult(success=True, content="{tool_name}")
"""
                )

        try:
            registry = ToolRegistry()
            discovered = registry.discover_tools(tmpdir)

            tool_names = {t.name for t in discovered}
            assert "nanocode_tool" in tool_names
            assert "opencode_tool" in tool_names
            assert "project_tool" in tool_names
        finally:
            shutil.rmtree(tmpdir)

    def test_discover_tools_skips_dunder(self):
        """Test discovering tools skips __init__.py and dunder files."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        with open(os.path.join(tool_dir, "__init__.py"), "w") as f:
            f.write("# init")

        with open(os.path.join(tool_dir, "_private.py"), "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class PrivateTool(Tool):
    name = "private"

    async def execute(self, input: str = "") -> ToolResult:
        return ToolResult(success=True, content="private")
"""
            )

        try:
            registry = ToolRegistry()
            discovered = registry.discover_tools(tmpdir)

            assert len(discovered) == 0
        finally:
            shutil.rmtree(tmpdir)


class TestToolDiscoveryWithInitPattern:
    """Tests for tool auto-discovery with __init__ pattern."""

    @pytest.fixture
    def temp_tool_dir_init(self):
        """Create a temporary directory with init-style tools."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        with open(os.path.join(tool_dir, "greet_tool.py"), "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class GreetTool(Tool):
    def __init__(self):
        super().__init__(
            name="greet",
            description="Greet someone"
        )

    async def execute(self, name: str = "world") -> ToolResult:
        return ToolResult(success=True, content=f"Hello, {name}!")
"""
            )

        yield tmpdir

        shutil.rmtree(tmpdir)

    def test_discover_tools_with_init_pattern(self, temp_tool_dir_init):
        """Test discovering tools with __init__ pattern."""
        registry = ToolRegistry()
        discovered = registry.discover_tools(temp_tool_dir_init)

        assert len(discovered) == 1
        assert discovered[0].name == "greet"

    def test_load_discovered_tools_with_init_pattern(self, temp_tool_dir_init):
        """Test loading discovered tools with __init__ pattern."""
        registry = ToolRegistry()
        count = registry.load_discovered_tools(temp_tool_dir_init)

        assert count == 1
        assert registry.has_tool("greet")

    @pytest.mark.asyncio
    async def test_execute_discovered_tool(self, temp_tool_dir_init):
        """Test executing a discovered tool."""
        registry = ToolRegistry()
        registry.load_discovered_tools(temp_tool_dir_init)
        executor = ToolExecutor(registry)

        result = await executor.execute("greet", {"name": "Alice"})

        assert result.success is True
        assert "Alice" in result.content

    def test_discover_tools_invalid_file(self):
        """Test discovering tools with invalid file."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        with open(os.path.join(tool_dir, "bad_tool.py"), "w") as f:
            f.write("# invalid python syntax error $$$")

        try:
            registry = ToolRegistry()
            discovered = registry.discover_tools(tmpdir)

            assert len(discovered) == 0
        finally:
            shutil.rmtree(tmpdir)

    def test_discover_tools_no_tool_class(self):
        """Test discovering tools skips files without Tool subclass."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        with open(os.path.join(tool_dir, "notool.py"), "w") as f:
            f.write(
                """
def hello():
    return "hello"
"""
            )

        try:
            registry = ToolRegistry()
            discovered = registry.discover_tools(tmpdir)

            assert len(discovered) == 0
        finally:
            shutil.rmtree(tmpdir)

    def test_discover_tools_mixed_valid_invalid(self):
        """Test discovering tools with mixed valid/invalid files."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        with open(os.path.join(tool_dir, "valid.py"), "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class ValidTool(Tool):
    name = "valid"
    description = "A valid tool"

    async def execute(self, input: str = "") -> ToolResult:
        return ToolResult(success=True, content="valid")
"""
            )

        with open(os.path.join(tool_dir, "invalid.py"), "w") as f:
            f.write("# broken")

        with open(os.path.join(tool_dir, "helper.py"), "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult

def helper_func():
    pass

class HelperTool(Tool):
    name = "helper"
    description = "Helper tool"

    async def execute(self, input: str = "") -> ToolResult:
        return ToolResult(success=True, content="helper")
"""
            )

        try:
            registry = ToolRegistry()
            discovered = registry.discover_tools(tmpdir)

            tool_names = {t.name for t in discovered}
            assert "valid" in tool_names
            assert "helper" in tool_names
            assert len(discovered) == 2
        finally:
            shutil.rmtree(tmpdir)

    def test_discover_nested_directories(self):
        """Test discovering tools in nested directories."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        nested_dir = os.path.join(tmpdir, ".nanocode", "tools", "subdir")
        os.makedirs(nested_dir)

        with open(os.path.join(nested_dir, "nested_tool.py"), "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class NestedTool(Tool):
    name = "nested"
    description = "Nested tool"

    async def execute(self, input: str = "") -> ToolResult:
        return ToolResult(success=True, content="nested")
"""
            )

        try:
            registry = ToolRegistry()
            discovered = registry.discover_tools(tmpdir)

            assert len(discovered) == 1
            assert discovered[0].name == "nested"
        finally:
            shutil.rmtree(tmpdir)

    def test_discover_ignores_pycache(self):
        """Test discovering tools ignores __pycache__."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        pycache_dir = os.path.join(tool_dir, "__pycache__")
        os.makedirs(pycache_dir)

        tool_file = os.path.join(tool_dir, "real_tool.py")
        with open(tool_file, "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class RealTool(Tool):
    name = "real"
    description = "Real tool"

    async def execute(self, input: str = "") -> ToolResult:
        return ToolResult(success=True, content="real")
"""
            )

        try:
            registry = ToolRegistry()
            discovered = registry.discover_tools(tmpdir)

            assert len(discovered) == 1
            assert discovered[0].name == "real"
        finally:
            shutil.rmtree(tmpdir)


class TestToolRegistryIntegration:
    """Integration tests for tool registry."""

    @pytest.mark.asyncio
    async def test_register_and_execute_custom_tool(self):
        """Test registering and executing a custom tool."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, "tools")
        os.makedirs(tool_dir)

        tool_file = os.path.join(tool_dir, "echo.py")
        with open(tool_file, "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class EchoTool(Tool):
    name = "echo"
    description = "Echo back the input"

    async def execute(self, text: str = "") -> ToolResult:
        return ToolResult(success=True, content=text)
"""
            )

        try:
            registry = ToolRegistry()
            registry.load_discovered_tools(tmpdir)

            assert registry.has_tool("echo")

            executor = ToolExecutor(registry)
            result = await executor.execute("echo", {"text": "hello world"})

            assert result.success is True
            assert result.content == "hello world"
        finally:
            shutil.rmtree(tmpdir)

    def test_tool_schema_generation(self):
        """Test tool schema is correctly generated."""
        import shutil

        tmpdir = tempfile.mkdtemp()

        tool_dir = os.path.join(tmpdir, ".nanocode", "tools")
        os.makedirs(tool_dir)

        tool_file = os.path.join(tool_dir, "schema_tool.py")
        with open(tool_file, "w") as f:
            f.write(
                """
from nanocode.tools import Tool, ToolResult


class SchemaTool(Tool):
    name = "schema"
    description = "A tool with schema"

    def __init__(self):
        super().__init__(
            name="schema",
            description="A tool with schema",
            parameters={
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input text"}
                },
                "required": ["input"]
            }
        )

    async def execute(self, input: str = "") -> ToolResult:
        return ToolResult(success=True, content=input)
"""
            )

        try:
            registry = ToolRegistry()
            registry.load_discovered_tools(tmpdir)

            schemas = registry.get_schemas()
            schema = next(s for s in schemas if s["function"]["name"] == "schema")

            assert schema["function"]["name"] == "schema"
            assert "input" in schema["function"]["parameters"]["properties"]
        finally:
            shutil.rmtree(tmpdir)
