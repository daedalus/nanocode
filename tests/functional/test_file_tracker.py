"""Tests for file tracker."""

import pytest
import tempfile
import os
import time
from pathlib import Path

from agent_smith.tools.file_tracker import FileTracker


class TestFileTracker:
    """Test file tracker functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def tracker(self, temp_dir):
        """Create a file tracker."""
        return FileTracker(cache_dir=os.path.join(temp_dir, ".agent/cache"))

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a test file."""
        path = os.path.join(temp_dir, "test.txt")
        Path(path).write_text("initial content")
        return path

    def test_set_and_get(self, tracker, test_file):
        """Test setting and getting cached file."""
        content = Path(test_file).read_text()
        tracker.set(test_file, content)
        
        cached = tracker.get(test_file)
        assert cached is not None
        assert cached.content == content

    def test_is_modified_true_for_new_file(self, tracker, temp_dir):
        """Test is_modified returns True for new files."""
        path = os.path.join(temp_dir, "new.txt")
        Path(path).write_text("content")
        
        assert tracker.is_modified(path) is True

    def test_is_modified_false_for_unchanged(self, tracker, test_file):
        """Test is_modified returns False for unchanged files."""
        content = Path(test_file).read_text()
        tracker.set(test_file, content)
        
        assert tracker.is_modified(test_file) is False

    def test_is_modified_true_after_change(self, tracker, test_file):
        """Test is_modified returns True after file modification."""
        content = Path(test_file).read_text()
        tracker.set(test_file, content)
        
        time.sleep(0.1)
        Path(test_file).write_text("modified content")
        
        assert tracker.is_modified(test_file) is True

    def test_get_or_read_returns_cached(self, tracker, test_file):
        """Test get_or_read returns cached content."""
        content, refreshed = tracker.get_or_read(test_file)
        
        assert refreshed is True
        assert content == "initial content"
        
        content, refreshed = tracker.get_or_read(test_file)
        
        assert refreshed is False
        assert content == "initial content"

    def test_get_or_read_force_refresh(self, tracker, test_file):
        """Test force_refresh parameter."""
        tracker.get_or_read(test_file)
        
        Path(test_file).write_text("new content")
        
        content, refreshed = tracker.get_or_read(test_file, force_refresh=True)
        assert refreshed is True
        assert content == "new content"

    def test_invalidate(self, tracker, test_file):
        """Test cache invalidation."""
        tracker.get_or_read(test_file)
        assert tracker.get(test_file) is not None
        
        tracker.invalidate(test_file)
        assert tracker.get(test_file) is None

    def test_invalidate_pattern(self, tracker, temp_dir):
        """Test pattern-based invalidation."""
        Path(os.path.join(temp_dir, "file1.txt")).write_text("1")
        Path(os.path.join(temp_dir, "file2.txt")).write_text("2")
        Path(os.path.join(temp_dir, "file3.py")).write_text("3")
        
        tracker.get_or_read(os.path.join(temp_dir, "file1.txt"))
        tracker.get_or_read(os.path.join(temp_dir, "file2.txt"))
        tracker.get_or_read(os.path.join(temp_dir, "file3.py"))
        
        tracker.invalidate_pattern("*.txt")
        
        assert tracker.get(os.path.join(temp_dir, "file1.txt")) is None
        assert tracker.get(os.path.join(temp_dir, "file2.txt")) is None
        assert tracker.get(os.path.join(temp_dir, "file3.py")) is not None

    def test_get_stats(self, tracker, temp_dir):
        """Test statistics retrieval."""
        path1 = os.path.join(temp_dir, "file1.txt")
        path2 = os.path.join(temp_dir, "file2.txt")
        
        Path(path1).write_text("short")
        Path(path2).write_text("much longer content here")
        
        tracker.get_or_read(path1)
        tracker.get_or_read(path2)
        tracker.get_or_read(path1)
        
        stats = tracker.get_stats()
        
        assert stats["cached_files"] == 2
        assert stats["total_content_size"] > 0

    def test_clear(self, tracker, test_file):
        """Test clearing cache."""
        tracker.get_or_read(test_file)
        assert len(tracker._cache) > 0
        
        tracker.clear()
        assert len(tracker._cache) == 0
