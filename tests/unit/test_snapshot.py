"""Tests for snapshot module - git-based workspace state tracking."""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path

from nanocode.snapshot import GitSnapshotManager


class TestGitSnapshotManager:
    """Tests for GitSnapshotManager."""

    @pytest.fixture
    def worktree(self):
        """Create a temporary working directory with git."""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    async def manager(self, worktree):
        """Create a GitSnapshotManager."""
        mgr = GitSnapshotManager(worktree=worktree)
        await mgr.init_repo("test-session")
        return mgr

    @pytest.mark.asyncio
    async def test_init_repo(self, worktree):
        """Test repo initialization."""
        mgr = GitSnapshotManager(worktree=worktree)
        result = await mgr.init_repo("test-session")
        assert result is True

        # Verify git dir exists (in snapshot base, not worktree)
        git_dir = mgr._get_repo_dir("test-session") / ".git"
        assert git_dir.exists()

    @pytest.mark.asyncio
    async def test_create_snapshot(self, manager):
        """Test creating a snapshot."""
        # Create a test file
        test_file = Path(manager.worktree) / "test.txt"
        test_file.write_text("hello")

        # Create snapshot
        snapshot_hash = await manager.create_snapshot("test-session", "Test snapshot")
        assert snapshot_hash is not None
        assert len(snapshot_hash) > 0

    @pytest.mark.asyncio
    async def test_list_snapshots(self, manager):
        """Test listing snapshots."""
        # Create a couple of snapshots
        test_file = Path(manager.worktree) / "test.txt"
        test_file.write_text("v1")

        hash1 = await manager.create_snapshot("test-session", "Snapshot 1")
        assert hash1 is not None

        test_file.write_text("v2")
        hash2 = await manager.create_snapshot("test-session", "Snapshot 2")
        assert hash2 is not None

        # List snapshots
        snapshots = await manager.list_snapshots("test-session")
        assert len(snapshots) >= 2

    @pytest.mark.asyncio
    async def test_restore_snapshot(self, manager):
        """Test restoring a snapshot."""
        # Create initial file
        test_file = Path(manager.worktree) / "test.txt"
        test_file.write_text("original")

        # Create snapshot
        snapshot_hash = await manager.create_snapshot("test-session", "Original state")
        assert snapshot_hash is not None

        # Modify file
        test_file.write_text("modified")
        assert test_file.read_text() == "modified"

        # Restore snapshot
        result = await manager.restore_snapshot("test-session", snapshot_hash)
        assert result is True

        # Verify file is restored
        assert test_file.read_text() == "original"

    @pytest.mark.asyncio
    async def test_diff_snapshots(self, manager):
        """Test diffing between snapshots."""
        test_file = Path(manager.worktree) / "test.txt"

        # Create first snapshot
        test_file.write_text("line1")
        hash1 = await manager.create_snapshot("test-session", "Snapshot 1")

        # Create second snapshot
        test_file.write_text("line1\nline2")
        hash2 = await manager.create_snapshot("test-session", "Snapshot 2")

        # Get diff
        diffs = await manager.diff_snapshots("test-session", hash1, hash2)
        assert len(diffs) > 0

    @pytest.mark.asyncio
    async def test_get_file_at_snapshot(self, manager):
        """Test getting file content at a snapshot."""
        test_file = Path(manager.worktree) / "test.txt"
        test_file.write_text("content v1")

        snapshot_hash = await manager.create_snapshot("test-session", "Snapshot")

        # Modify file
        test_file.write_text("content v2")

        # Get file at snapshot
        content = await manager.get_file_at_snapshot(
            "test-session", snapshot_hash, "test.txt"
        )
        assert content == "content v1"
