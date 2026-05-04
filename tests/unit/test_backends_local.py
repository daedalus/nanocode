"""Tests for FileSystemBackend ABC and LocalFSBackend."""

import pytest
import tempfile
import os
from pathlib import Path

from nanocode.tools.backends.base import FileSystemBackend
from nanocode.tools.backends.local import LocalFSBackend


class TestLocalFSBackend:
    """Tests for LocalFSBackend."""

    @pytest.fixture
    def backend(self):
        """Create a temporary directory backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield LocalFSBackend(tmpdir)

    @pytest.fixture
    def backend_with_files(self):
        """Create a backend with some test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            Path(tmpdir, "test.txt").write_text("Hello, World!")
            Path(tmpdir, "subdir").mkdir()
            Path(tmpdir, "subdir", "nested.txt").write_text("Nested content")
            yield LocalFSBackend(tmpdir)

    @pytest.mark.asyncio
    async def test_read_existing_file(self, backend_with_files):
        """Test reading an existing file."""
        result = await backend_with_files.read("test.txt")
        assert result["success"] is True
        assert result["content"] == "Hello, World!"
        assert result["metadata"]["path"].endswith("test.txt")

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, backend):
        """Test reading a file that doesn't exist."""
        result = await backend.read("nonexistent.txt")
        assert result["success"] is True  # Returns empty for new files
        assert result["content"] == ""
        assert result["metadata"]["new_file"] is True

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, backend_with_files):
        """Test reading with offset and limit."""
        # Create a multi-line file
        await backend_with_files.write("multiline.txt", "Line1\nLine2\nLine3\nLine4\nLine5")
        
        result = await backend_with_files.read("multiline.txt", offset=2, limit=2)
        assert result["success"] is True
        assert result["content"] == "Line2\nLine3"
        assert result["metadata"]["lines"] == 2

    @pytest.mark.asyncio
    async def test_write_new_file(self, backend):
        """Test writing a new file."""
        result = await backend.write("new_file.txt", "New content here")
        assert result["success"] is True
        assert "new_file.txt" in result["content"]
        
        # Verify file was actually written
        assert Path(backend.root_dir, "new_file.txt").read_text() == "New content here"

    @pytest.mark.asyncio
    async def test_write_existing_file(self, backend_with_files):
        """Test overwriting an existing file."""
        result = await backend_with_files.write("test.txt", "Overwritten content")
        assert result["success"] is True
        
        # Verify content was updated
        assert Path(backend_with_files.root_dir, "test.txt").read_text() == "Overwritten content"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, backend):
        """Test that write creates parent directories."""
        result = await backend.write("a/b/c/test.txt", "Deep file")
        assert result["success"] is True
        assert Path(backend.root_dir, "a", "b", "c", "test.txt").exists()

    @pytest.mark.asyncio
    async def test_edit_existing_text(self, backend_with_files):
        """Test editing existing text in a file."""
        result = await backend_with_files.edit("test.txt", "World", "Universe")
        assert result["success"] is True
        assert "Successfully edited" in result["content"]
        
        # Verify the edit
        content = Path(backend_with_files.root_dir, "test.txt").read_text()
        assert content == "Hello, Universe!"

    @pytest.mark.asyncio
    async def test_edit_not_found(self, backend_with_files):
        """Test editing text that doesn't exist."""
        result = await backend_with_files.edit("test.txt", "NotExist", "Something")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_edit_replace_all(self, backend):
        """Test replace_all functionality."""
        await backend.write("repeat.txt", "foo bar foo bar foo")
        result = await backend.edit("repeat.txt", "foo", "baz", replace_all=True)
        assert result["success"] is True
        
        content = Path(backend.root_dir, "repeat.txt").read_text()
        assert content == "baz bar baz bar baz"

    @pytest.mark.asyncio
    async def test_edit_multiple_occurrences_without_replace_all(self, backend):
        """Test edit fails when multiple matches exist and replace_all=False."""
        await backend.write("repeat.txt", "foo bar foo")
        result = await backend.edit("repeat.txt", "foo", "baz", replace_all=False)
        assert result["success"] is False
        assert "matches" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_exists(self, backend_with_files):
        """Test exists method."""
        assert await backend_with_files.exists("test.txt") is True
        assert await backend_with_files.exists("nonexistent.txt") is False

    @pytest.mark.asyncio
    async def test_list_dir(self, backend_with_files):
        """Test listing directory contents."""
        result = await backend_with_files.list_dir("")
        assert len(result) >= 2  # test.txt and subdir
        names = [r["name"] for r in result]
        assert "test.txt" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_list_dir_subdir(self, backend_with_files):
        """Test listing subdirectory contents."""
        result = await backend_with_files.list_dir("subdir")
        assert len(result) == 1
        assert result[0]["name"] == "nested.txt"
        assert result[0]["is_dir"] is False

    @pytest.mark.asyncio
    async def test_delete_file(self, backend_with_files):
        """Test deleting a file."""
        assert await backend_with_files.exists("test.txt") is True
        result = await backend_with_files.delete("test.txt")
        assert result["success"] is True
        assert await backend_with_files.exists("test.txt") is False

    @pytest.mark.asyncio
    async def test_resolve_absolute_path(self, backend):
        """Test that absolute paths are handled correctly."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Absolute content")
            abs_path = f.name
        
        try:
            # LocalFSBackend should handle absolute paths
            result = await backend.read(abs_path)
            assert result["success"] is True
            assert result["content"] == "Absolute content"
        finally:
            os.unlink(abs_path)
