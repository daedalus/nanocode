"""Snapshot module - git-based file state tracking.

Implements low-level git operations for snapshotting workspace state:
- Uses a separate git repository in `~/.local/share/nanocode/snapshots/<session-id>/`
- `git write-tree` to capture current file state
- `git read-tree` to restore a snapshot
- `git diff` to show changes between snapshots

This is based on the opencode approach of using git as an underlying
content-addressable filesystem for efficient snapshot/restore.
"""

import asyncio
import os
from pathlib import Path


class GitSnapshotManager:
    """Manages workspace snapshots using a separate git repository.

    Uses low-level git operations (write-tree, read-tree) for fast
    snapshot creation and restore without disrupting the main worktree.
    """

    def __init__(self, worktree: str, snapshot_dir: str = None, session_id: str = None):
        """Initialize with workspace and snapshot storage.

        Args:
            worktree: Path to the workspace (worktree to snapshot)
            snapshot_dir: Where to store snapshot git repo (default: ~/.local/share/nanocode/snapshots/)
            session_id: Session ID to namespace snapshots (used to set default repo)
        """
        self.worktree = Path(worktree).resolve()
        self.snapshot_base = Path(
            snapshot_dir or os.path.expanduser("~/.local/share/nanocode/snapshots")
        )
        self._repo_dir: Path | None = None
        if session_id:
            self._repo_dir = self._get_repo_dir(session_id)

    def _get_repo_dir(self, session_id: str) -> Path:
        """Get the snapshot repo directory for a session."""
        return self.snapshot_base / session_id

    async def init_repo(self, session_id: str) -> bool:
        """Initialize (or verify) the snapshot git repository.

        Creates a bare-like repo structure for storing snapshots.
        """
        repo_dir = self._get_repo_dir(session_id)
        self._repo_dir = repo_dir
        repo_dir.mkdir(parents=True, exist_ok=True)

        git_dir = repo_dir / ".git"
        if not git_dir.exists():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    f"--work-tree={self.worktree}",
                    f"--git-dir={git_dir}",
                    "init",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if proc.returncode != 0:
                    return False
            except Exception:
                return False

        # Configure git repo
        await self._git_config("core.bare", "false")
        await self._git_config("core.autocrlf", "false")
        await self._git_config("core.quotepath", "false")
        await self._git_config("core.symlinks", "false")

        return True

    async def _git_config(self, key: str, value: str) -> bool:
        """Set a git config value."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                f"--work-tree={self.worktree}",
                f"--git-dir={self._repo_dir / '.git'}",
                "config",
                key,
                value,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    async def _git(self, *args: str, stdin_text: str = None) -> dict:
        """Execute a git command in the snapshot repo.

        Returns:
            dict with keys: success, stdout, stderr, exit_code
        """
        cmd = [
            "git",
            f"--work-tree={self.worktree}",
            f"--git-dir={self._repo_dir / '.git'}",
        ] + list(args)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin_text else None,
            )

            if stdin_text:
                stdout, stderr = await proc.communicate(
                    input=stdin_text.encode("utf-8")
                )
            else:
                stdout, stderr = await proc.communicate()

            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                "exit_code": proc.returncode or 0,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    async def create_snapshot(self, session_id: str, message: str = "") -> str | None:
        """Create a snapshot of the current workspace.

        Uses `git write-tree` to capture the current file state
        and `git commit-tree` to create a commit object.

        Returns:
            Snapshot hash (SHA) or None on failure.
        """
        if not self._repo_dir:
            await self.init_repo(session_id)

        # Add all files to index
        add_result = await self._git("add", "--all", "--", ".")
        if not add_result["success"]:
            return None

        # Write the current tree to get a tree hash
        write_result = await self._git("write-tree")
        if not write_result["success"]:
            return None

        tree_hash = write_result["stdout"].strip()

        # Create a commit object (commit-tree)
        # We need to get the parent commit if one exists
        parent_result = await self._git("rev-parse", "--verify", "HEAD")
        parent_args = []
        if parent_result["success"] and parent_result["stdout"].strip():
            parent_args = ["-p", parent_result["stdout"].strip()]

        commit_result = await self._git(
            "commit-tree",
            *parent_args,
            "-m", message or "Snapshot",
            tree_hash,
        )

        if not commit_result["success"]:
            return None

        commit_hash = commit_result["stdout"].strip()

        # Update HEAD to point to this snapshot
        await self._git("update-ref", "HEAD", commit_hash)

        return commit_hash

    async def restore_snapshot(self, session_id: str, snapshot_hash: str) -> bool:
        """Restore workspace to a snapshot.

        Uses `git read-tree` to populate the index, then
        `git checkout-index` to update the working tree.
        """
        if not self._repo_dir:
            await self.init_repo(session_id)

        # Read the tree into the index
        read_result = await self._git("read-tree", snapshot_hash)
        if not read_result["success"]:
            return False

        # Checkout the index to the working tree
        checkout_result = await self._git(
            "checkout-index",
            "-a",
            "-f",
            "--prefix",
            f"{self.worktree}/",
        )

        return checkout_result["success"]

    async def diff_snapshots(
        self, session_id: str, from_hash: str, to_hash: str
    ) -> list[dict]:
        """Get file-level diffs between two snapshots.

        Returns:
            List of dicts with keys: file, status (added/deleted/modified), patch
        """
        if not self._repo_dir:
            await self.init_repo(session_id)

        result = await self._git("diff", "--name-status", from_hash, to_hash)

        if not result["success"]:
            return []

        # Parse the diff output
        diffs = []
        for line in result["stdout"].strip().split("\n"):
            if not line.strip():
                continue
            # Format: <status>\t<file>
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                status_map = {
                    "A": "added",
                    "D": "deleted",
                    "M": "modified",
                }
                diffs.append({
                    "file": parts[1],
                    "status": status_map.get(parts[0], parts[0]),
                })

        return diffs

    async def list_snapshots(self, session_id: str) -> list[dict]:
        """List all snapshots for a session.

        Returns:
            List of dicts with keys: hash, message, date
        """
        if not self._repo_dir:
            await self.init_repo(session_id)

        result = await self._git(
            "log",
            "--format=%H|%s|%ai",
            "--all",
        )

        if not result["success"]:
            return []

        snapshots = []
        for line in result["stdout"].strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                snapshots.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "date": parts[2],
                })

        return snapshots

    async def get_file_at_snapshot(
        self, session_id: str, snapshot_hash: str, file_path: str
    ) -> str | None:
        """Get file content at a specific snapshot.

        Uses `git show <hash>:<file>` to retrieve file content.
        """
        if not self._repo_dir:
            await self.init_repo(session_id)

        result = await self._git("show", f"{snapshot_hash}:{file_path}")

        if not result["success"]:
            return None

        return result["stdout"]
