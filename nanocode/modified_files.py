"""Track modified files for display in sidebar."""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("nanocode.modified_files")


@dataclass
class FileModification:
    """Represents a file modification."""

    path: str
    relative_path: str
    additions: int = 0
    deletions: int = 0
    is_new: bool = False
    is_deleted: bool = False


class ModifiedFilesTracker:
    """Track files modified during the session using git diff."""

    def __init__(self, cwd: str | None = None):
        if cwd is None:
            cwd = str(Path.cwd())
        self.cwd = Path(cwd)
        self._files: list[FileModification] = []

    def get_modified_files(self) -> list[FileModification]:
        """Get list of modified files."""
        return self._files.copy()

    def _determine_from_commit(self, from_commit: str | None) -> str | None:
        """Determine the from_commit for git diff."""
        if from_commit is not None:
            return from_commit
        result = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=self.cwd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.debug("Git diff skipped: no commits yet")
            return None
        commit_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
        if commit_count == 0:
            logger.debug("Git diff skipped: no commits")
            return None
        return "HEAD" if commit_count == 1 else "HEAD~1"

    def _parse_numstat_line(self, line: str) -> tuple[str, int, int, str] | None:
        """Parse a single --numstat line. Returns (file_path, adds, dels, raw_path) or None."""
        parts = line.split("\t")
        if len(parts) < 3:
            return None
        adds_str, dels_str, file_path = parts[0], parts[1], parts[2]
        adds = int(adds_str) if adds_str != "-" else 0
        dels = int(dels_str) if dels_str != "-" else 0
        return file_path, adds, dels, file_path

    def _diff_numstat(self, from_commit: str, extra_args: list[str] = None) -> list[tuple[str, int, int]]:
        """Run git diff --numstat and return list of (file_path, adds, dels)."""
        cmd = ["git", "diff", "--numstat", *(extra_args or []), from_commit, "--", "."]
        result = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        parsed = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            p = self._parse_numstat_line(line)
            if p:
                parsed.append((p[0], p[1], p[2]))
        return parsed

    def _diff_deleted_files(self, from_commit: str) -> list[str]:
        """Run git diff --name-only --diff-filter=D."""
        cmd = ["git", "diff", "--name-only", "--diff-filter=D", from_commit, "--", "."]
        result = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.strip().split("\n") if line]

    def _add_file_entry(self, file_path: str, adds: int, dels: int, is_deleted: bool = False):
        """Add or merge a file entry."""
        relative_path = self._get_relative_path(file_path)
        if not relative_path:
            return
        existing = next((f for f in self._files if f.relative_path == relative_path), None)
        if existing:
            existing.additions += adds
            existing.deletions += dels
        else:
            self._files.append(FileModification(
                path=str(self.cwd / file_path),
                relative_path=relative_path,
                additions=adds,
                deletions=dels,
                is_new=False,
                is_deleted=is_deleted,
            ))

    def refresh_from_git(self, from_commit: str | None = None) -> None:
        """Refresh modified files from git diff."""
        try:
            from_commit = self._determine_from_commit(from_commit)
            if from_commit is None:
                return

            self._files = []
            for file_path, adds, dels in self._diff_numstat(from_commit):
                self._add_file_entry(file_path, adds, dels)

            for file_path, adds, dels in self._diff_numstat(from_commit, extra_args=["--cached"]):
                self._add_file_entry(file_path, adds, dels)

            for file_path in self._diff_deleted_files(from_commit):
                self._add_file_entry(file_path, 0, 0, is_deleted=True)

        except subprocess.TimeoutExpired:
            logger.warning("Git diff timed out")
        except Exception as e:
            logger.debug(f"Failed to refresh git diff: {e}")

    def _get_relative_path(self, file_path: str) -> str | None:
        """Get relative path from cwd."""
        try:
            abs_path = (self.cwd / file_path).resolve()
            rel_path = abs_path.relative_to(self.cwd)
            return str(rel_path)
        except ValueError:
            return file_path

    def get_stats(self) -> dict:
        """Get statistics about modified files."""
        return {
            "total": len(self._files),
            "additions": sum(f.additions for f in self._files),
            "deletions": sum(f.deletions for f in self._files),
            "new": sum(1 for f in self._files if f.is_new),
            "deleted": sum(1 for f in self._files if f.is_deleted),
            "modified": sum(
                1 for f in self._files if not f.is_new and not f.is_deleted
            ),
        }

    def clear(self) -> None:
        """Clear tracked files."""
        self._files = []


_global_tracker: ModifiedFilesTracker | None = None


def get_modified_files_tracker(cwd: str | None = None) -> ModifiedFilesTracker:
    """Get the global modified files tracker."""
    global _global_tracker
    if _global_tracker is None or cwd is not None:
        _global_tracker = ModifiedFilesTracker(cwd=cwd)
    return _global_tracker
