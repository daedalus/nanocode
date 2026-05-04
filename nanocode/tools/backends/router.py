"""FileSystemRouter - routes tool calls to the correct backend based on path prefix.

Implements the "one interface, two backends" pattern from the blog post:
- /workspace/*  -> LocalFSBackend (sandbox or CWD)
- /skills/*      -> DatabaseBackend (skills stored in SQLite)
- /memory/*      -> DatabaseBackend (memories stored in SQLite)

The agent sees one read/write/edit interface. The routing is invisible.
"""

from typing import Optional


class FileSystemRouter:
    """Routes filesystem operations to the correct backend based on path prefixes.

    This is the core of the virtualized filesystem described in the blog post.
    The agent calls read(path) and the router figures out where to get the data.
    """

    def __init__(
        self,
        workspace_backend=None,
        skills_backend=None,
        memory_backend=None,
    ):
        """Initialize with backends for each namespace.

        Args:
            workspace_backend: LocalFSBackend for /workspace/* paths
            skills_backend: DatabaseBackend for /skills/* paths
            memory_backend: DatabaseBackend for /memory/* paths
        """
        self.workspace_backend = workspace_backend
        self.skills_backend = skills_backend
        self.memory_backend = memory_backend

    def _route(self, path: str) -> tuple:
        """Determine which backend and relative path to use.

        Returns:
            (backend, relative_path) or (None, path) if no match
        """
        normalized = path.replace("\\", "/")

        if normalized.startswith("/skills/") or normalized.startswith("skills/"):
            if self.skills_backend:
                rel = normalized.lstrip("/")
                return self.skills_backend, rel
            return None, path

        if normalized.startswith("/memory/") or normalized.startswith("memory/"):
            if self.memory_backend:
                rel = normalized.lstrip("/")
                return self.memory_backend, rel
            return None, path

        if normalized.startswith("/workspace/"):
            if self.workspace_backend:
                rel = normalized[len("/workspace/"):]
                return self.workspace_backend, rel
            return None, path

        if self.workspace_backend:
            return self.workspace_backend, normalized.lstrip("/")

        return None, path

    async def read(self, path: str, offset: int = None, limit: int = None) -> dict:
        backend, rel_path = self._route(path)
        if backend is None:
            return {"success": False, "content": None, "error": f"No backend for path: {path}"}
        return await backend.read(rel_path, offset=offset, limit=limit)

    async def write(self, path: str, content: str) -> dict:
        backend, rel_path = self._route(path)
        if backend is None:
            return {"success": False, "content": None, "error": f"No backend for path: {path}"}
        return await backend.write(rel_path, content)

    async def edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
        backend, rel_path = self._route(path)
        if backend is None:
            return {"success": False, "content": None, "error": f"No backend for path: {path}"}
        return await backend.edit(rel_path, old_string, new_string, replace_all=replace_all)

    async def exists(self, path: str) -> bool:
        backend, rel_path = self._route(path)
        if backend is None:
            return False
        return await backend.exists(rel_path)

    async def list_dir(self, path: str = "") -> list[dict]:
        backend, rel_path = self._route(path)
        if backend is None:
            return []
        return await backend.list_dir(rel_path)

    async def delete(self, path: str) -> dict:
        backend, rel_path = self._route(path)
        if backend is None:
            return {"success": False, "content": None, "error": f"No backend for path: {path}"}
        return await backend.delete(rel_path)
