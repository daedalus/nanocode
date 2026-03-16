"""Unit tests for file watcher module."""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from agent_smith.file_watcher import (
    FileWatcher,
    FileWatcherEvent,
    FileEventHandler,
    FileWatcherManager,
    create_file_watcher,
    get_watcher_manager,
)


class TestFileWatcherEvent:
    """Tests for FileWatcherEvent dataclass."""

    def test_event_creation(self):
        """Test creating a file watcher event."""
        event = FileWatcherEvent(file="/path/to/file.py", event_type="change")
        assert event.file == "/path/to/file.py"
        assert event.event_type == "change"

    def test_event_types(self):
        """Test all event types."""
        for event_type in ["add", "change", "unlink"]:
            event = FileWatcherEvent(file="/test.py", event_type=event_type)
            assert event.event_type == event_type


class TestFileEventHandler:
    """Tests for FileEventHandler."""

    def test_ignore_patterns(self):
        """Test that ignore patterns work."""
        events = []

        def callback(event):
            events.append(event)

        handler = FileEventHandler(callback, ignore_patterns=["*.pyc", "__pycache__"])

        handler.on_created(type("MockEvent", (), {"src_path": "/test.py", "is_directory": False})())
        assert len(events) == 1

        events.clear()
        handler.on_created(
            type("MockEvent", (), {"src_path": "/test.pyc", "is_directory": False})()
        )
        assert len(events) == 0

    def test_directory_events_ignored(self):
        """Test that directory events are ignored."""
        events = []

        def callback(event):
            events.append(event)

        handler = FileEventHandler(callback)
        handler.on_created(type("MockEvent", (), {"src_path": "/dir", "is_directory": True})())
        assert len(events) == 0


class TestFileWatcher:
    """Tests for FileWatcher."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_watcher_initialization(self, temp_dir):
        """Test that watcher initializes correctly."""
        watcher = FileWatcher(root_dir=temp_dir, enabled=False)
        assert watcher.root_dir == Path(temp_dir)
        assert not watcher.is_running

    def test_watcher_default_ignore_patterns(self):
        """Test default ignore patterns."""
        watcher = FileWatcher(enabled=False)
        assert ".git" in watcher.ignore_patterns
        assert "__pycache__" in watcher.ignore_patterns
        assert "*.pyc" in watcher.ignore_patterns

    def test_watcher_custom_ignore_patterns(self):
        """Test custom ignore patterns."""
        watcher = FileWatcher(enabled=False, ignore_patterns=["custom/*"])
        assert "custom/*" in watcher.ignore_patterns

    @pytest.mark.asyncio
    async def test_watcher_start_stop(self, temp_dir):
        """Test starting and stopping the watcher."""
        watcher = FileWatcher(root_dir=temp_dir, enabled=True)
        watcher.start()
        assert watcher.is_running
        watcher.stop()
        assert not watcher.is_running

    @pytest.mark.asyncio
    async def test_watcher_disabled(self, temp_dir):
        """Test that disabled watcher doesn't start."""
        watcher = FileWatcher(root_dir=temp_dir, enabled=False)
        watcher.start()
        assert not watcher.is_running

    @pytest.mark.asyncio
    async def test_watcher_callback(self, temp_dir):
        """Test that callbacks are called on file events."""
        events = []
        watcher = FileWatcher(root_dir=temp_dir, enabled=True)
        watcher.add_callback(lambda e: events.append(e))
        watcher.start()

        try:
            test_file = Path(temp_dir) / "test.txt"
            test_file.write_text("hello")

            await asyncio.sleep(0.5)

            assert len(events) > 0
            assert any(e.file.endswith("test.txt") for e in events)
        finally:
            watcher.stop()

    @pytest.mark.asyncio
    async def test_watcher_get_event(self, temp_dir):
        """Test getting events from queue."""
        watcher = FileWatcher(root_dir=temp_dir, enabled=True)
        watcher.start()

        try:
            test_file = Path(temp_dir) / "test.txt"
            test_file.write_text("hello")

            event = await watcher.get_event(timeout=2)
            assert event is not None
            assert event.event_type in ["add", "change"]
        finally:
            watcher.stop()


class TestFileWatcherManager:
    """Tests for FileWatcherManager."""

    def test_manager_create_watcher(self):
        """Test creating watchers via manager."""
        manager = FileWatcherManager()
        watcher = manager.create_watcher("test", enabled=False)
        assert watcher is not None
        assert manager.get_watcher("test") is watcher

    def test_manager_remove_watcher(self):
        """Test removing watchers via manager."""
        manager = FileWatcherManager()
        manager.create_watcher("test", enabled=False)
        manager.remove_watcher("test")
        assert manager.get_watcher("test") is None


class TestCreateFileWatcher:
    """Tests for create_file_watcher convenience function."""

    def test_create_watcher(self):
        """Test creating a watcher with convenience function."""
        watcher = create_file_watcher("test", enabled=False)
        assert watcher is not None
        get_watcher_manager().remove_watcher("test")


class TestFileWatcherIntegration:
    """Integration tests for file watcher."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_file_create_event(self, temp_dir):
        """Test file creation event."""
        events = []
        watcher = FileWatcher(root_dir=temp_dir, enabled=True)
        watcher.add_callback(lambda e: events.append(e))
        watcher.start()

        try:
            test_file = Path(temp_dir) / "new_file.txt"
            test_file.write_text("content")

            await asyncio.sleep(0.5)

            add_events = [e for e in events if e.event_type == "add"]
            assert len(add_events) > 0
        finally:
            watcher.stop()

    @pytest.mark.asyncio
    async def test_file_modify_event(self, temp_dir):
        """Test file modification event."""
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("original")

        events = []
        watcher = FileWatcher(root_dir=temp_dir, enabled=True)
        watcher.add_callback(lambda e: events.append(e))
        watcher.start()

        try:
            time.sleep(0.1)
            test_file.write_text("modified")

            await asyncio.sleep(0.5)

            change_events = [e for e in events if e.event_type == "change"]
            assert len(change_events) > 0
        finally:
            watcher.stop()

    @pytest.mark.asyncio
    async def test_file_delete_event(self, temp_dir):
        """Test file deletion event."""
        test_file = Path(temp_dir) / "delete_me.txt"
        test_file.write_text("content")

        events = []
        watcher = FileWatcher(root_dir=temp_dir, enabled=True)
        watcher.add_callback(lambda e: events.append(e))
        watcher.start()

        try:
            time.sleep(0.1)
            test_file.unlink()

            await asyncio.sleep(0.5)

            unlink_events = [e for e in events if e.event_type == "unlink"]
            assert len(unlink_events) > 0
        finally:
            watcher.stop()
