"""Track modified files for display in sidebar."""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

    def __init__(self, cwd: Optional[str] = None):
        if cwd is None:
            cwd = str(Path.cwd())
        self.cwd = Path(cwd)
        self._files: list[FileModification] = []

    def get_modified_files(self) -> list[FileModification]:
        """Get list of modified files."""
        return self._files.copy()

    def refresh_from_git(self, from_commit: Optional[str] = None) -> None:
        """Refresh modified files from git diff.

        Args:
            from_commit: Commit to diff from (default: HEAD~1)
        """
        try:
            if from_commit is None:
                from_commit = "HEAD~1"

            result = subprocess.run(
                ["git", "diff", "--numstat", from_commit, "--", "."],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.debug(f"Git diff failed: {result.stderr}")
                return

            self._files = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    continue

                adds_str, dels_str, file_path = parts[0], parts[1], parts[2]
                adds = int(adds_str) if adds_str != "-" else 0
                dels = int(dels_str) if dels_str != "-" else 0

                relative_path = self._get_relative_path(file_path)
                if relative_path:
                    self._files.append(FileModification(
                        path=str(self.cwd / file_path),
                        relative_path=relative_path,
                        additions=adds,
                        deletions=dels,
                        is_new=False,
                        is_deleted=False,
                    ))

            result = subprocess.run(
                ["git", "diff", "--numstat", "--cached", from_commit, "--", "."],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue

                    adds_str, dels_str, file_path = parts[0], parts[1], parts[2]
                    adds = int(adds_str) if adds_str != "-" else 0
                    dels = int(dels_str) if dels_str != "-" else 0

                    existing = next((f for f in self._files if f.relative_path == file_path), None)
                    if existing:
                        existing.additions += adds
                        existing.deletions += dels
                    else:
                        relative_path = self._get_relative_path(file_path)
                        if relative_path:
                            self._files.append(FileModification(
                                path=str(self.cwd / file_path),
                                relative_path=relative_path,
                                additions=adds,
                                deletions=dels,
                                is_new=False,
                                is_deleted=False,
                            ))

            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=D", from_commit, "--", "."],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    self._files.append(FileModification(
                        path=str(self.cwd / line),
                        relative_path=self._get_relative_path(line) or line,
                        additions=0,
                        deletions=0,
                        is_new=False,
                        is_deleted=True,
                    ))

        except subprocess.TimeoutExpired:
            logger.warning("Git diff timed out")
        except Exception as e:
            logger.debug(f"Failed to refresh git diff: {e}")

    def _get_relative_path(self, file_path: str) -> Optional[str]:
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
            "modified": sum(1 for f in self._files if not f.is_new and not f.is_deleted),
        }

    def clear(self) -> None:
        """Clear tracked files."""
        self._files = []


_global_tracker: Optional[ModifiedFilesTracker] = None


def get_modified_files_tracker(cwd: Optional[str] = None) -> ModifiedFilesTracker:
    """Get the global modified files tracker."""
    global _global_tracker
    if _global_tracker is None or cwd is not None:
        _global_tracker = ModifiedFilesTracker(cwd=cwd)
    return _global_tracker