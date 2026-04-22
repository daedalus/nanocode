"""Tests for stat_file_count_tokens tool."""

import os
import tempfile

import pytest


class TestStatFileCountTokensTool:
    """Test StatFileCountTokensTool."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary test file."""
        tmpdir = tempfile.mkdtemp()
        file_path = os.path.join(tmpdir, "test.txt")

        content = "\n".join([f"line {i}" for i in range(100)])
        with open(file_path, "w") as f:
            f.write(content)

        yield file_path

        os.remove(file_path)
        os.rmdir(tmpdir)

    @pytest.fixture
    def large_file(self):
        """Create a larger test file."""
        tmpdir = tempfile.mkdtemp()
        file_path = os.path.join(tmpdir, "large.txt")

        content = "word " * 1000
        with open(file_path, "w") as f:
            f.write(content * 10)

        yield file_path

        os.remove(file_path)
        os.rmdir(tmpdir)

    @pytest.mark.asyncio
    async def test_count_tokens_full_file(self, temp_file):
        """Test counting tokens for full file."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        result = await tool.execute(path=temp_file)

        assert result.success is True
        assert "Estimated tokens:" in result.content
        assert "Lines:" in result.content

    @pytest.mark.asyncio
    async def test_count_tokens_with_offset(self, temp_file):
        """Test counting tokens with offset."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        result = await tool.execute(path=temp_file, offset=50)

        assert result.success is True
        assert result.metadata["partial"] is True

    @pytest.mark.asyncio
    async def test_count_tokens_with_limit(self, temp_file):
        """Test counting tokens with limit."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        result = await tool.execute(path=temp_file, limit=10)

        assert result.success is True
        assert result.metadata["lines"] == 10

    @pytest.mark.asyncio
    async def test_count_tokens_with_offset_and_limit(self, temp_file):
        """Test counting tokens with offset and limit."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        result = await tool.execute(path=temp_file, offset=10, limit=20)

        assert result.success is True
        assert result.metadata["lines"] == 20

    @pytest.mark.asyncio
    async def test_count_tokens_not_found(self):
        """Test file not found."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        result = await tool.execute(path="nonexistent.txt")

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_count_tokens_returns_bytes(self, temp_file):
        """Test that bytes are returned."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        result = await tool.execute(path=temp_file)

        assert result.success is True
        assert "Bytes:" in result.content

    @pytest.mark.asyncio
    async def test_count_tokens_metadata(self, temp_file):
        """Test metadata contains token info."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        result = await tool.execute(path=temp_file)

        assert result.success is True
        assert "tokens" in result.metadata
        assert "bytes" in result.metadata

    @pytest.mark.asyncio
    async def test_pagination_token_counts(self, temp_file):
        """Test pagination correctly counts partial tokens."""
        from nanocode.tools.builtin import StatFileCountTokensTool

        tool = StatFileCountTokensTool()
        full_result = await tool.execute(path=temp_file)
        partial_result = await tool.execute(path=temp_file, limit=10, offset=1)

        assert partial_result.metadata["tokens"] < full_result.metadata["tokens"]


class TestReadToolPagination:
    """Test ReadFileTool pagination."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary test file."""
        tmpdir = tempfile.mkdtemp()
        file_path = os.path.join(tmpdir, "test.txt")

        content = "\n".join([f"line {i}" for i in range(100)])
        with open(file_path, "w") as f:
            f.write(content)

        yield file_path

        os.remove(file_path)
        os.rmdir(tmpdir)

    @pytest.mark.asyncio
    async def test_read_with_offset(self, temp_file):
        """Test reading with offset."""
        from nanocode.tools.builtin import ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(path=temp_file, offset=50)

        assert result.success is True
        assert "line 49" in result.content

    @pytest.mark.asyncio
    async def test_read_with_limit(self, temp_file):
        """Test reading with limit."""
        from nanocode.tools.builtin import ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(path=temp_file, limit=10)

        lines = result.content.splitlines()
        assert len(lines) == 10
        assert result.metadata["lines"] == 10

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, temp_file):
        """Test reading with offset and limit."""
        from nanocode.tools.builtin import ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(path=temp_file, offset=10, limit=20)

        lines = result.content.splitlines()
        assert len(lines) == 20
        assert result.metadata["lines"] == 20

    @pytest.mark.asyncio
    async def test_read_total_lines_in_metadata(self, temp_file):
        """Test total lines reported in metadata."""
        from nanocode.tools.builtin import ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(path=temp_file, limit=5)

        assert "total_lines" in result.metadata
        assert result.metadata["total_lines"] == 100

    @pytest.mark.asyncio
    async def test_read_pagination_preserves_total(self, temp_file):
        """Test pagination preserves total line count."""
        from nanocode.tools.builtin import ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(path=temp_file, limit=10)

        assert result.metadata["total_lines"] == 100
        assert result.metadata["lines"] == 10