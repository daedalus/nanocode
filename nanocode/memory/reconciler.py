"""Memory reconciler - keeps FTS5 index in sync with memory files."""

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from .indexer import MemoryIndexer


class MemoryReconciler:
    """Reconciles memory files with FTS5 index."""

    def __init__(self, session: AsyncSession, memory_dir: str | None = None):
        self.session = session
        self.indexer = MemoryIndexer(session)
        self.memory_dir = memory_dir or self._get_default_memory_dir()

    def _get_default_memory_dir(self) -> str:
        """Get default memory directory."""
        xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return str(Path(xdg_data) / "nanocode" / "memory")

    async def reconcile(
        self,
        force: bool = False,
        scopes: list[str] | None = None,
    ) -> dict:
        """Reconcile memory files with index.

        Args:
            force: Force full re-indexing
            scopes: Specific scopes to reconcile (default: all)

        Returns:
            Statistics about reconciliation
        """
        await self.indexer.initialize()

        stats = {
            "indexed": 0,
            "pruned": 0,
            "errors": [],
        }

        # Get current indexed files
        indexed_files = await self._get_indexed_files()

        # Scan memory directories
        memory_files = await self._scan_memory_files(scopes)

        # Index new or updated files
        for file_path, metadata in memory_files.items():
            if force or file_path not in indexed_files:
                try:
                    chunks = await self.indexer.index_file(
                        file_path,
                        scope=metadata["scope"],
                        scope_id=metadata.get("scope_id"),
                        memory_type=metadata["type"],
                    )
                    stats["indexed"] += chunks
                except Exception as e:
                    stats["errors"].append({"file": file_path, "error": str(e)})

        # Prune deleted files
        for file_path in indexed_files:
            if file_path not in memory_files:
                try:
                    await self.indexer.remove_file(file_path)
                    stats["pruned"] += 1
                except Exception as e:
                    stats["errors"].append({"file": file_path, "error": str(e)})

        return stats

    async def _get_indexed_files(self) -> set[str]:
        """Get set of currently indexed file paths."""
        from sqlalchemy import text

        result = await self.session.execute(
            text("SELECT DISTINCT path FROM memory_fts")
        )
        return {row[0] for row in result.fetchall()}

    async def _scan_memory_files(
        self, scopes: list[str] | None = None
    ) -> dict[str, dict]:
        """Scan memory directories for files to index.

        Returns:
            Dict mapping file paths to metadata
        """
        files = {}
        memory_path = Path(self.memory_dir)

        if not memory_path.exists():
            return files

        # Scan each scope
        self._scan_global(files, memory_path, scopes)
        self._scan_projects(files, memory_path, scopes)
        self._scan_sessions(files, memory_path, scopes)

        return files

    def _scan_global(
        self, files: dict, memory_path: Path, scopes: list[str] | None
    ) -> None:
        """Scan global memory directory."""
        if scopes is not None and "global" not in scopes:
            return
        global_dir = memory_path / "global"
        if not global_dir.exists():
            return
        for md_file in global_dir.glob("*.md"):
            files[str(md_file)] = {
                "scope": "global",
                "type": self._detect_type(md_file.name),
            }

    def _scan_projects(
        self, files: dict, memory_path: Path, scopes: list[str] | None
    ) -> None:
        """Scan project memory directories."""
        if scopes is not None and "project" not in scopes:
            return
        projects_dir = memory_path / "projects"
        if not projects_dir.exists():
            return
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir():
                project_id = project_dir.name
                for md_file in project_dir.glob("*.md"):
                    files[str(md_file)] = {
                        "scope": "project",
                        "scope_id": project_id,
                        "type": self._detect_type(md_file.name),
                    }

    def _scan_sessions(
        self, files: dict, memory_path: Path, scopes: list[str] | None
    ) -> None:
        """Scan session memory directories."""
        if scopes is not None and "session" not in scopes:
            return
        sessions_dir = memory_path / "sessions"
        if not sessions_dir.exists():
            return
        for session_dir in sessions_dir.iterdir():
            if session_dir.is_dir():
                session_id = session_dir.name
                self._scan_session_files(files, session_dir, session_id)

    def _scan_session_files(
        self, files: dict, session_dir: Path, session_id: str
    ) -> None:
        """Scan files within a session directory."""
        for md_file in session_dir.glob("*.md"):
            files[str(md_file)] = {
                "scope": "session",
                "scope_id": session_id,
                "type": self._detect_type(md_file.name),
            }
        # Also scan task progress files
        tasks_dir = session_dir / "tasks"
        if tasks_dir.exists():
            for task_dir in tasks_dir.iterdir():
                if task_dir.is_dir():
                    task_id = task_dir.name
                    progress_file = task_dir / "progress.md"
                    if progress_file.exists():
                        files[str(progress_file)] = {
                            "scope": "session",
                            "scope_id": f"{session_id}:{task_id}",
                            "type": "task",
                        }

    def _detect_type(self, filename: str) -> str:
        """Detect memory type from filename."""
        filename_lower = filename.lower()
        if "checkpoint" in filename_lower:
            return "checkpoint"
        elif "notes" in filename_lower:
            return "notes"
        elif "task" in filename_lower or "progress" in filename_lower:
            return "task"
        elif "memory" in filename_lower:
            return "memory"
        else:
            return "memory"

    async def reconcile_on_search(self) -> dict:
        """Reconcile before search (lazy update).

        Returns:
            Statistics about reconciliation
        """
        return await self.reconcile(force=False)

    async def get_memory_files(self) -> dict[str, str]:
        """Get all memory files with their paths.

        Returns:
            Dict mapping file names to paths
        """
        files = {}
        memory_path = Path(self.memory_dir)

        if not memory_path.exists():
            return files

        for md_file in memory_path.rglob("*.md"):
            files[md_file.name] = str(md_file)

        return files
