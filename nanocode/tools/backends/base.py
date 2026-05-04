"""Base classes for filesystem backends."""

from abc import ABC, abstractmethod


class FileSystemBackend(ABC):
    """Abstract base class for filesystem backends.

    All backends must implement these methods so that tools
    (read, write, edit, glob, grep) can operate uniformly
    regardless of where the data lives.
    """

    @abstractmethod
    async def read(self, path: str, offset: int = None, limit: int = None) -> dict:
        """Read file content.

        Args:
            path: File path (relative to backend's namespace).
            offset: Line number to start from (1-indexed, optional).
            limit: Number of lines to read (optional).

        Returns:
            dict with keys: content (str), metadata (dict with path, lines, total_lines, bytes, tokens_estimate)
        """

    @abstractmethod
    async def write(self, path: str, content: str) -> dict:
        """Write content to a file atomically.

        Args:
            path: File path (relative to backend's namespace).
            content: Content to write.

        Returns:
            dict with keys: success (bool), content (str), metadata (dict)
        """

    @abstractmethod
    async def edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
        """Edit a file by replacing text.

        Args:
            path: File path (relative to backend's namespace).
            old_string: Text to replace.
            new_string: Replacement text.
            replace_all: Replace all occurrences.

        Returns:
            dict with keys: success (bool), content (str), metadata (dict)
        """

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if a file exists."""

    @abstractmethod
    async def list_dir(self, path: str = "") -> list[dict]:
        """List files in a directory.

        Returns:
            List of dicts with keys: name (str), path (str), is_dir (bool)
        """

    @abstractmethod
    async def delete(self, path: str) -> dict:
        """Delete a file."""
