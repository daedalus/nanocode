"""File watcher for real-time file system monitoring.

This module provides cross-platform file system watching using the watchdog library,
similar to how opencode uses @parcel/watcher. It publishes events when files are
created, modified, or deleted.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

logger = logging.getLogger(__name__)


@dataclass
class FileWatcherEvent:
    """Event emitted when a file changes."""

    file: str
    event_type: str  # "add", "change", "unlink"


class FileEventHandler(FileSystemEventHandler):
    """Handler for file system events."""

    def __init__(
        self, callback: Callable[[FileWatcherEvent], None], ignore_patterns: list[str] = None
    ):
        self.callback = callback
        self.ignore_patterns = ignore_patterns or []

    def should_ignore(self, path: str) -> bool:
        """Check if the path should be ignored."""
        path_obj = Path(path)
        for pattern in self.ignore_patterns:
            if pattern in str(path_obj):
                return True
            if path_obj.match(pattern):
                return True
        return False

    def on_created(self, event: FileSystemEvent):
        """Handle file creation."""
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return
        self.callback(FileWatcherEvent(file=event.src_path, event_type="add"))
        logger.debug(f"File created: {event.src_path}")

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification."""
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return
        self.callback(FileWatcherEvent(file=event.src_path, event_type="change"))
        logger.debug(f"File modified: {event.src_path}")

    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion."""
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return
        self.callback(FileWatcherEvent(file=event.src_path, event_type="unlink"))
        logger.debug(f"File deleted: {event.src_path}")

    def on_moved(self, event: FileSystemEvent):
        """Handle file move."""
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return
        self.callback(FileWatcherEvent(file=event.dest_path, event_type="add"))
        self.callback(FileWatcherEvent(file=event.src_path, event_type="unlink"))
        logger.debug(f"File moved: {event.src_path} -> {event.dest_path}")


class FileWatcher:
    """Cross-platform file system watcher.

    Watches directories for file changes and emits events that can be
    used to invalidate caches or trigger other actions.
    """

    DEFAULT_IGNORE_PATTERNS = [
        ".git",
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        "node_modules",
        ".DS_Store",
        "*.swp",
        "*.tmp",
        ".venv",
        "venv",
    ]

    def __init__(
        self,
        root_dir: Optional[str] = None,
        ignore_patterns: Optional[list[str]] = None,
        enabled: bool = True,
    ):
        """Initialize the file watcher.

        Args:
            root_dir: Directory to watch. Defaults to current working directory.
            ignore_patterns: List of patterns to ignore. Defaults to DEFAULT_IGNORE_PATTERNS.
            enabled: Whether the watcher is active. Can be toggled later.
        """
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.ignore_patterns = ignore_patterns or self.DEFAULT_IGNORE_PATTERNS
        self.enabled = enabled

        self._observer: Optional[Observer] = None
        self._handler: Optional[FileEventHandler] = None
        self._event_queue: asyncio.Queue[FileWatcherEvent] = asyncio.Queue()
        self._callbacks: list[Callable[[FileWatcherEvent], None]] = []

    def start(self):
        """Start watching the file system."""
        if not self.enabled:
            logger.info("File watcher is disabled")
            return

        if self._observer is not None:
            logger.warning("File watcher already running")
            return

        self._handler = FileEventHandler(self._on_event, self.ignore_patterns)

        self._observer = Observer()
        self._observer.schedule(
            self._handler,
            str(self.root_dir),
            recursive=True,
        )
        self._observer.start()
        logger.info(f"File watcher started for: {self.root_dir}")

    def stop(self):
        """Stop watching the file system."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("File watcher stopped")

    def _on_event(self, event: FileWatcherEvent):
        """Internal callback for file events."""
        self._event_queue.put_nowait(event)
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in file watcher callback: {e}")

    def add_callback(self, callback: Callable[[FileWatcherEvent], None]):
        """Add a callback to be called when files change."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[FileWatcherEvent], None]):
        """Remove a callback."""
        self._callbacks.remove(callback)

    async def get_event(self, timeout: float = None) -> Optional[FileWatcherEvent]:
        """Get the next file event.

        Args:
            timeout: Maximum time to wait for an event in seconds. None = wait forever.

        Returns:
            The next file event, or None if timeout occurred.
        """
        try:
            if timeout is not None:
                return await asyncio.wait_for(self._event_queue.get(), timeout)
            return await self._event_queue.get()
        except asyncio.TimeoutError:
            return None

    @property
    def is_running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._observer is not None and self._observer.is_alive()


class FileWatcherManager:
    """Manages multiple file watchers for different directories."""

    def __init__(self):
        self._watchers: dict[str, FileWatcher] = {}

    def create_watcher(
        self,
        name: str,
        root_dir: Optional[str] = None,
        ignore_patterns: Optional[list[str]] = None,
        enabled: bool = True,
    ) -> FileWatcher:
        """Create and register a new file watcher.

        Args:
            name: Unique name for this watcher.
            root_dir: Directory to watch.
            ignore_patterns: Patterns to ignore.
            enabled: Whether the watcher is active.

        Returns:
            The created FileWatcher instance.
        """
        watcher = FileWatcher(
            root_dir=root_dir,
            ignore_patterns=ignore_patterns,
            enabled=enabled,
        )
        self._watchers[name] = watcher
        return watcher

    def get_watcher(self, name: str) -> Optional[FileWatcher]:
        """Get a watcher by name."""
        return self._watchers.get(name)

    def remove_watcher(self, name: str):
        """Remove and stop a watcher."""
        watcher = self._watchers.pop(name, None)
        if watcher:
            watcher.stop()

    def start_all(self):
        """Start all registered watchers."""
        for watcher in self._watchers.values():
            watcher.start()

    def stop_all(self):
        """Stop all registered watchers."""
        for watcher in self._watchers.values():
            watcher.stop()


_watcher_manager: Optional[FileWatcherManager] = None


def get_watcher_manager() -> FileWatcherManager:
    """Get the global watcher manager instance."""
    global _watcher_manager
    if _watcher_manager is None:
        _watcher_manager = FileWatcherManager()
    return _watcher_manager


def create_file_watcher(
    name: str = "default",
    root_dir: Optional[str] = None,
    ignore_patterns: Optional[list[str]] = None,
    enabled: bool = True,
    auto_start: bool = False,
) -> FileWatcher:
    """Convenience function to create a file watcher.

    Args:
        name: Unique name for this watcher.
        root_dir: Directory to watch.
        ignore_patterns: Patterns to ignore.
        enabled: Whether the watcher is active.
        auto_start: Whether to automatically start the watcher.

    Returns:
        The created FileWatcher instance.
    """
    manager = get_watcher_manager()
    watcher = manager.create_watcher(
        name=name,
        root_dir=root_dir,
        ignore_patterns=ignore_patterns,
        enabled=enabled,
    )
    if auto_start:
        watcher.start()
    return watcher
