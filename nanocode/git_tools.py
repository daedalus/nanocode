"""Git Introspection Tools - Rich git queries for code exploration.

Based on Aura's git_tools.py:
- git_log_file: Follow renames
- git_branch_list: Local + tracking branches
- git_stash_list: List stashes
- git_stash_show: Show stash contents
"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GitBranch:
    """A git branch."""

    name: str
    is_current: bool = False
    is_remote: bool = False
    tracking: str | None = None
    last_commit: str | None = None
    last_commit_message: str | None = None


@dataclass
class GitStash:
    """A git stash entry."""

    index: int
    branch: str
    description: str
    commit: str
    timestamp: str | None = None


@dataclass
class GitCommit:
    """A git commit."""

    hash: str
    author: str
    date: str
    message: str
    files_changed: list[str] | None = None


@dataclass
class GitLogEntry:
    """A git log entry."""

    hash: str
    short_hash: str
    author: str
    date: str
    subject: str
    files: list[str] | None = None


class GitIntrospection:
    """Rich git introspection tools for code exploration."""

    def __init__(self, workdir: str = "."):
        """Initialize git introspection.

        Args:
            workdir: Working directory (git repository root)
        """
        self.workdir = workdir

    async def _git(self, *args: str) -> dict:
        """Execute a git command.

        Returns:
            Dict with stdout, stderr, returncode
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workdir,
            )
            stdout, stderr = await proc.communicate()
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
            }
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}

    async def log_file(
        self,
        file_path: str,
        max_count: int = 20,
        follow: bool = True,
    ) -> list[GitLogEntry]:
        """Get git log for a specific file, following renames.

        Args:
            file_path: Path to the file
            max_count: Maximum number of entries
            follow: Follow file renames

        Returns:
            List of GitLogEntry objects
        """
        args = [
            "log",
            f"--max-count={max_count}",
            "--format=%H|%h|%an|%ai|%s",
            "--name-only",
        ]
        if follow:
            args.append("--follow")

        args.append("--")
        args.append(file_path)

        result = await self._git(*args)
        if result["returncode"] != 0:
            logger.warning(f"git log failed: {result['stderr']}")
            return []

        entries = []
        current_entry = None

        for line in result["stdout"].split("\n"):
            line = line.strip()
            if not line:
                continue

            # Parse commit line (hash|short_hash|author|date|subject)
            parts = line.split("|", 4)
            if len(parts) == 5:
                if current_entry:
                    entries.append(current_entry)

                current_entry = GitLogEntry(
                    hash=parts[0],
                    short_hash=parts[1],
                    author=parts[2],
                    date=parts[3],
                    subject=parts[4],
                    files=[],
                )
            elif current_entry and line and not line.startswith("commit"):
                # File line
                current_entry.files.append(line)

        if current_entry:
            entries.append(current_entry)

        return entries

    async def branch_list(
        self,
        include_remote: bool = True,
        include_tracking: bool = True,
    ) -> list[GitBranch]:
        """List all branches with tracking info.

        Args:
            include_remote: Include remote branches
            include_tracking: Show tracking info

        Returns:
            List of GitBranch objects
        """
        args = ["branch", "-a"]
        if include_tracking:
            args.append("-vv")

        result = await self._git(*args)
        if result["returncode"] != 0:
            return []

        branches = []
        current_branch = await self._get_current_branch()

        for line in result["stdout"].split("\n"):
            line = line.strip()
            if not line or line.startswith("remotes/HEAD"):
                continue

            # Parse branch line
            is_current = line.startswith("* ")
            if is_current:
                line = line[2:]

            is_remote = line.startswith("remotes/")
            name = line.split()[0] if line else ""

            if not name:
                continue

            # Clean up remote prefix for display
            display_name = name
            if name.startswith("remotes/origin/"):
                display_name = name.replace("remotes/origin/", "")

            # Extract tracking info
            tracking = None
            if include_tracking and "[" in line:
                tracking_start = line.index("[") + 1
                tracking_end = line.index("]")
                tracking = line[tracking_start:tracking_end]

            branches.append(
                GitBranch(
                    name=display_name,
                    is_current=is_current or name == current_branch,
                    is_remote=is_remote,
                    tracking=tracking,
                )
            )

        return branches

    async def _get_current_branch(self) -> str | None:
        """Get the current branch name."""
        result = await self._git("branch", "--show-current")
        if result["returncode"] == 0:
            return result["stdout"].strip()
        return None

    async def stash_list(self) -> list[GitStash]:
        """List all stashes.

        Returns:
            List of GitStash objects
        """
        result = await self._git(
            "stash", "list", "--format=%gd|%gs|%gD|%h|%ci"
        )
        if result["returncode"] != 0:
            return []

        stashes = []
        for line in result["stdout"].split("\n"):
            line = line.strip()
            if not line:
                continue

            parts = line.split("|", 4)
            if len(parts) >= 4:
                index_str = parts[0].replace("stash@{", "").replace("}", "")
                try:
                    index = int(index_str)
                except ValueError:
                    continue

                stashes.append(
                    GitStash(
                        index=index,
                        branch=parts[1] if len(parts) > 1 else "",
                        description=parts[2] if len(parts) > 2 else "",
                        commit=parts[3] if len(parts) > 3 else "",
                        timestamp=parts[4] if len(parts) > 4 else None,
                    )
                )

        return stashes

    async def stash_show(
        self,
        stash_index: int = 0,
        stat: bool = True,
    ) -> dict:
        """Show stash contents.

        Args:
            stash_index: Stash index to show
            stat: Show stat summary

        Returns:
            Dict with stash info and changes
        """
        args = ["stash", "show"]
        if stat:
            args.append("--stat")
        args.append(f"stash@{{{stash_index}}}")

        result = await self._git(*args)
        return {
            "index": stash_index,
            "content": result["stdout"],
            "error": result["stderr"] if result["returncode"] != 0 else None,
        }

    async def blame_file(
        self,
        file_path: str,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> list[dict]:
        """Get git blame for a file.

        Args:
            file_path: Path to the file
            line_start: Start line (1-indexed)
            line_end: End line (1-indexed)

        Returns:
            List of blame entries
        """
        args = ["blame", "--porcelain"]
        if line_start and line_end:
            args.append(f"-L {line_start},{line_end}")
        args.append(file_path)

        result = await self._git(*args)
        if result["returncode"] != 0:
            return []

        entries = []
        current = {}

        for line in result["stdout"].split("\n"):
            line = line.rstrip()

            if not line:
                if current:
                    entries.append(current)
                    current = {}
                continue

            if line.startswith("\t"):
                current["content"] = line[1:]
            elif " " in line:
                key, value = line.split(" ", 1)
                if key in ("author", "author-mail", "author-time", "summary"):
                    current[key] = value.strip('"')

        if current:
            entries.append(current)

        return entries

    async def diff_stat(
        self,
        base: str = "HEAD",
        head: str | None = None,
    ) -> dict:
        """Get diff statistics.

        Args:
            base: Base commit/branch
            head: Head commit/branch (defaults to working tree)

        Returns:
            Dict with diff statistics
        """
        args = ["diff", "--stat"]
        if head:
            args.append(f"{base}...{head}")
        else:
            args.append(base)

        result = await self._git(*args)
        return {
            "content": result["stdout"],
            "error": result["stderr"] if result["returncode"] != 0 else None,
        }

    async def is_dirty(self) -> bool:
        """Check if the working tree is dirty."""
        result = await self._git("status", "--porcelain")
        return bool(result["stdout"].strip())

    async def get_repo_root(self) -> str | None:
        """Get the repository root directory."""
        result = await self._git("rev-parse", "--show-toplevel")
        if result["returncode"] == 0:
            return result["stdout"].strip()
        return None

    async def get_current_commit(self) -> str | None:
        """Get the current commit hash."""
        result = await self._git("rev-parse", "HEAD")
        if result["returncode"] == 0:
            return result["stdout"].strip()
        return None


# Global instance
_git_introspection: GitIntrospection | None = None


def get_git_introspection(workdir: str = ".") -> GitIntrospection:
    """Get or create the global git introspection."""
    global _git_introspection
    if _git_introspection is None:
        _git_introspection = GitIntrospection(workdir)
    return _git_introspection


def reset_git_introspection():
    """Reset the global git introspection."""
    global _git_introspection
    _git_introspection = None
