"""Tests for atomic file operations."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from nanocode.tools.builtin import atomic_read, atomic_write


class TestAtomicWrite:
    """Tests for atomic_write function."""

    def test_basic_write(self, tmp_path):
        """Test basic atomic write."""
        file_path = tmp_path / "test.txt"
        content = "Hello, World!"

        atomic_write(file_path, content)

        assert file_path.read_text() == content

    def test_write_creates_parent_dirs(self, tmp_path):
        """Test that atomic write creates parent directories."""
        file_path = tmp_path / "nested" / "dir" / "test.txt"

        atomic_write(file_path, "content")

        assert file_path.exists()
        assert file_path.read_text() == "content"

    def test_write_overwrites_existing(self, tmp_path):
        """Test overwriting existing file."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("old content")

        atomic_write(file_path, "new content")

        assert file_path.read_text() == "new content"

    def test_write_unicode(self, tmp_path):
        """Test writing unicode content."""
        file_path = tmp_path / "test.txt"
        content = "Hello, 世界! 🌍"

        atomic_write(file_path, content)

        assert file_path.read_text() == content

    def test_write_large_content(self, tmp_path):
        """Test writing large content."""
        file_path = tmp_path / "test.txt"
        content = "x" * 100000

        atomic_write(file_path, content)

        assert file_path.read_text() == content

    def test_concurrent_writes(self, tmp_path):
        """Test concurrent writes don't corrupt file."""
        file_path = tmp_path / "test.txt"
        num_threads = 10
        writes_per_thread = 5

        def write_task(thread_id):
            for i in range(writes_per_thread):
                content = f"Thread {thread_id}, Write {i}"
                atomic_write(file_path, content)
                time.sleep(0.001)
            return thread_id

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(write_task, i) for i in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        content = file_path.read_text()
        assert content.startswith("Thread ")
        assert "\n" not in content


class TestAtomicRead:
    """Tests for atomic_read function."""

    def test_basic_read(self, tmp_path):
        """Test basic atomic read."""
        file_path = tmp_path / "test.txt"
        content = "Hello, World!"
        file_path.write_text(content)

        result = atomic_read(file_path)

        assert result == content

    def test_read_unicode(self, tmp_path):
        """Test reading unicode content."""
        file_path = tmp_path / "test.txt"
        content = "Hello, 世界! 🌍"
        file_path.write_text(content)

        result = atomic_read(file_path)

        assert result == content

    def test_read_large_file(self, tmp_path):
        """Test reading large file."""
        file_path = tmp_path / "test.txt"
        content = "x" * 100000
        file_path.write_text(content)

        result = atomic_read(file_path)

        assert result == content


class TestAtomicReadWrite:
    """Tests for combined atomic read/write operations."""

    def test_write_then_read(self, tmp_path):
        """Test writing then reading."""
        file_path = tmp_path / "test.txt"

        atomic_write(file_path, "test content")
        result = atomic_read(file_path)

        assert result == "test content"

    def test_multiple_write_read_cycles(self, tmp_path):
        """Test multiple write/read cycles."""
        file_path = tmp_path / "test.txt"

        for i in range(10):
            content = f"content {i}"
            atomic_write(file_path, content)
            result = atomic_read(file_path)
            assert result == content
