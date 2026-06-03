"""Tests for EditTool - exact text replacement tool."""

import os
import tempfile
from pathlib import Path

import pytest

from nanocode.tools.builtin import EditTool
from nanocode.tools import ToolResult


class TestEditTool:
    """Test EditTool for exact text replacement."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a test file with content."""
        file_path = os.path.join(temp_dir, "test.txt")
        Path(file_path).write_text("Hello World\nThis is a test\nHello again")
        return file_path

    @pytest.fixture
    def tool(self):
        """Create EditTool instance."""
        return EditTool()

    @pytest.mark.asyncio
    async def test_successful_single_edit(self, tool, test_file):
        """Test successful single replacement."""
        result = await tool.execute(
            filePath=test_file, oldString="Hello World", newString="Hi World"
        )

        assert result.success is True
        assert "Successfully edited" in result.content
        assert result.metadata["replacements"] == 1

        content = Path(test_file).read_text()
        assert "Hi World" in content
        assert "Hello World" not in content

    @pytest.mark.asyncio
    async def test_successful_replace_all(self, tool, temp_dir):
        """Test replaceAll replaces all occurrences."""
        test_file = os.path.join(temp_dir, "multi.txt")
        Path(test_file).write_text("Hello Hello Hello")

        result = await tool.execute(
            filePath=test_file,
            oldString="Hello",
            newString="Hi",
            replaceAll=True
        )

        assert result.success is True
        assert result.metadata["replacements"] == 3

        content = Path(test_file).read_text()
        assert content == "Hi Hi Hi"

    @pytest.mark.asyncio
    async def test_multiple_matches_requires_replace_all(self, tool, temp_dir):
        """Test edit fails when multiple matches exist and replaceAll is False."""
        test_file = os.path.join(temp_dir, "multi.txt")
        Path(test_file).write_text("Hello Hello Hello")

        result = await tool.execute(
            filePath=test_file,
            oldString="Hello",
            newString="Hi",
            replaceAll=False
        )

        assert result.success is False
        assert "Found 3 matches" in result.error
        assert "replaceAll=True" in result.error

    @pytest.mark.asyncio
    async def test_old_string_not_found(self, tool, test_file):
        """Test edit fails when oldString not found."""
        result = await tool.execute(
            filePath=test_file, oldString="NotFound", newString="Replacement"
        )

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool, temp_dir):
        """Test edit fails when file doesn't exist."""
        nonexistent = os.path.join(temp_dir, "nonexistent.txt")

        result = await tool.execute(
            filePath=nonexistent, oldString="test", newString="replacement"
        )

        assert result.success is False
        assert "File not found" in result.error

    @pytest.mark.asyncio
    async def test_relative_path_rejected(self, tool, temp_dir):
        """Test edit fails with relative path."""
        result = await tool.execute(
            filePath="relative/path.txt", oldString="test", newString="replacement"
        )

        assert result.success is False
        assert "must be an absolute path" in result.error

    @pytest.mark.asyncio
    async def test_missing_file_path(self, tool):
        """Test edit fails with missing filePath."""
        result = await tool.execute(oldString="test", newString="replacement")

        assert result.success is False
        assert "Missing required argument: filePath" in result.error

    @pytest.mark.asyncio
    async def test_missing_old_string(self, tool, test_file):
        """Test edit fails with missing oldString."""
        result = await tool.execute(filePath=test_file, newString="replacement")

        assert result.success is False
        assert "Missing required argument: oldString" in result.error

    @pytest.mark.asyncio
    async def test_missing_new_string(self, tool, test_file):
        """Test edit fails with missing newString."""
        result = await tool.execute(filePath=test_file, oldString="Hello")

        assert result.success is False
        assert "Missing required argument: newString" in result.error

    @pytest.mark.asyncio
    async def test_unicode_content(self, tool, temp_dir):
        """Test edit with unicode content."""
        test_file = os.path.join(temp_dir, "unicode.txt")
        Path(test_file).write_text("こんにちは世界")

        result = await tool.execute(
            filePath=test_file, oldString="世界", newString="地球"
        )

        assert result.success is True

        content = Path(test_file).read_text()
        assert "こんにちは地球" in content

    @pytest.mark.asyncio
    async def test_multiline_replacement(self, tool, temp_dir):
        """Test edit with multiline oldString."""
        test_file = os.path.join(temp_dir, "multiline.txt")
        original = "Line 1\nLine 2\nLine 3"
        Path(test_file).write_text(original)

        result = await tool.execute(
            filePath=test_file,
            oldString="Line 2\nLine 3",
            newString="Replaced 2\nReplaced 3"
        )

        assert result.success is True

        content = Path(test_file).read_text()
        assert "Replaced 2" in content
        assert "Replaced 3" in content

    @pytest.mark.asyncio
    async def test_empty_old_string(self, tool, test_file):
        """Test edit with empty oldString."""
        result = await tool.execute(
            filePath=test_file, oldString="", newString="replacement"
        )

        assert result.success is False
        assert "Missing required argument" in result.error

    @pytest.mark.asyncio
    async def test_non_utf8_file(self, tool, temp_dir):
        """Test edit fails with non-UTF-8 encoded file."""
        test_file = os.path.join(temp_dir, "binary.bin")
        Path(test_file).write_bytes(b"\xff\xfe\x00\x00")

        result = await tool.execute(
            filePath=test_file, oldString="test", newString="replacement"
        )

        assert result.success is False
        assert "encoding" in result.error.lower()

    @pytest.mark.asyncio
    async def test_replace_all_default_false(self, tool, temp_dir):
        """Test that replaceAll defaults to False."""
        test_file = os.path.join(temp_dir, "test.txt")
        Path(test_file).write_text("a a a")

        result = await tool.execute(
            filePath=test_file, oldString="a", newString="b"
        )

        assert result.success is False
        assert "Found 3 matches" in result.error

    @pytest.mark.asyncio
    async def test_metadata_contents(self, tool, test_file):
        """Test result metadata contains expected fields."""
        result = await tool.execute(
            filePath=test_file, oldString="This is a test", newString="This is modified"
        )

        assert result.success is True
        assert "filePath" in result.metadata
        assert "replacements" in result.metadata
        assert result.metadata["replacements"] == 1

    def test_tool_properties(self, tool):
        """Test tool has correct name and description."""
        assert tool.name == "edit"
        assert "4-tier matching" in tool.description or "exact text replacement" in tool.description.lower()

    def test_tool_schema(self, tool):
        """Test tool schema is valid."""
        schema = tool.get_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "edit"
        assert "filePath" in schema["function"]["parameters"]["properties"]
        assert "oldString" in schema["function"]["parameters"]["properties"]
        assert "newString" in schema["function"]["parameters"]["properties"]
        assert "replaceAll" in schema["function"]["parameters"]["properties"]

    def test_required_parameters(self, tool):
        """Test required parameters are correct."""
        schema = tool.get_schema()
        required = schema["function"]["parameters"]["required"]

        assert "filePath" in required
        assert "oldString" in required
        assert "newString" in required
        assert "replaceAll" not in required
