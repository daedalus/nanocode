"""Snapshot/revert system using Git to capture and rollback changes."""

import os
import subprocess
import json
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Patch:
    """Represents changes between snapshots."""

    hash: str
    files: list[str]


class SnapshotError(Exception):
    """Base exception for snapshot errors."""

    pass


class SnapshotNotFoundError(SnapshotError):
    """Raised when a snapshot is not found."""

    pass


class SnapshotManager:
    """Manages snapshots for capturing and reverting changes using Git.

    Uses a separate git repository to track file states, similar to opencode.
    """

    SNAPSHOT_DIR = ".nanocode/snapshots"
    DEFAULT_PRUNE_AGE_DAYS = 7

    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.snapshot_dir = self.base_dir / self.SNAPSHOT_DIR
        self.enabled = True

    def _git_dir(self) -> Path:
        """Get the git directory for snapshots."""
        return self.snapshot_dir / "git"

    def _git_args(self, cmd: list[str]) -> list[str]:
        """Wrap git command with git-dir and work-tree args."""
        return ["--git-dir", str(self._git_dir()), "--work-tree", str(self.base_dir), *cmd]

    def _run_git(
        self, cmd: list[str], cwd: Path = None, check: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a git command."""
        full_cmd = ["git"] + self._git_args(cmd)
        return subprocess.run(
            full_cmd,
            cwd=cwd or self.base_dir,
            capture_output=True,
            text=True,
            check=check,
        )

    async def is_available(self) -> bool:
        """Check if snapshot is available (git is installed)."""
        try:
            subprocess.run(
                ["git", "--version"],
                capture_output=True,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    async def init(self):
        """Initialize the snapshot repository if needed."""
        if not self.enabled:
            return

        git_dir = self._git_dir()

        if git_dir.exists():
            return

        git_dir.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                ["git", "init"],
                cwd=git_dir,
                capture_output=True,
                check=True,
                env={**os.environ, "GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(self.base_dir)},
            )

            subprocess.run(
                ["git", "--git-dir", str(git_dir), "config", "core.autocrlf", "false"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "--git-dir", str(git_dir), "config", "core.longpaths", "true"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "--git-dir", str(git_dir), "config", "core.symlinks", "true"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "--git-dir", str(git_dir), "config", "core.fsmonitor", "false"],
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass

    async def track(self) -> Optional[str]:
        """Capture current state of files and return snapshot hash.

        Uses git write-tree to capture the current state.
        """
        if not self.enabled:
            return None

        await self.init()

        git_dir = self._git_dir()

        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.base_dir,
                capture_output=True,
                check=True,
                env={**os.environ, "GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(self.base_dir)},
            )

            result = subprocess.run(
                ["git", *self._git_args(["write-tree"])],
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                check=True,
            )

            snapshot_hash = result.stdout.strip()

            self._save_snapshot_timestamp(snapshot_hash)

            return snapshot_hash
        except subprocess.CalledProcessError:
            return None

    def _save_snapshot_timestamp(self, snapshot_hash: str):
        """Save timestamp for a snapshot."""
        timestamps_file = self.snapshot_dir / "timestamps.json"
        timestamps = {}
        if timestamps_file.exists():
            try:
                with open(timestamps_file) as f:
                    timestamps = json.load(f)
            except Exception:
                pass

        timestamps[snapshot_hash] = datetime.now().isoformat()

        try:
            with open(timestamps_file, "w") as f:
                json.dump(timestamps, f)
        except Exception:
            pass

    async def patch(self, snapshot_hash: str) -> Patch:
        """Get the diff/patch between current state and a snapshot.

        Returns a Patch object with the hash and list of changed files.
        """
        if not self.enabled:
            return Patch(hash=snapshot_hash, files=[])

        await self.init()

        git_dir = self._git_dir()

        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.base_dir,
                capture_output=True,
                check=True,
                env={**os.environ, "GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(self.base_dir)},
            )

            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.autocrlf=false",
                    "-c",
                    "core.longpaths=true",
                    "-c",
                    "core.symlinks=true",
                    "-c",
                    "core.quotepath=false",
                    *self._git_args(
                        ["diff", "--no-ext-diff", "--name-only", snapshot_hash, "--", "."]
                    ),
                ],
                cwd=self.base_dir,
                capture_output=True,
                text=True,
            )

            files = []
            if result.returncode == 0 and result.stdout:
                files = [
                    str(self.base_dir / f.strip())
                    for f in result.stdout.strip().split("\n")
                    if f.strip()
                ]

            return Patch(hash=snapshot_hash, files=files)
        except subprocess.CalledProcessError:
            return Patch(hash=snapshot_hash, files=[])

    async def restore(self, snapshot_hash: str) -> bool:
        """Restore files to a previous snapshot state.

        Uses git read-tree to restore the index, then checkout-index to restore files.
        """
        if not self.enabled:
            return False

        git_dir = self._git_dir()

        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.longpaths=true",
                    "-c",
                    "core.symlinks=true",
                    *self._git_args(["read-tree", snapshot_hash]),
                ],
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                check=True,
            )

            subprocess.run(
                [
                    "git",
                    "-c",
                    "core.longpaths=true",
                    "-c",
                    "core.symlinks=true",
                    *self._git_args(["checkout-index", "-a", "-f"]),
                ],
                cwd=self.base_dir,
                capture_output=True,
                check=True,
            )

            return True
        except subprocess.CalledProcessError as e:
            return False

    async def list_snapshots(self) -> list[dict]:
        """List all available snapshots.

        Returns a list of snapshot info with hash and timestamp.
        """
        if not self.enabled:
            return []

        git_dir = self._git_dir()

        if not git_dir.exists():
            return []

        try:
            result = subprocess.run(
                ["git", *self._git_args(["log", "--format=%H %ci", "-n", "20"])],
                cwd=self.base_dir,
                capture_output=True,
                text=True,
            )

            snapshots = []
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(" ", 1)
                        if len(parts) == 2:
                            snapshots.append(
                                {
                                    "hash": parts[0],
                                    "timestamp": parts[1],
                                }
                            )

            if not snapshots:
                snapshots = self._list_from_objects()

            return snapshots
        except subprocess.CalledProcessError:
            return []

    def _list_from_objects(self) -> list[dict]:
        """List snapshots from objects directory (for write-tree snapshots)."""
        git_dir = self._git_dir()
        objects_dir = git_dir / "objects"

        if not objects_dir.exists():
            return []

        timestamps_file = self.snapshot_dir / "timestamps.json"
        timestamps = {}
        if timestamps_file.exists():
            try:
                with open(timestamps_file) as f:
                    timestamps = json.load(f)
            except Exception:
                pass

        snapshots = []
        try:
            for obj_dir in objects_dir.iterdir():
                if obj_dir.is_dir() and len(obj_dir.name) == 2:
                    for obj_file in obj_dir.iterdir():
                        if obj_file.is_file():
                            snapshot_hash = obj_dir.name + obj_file.name
                            snapshots.append(
                                {
                                    "hash": snapshot_hash,
                                    "timestamp": timestamps.get(snapshot_hash, "unknown"),
                                }
                            )
        except Exception:
            pass

        def sort_key(s):
            ts = s.get("timestamp", "unknown")
            if ts == "unknown":
                return ""
            return ts

        snapshots.sort(key=sort_key, reverse=True)
        return snapshots[:20]

    async def get_snapshot_info(self, snapshot_hash: str) -> Optional[dict]:
        """Get information about a specific snapshot."""
        if not self.enabled:
            return None

        git_dir = self._git_dir()

        if not git_dir.exists():
            return None

        try:
            result = subprocess.run(
                ["git", *self._git_args(["show", "-s", "--format=%H %ci", snapshot_hash])],
                cwd=self.base_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0 and result.stdout:
                parts = result.stdout.strip().split(" ", 1)
                if len(parts) == 2:
                    return {
                        "hash": parts[0],
                        "timestamp": parts[1],
                    }
        except subprocess.CalledProcessError:
            pass

        return None

    async def cleanup(self, days: int = None):
        """Clean up old snapshots (garbage collection).

        Removes unreachable objects older than specified days.
        """
        if not self.enabled:
            return

        days = days or self.DEFAULT_PRUNE_AGE_DAYS
        prune_date = f"{days}.days"

        git_dir = self._git_dir()

        if not git_dir.exists():
            return

        try:
            subprocess.run(
                ["git", *self._git_args(["gc", f"--prune={prune_date}"])],
                cwd=self.base_dir,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass


def create_snapshot_manager(base_dir: str = None) -> SnapshotManager:
    """Create and initialize a snapshot manager."""
    return SnapshotManager(base_dir)
