"""Tests for snapshot module."""

import pytest
import tempfile
import os
import subprocess
import shutil

from nanocode.snapshot import SnapshotManager, Patch


class TestSnapshotManager:
    """Test snapshot manager."""

    @pytest.fixture
    def temp_git_dir(self):
        """Create a temporary directory with a git repository."""
        tmpdir = tempfile.mkdtemp()

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)

        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original content")

        subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmpdir,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        yield tmpdir

        shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_is_available(self, temp_git_dir):
        """Test checking if snapshot is available."""
        manager = SnapshotManager(temp_git_dir)

        available = await manager.is_available()

        assert available is True

    @pytest.mark.asyncio
    async def test_init_creates_snapshot_dir(self, temp_git_dir):
        """Test initialization creates snapshot directory."""
        manager = SnapshotManager(temp_git_dir)

        await manager.init()

        assert manager._git_dir().exists()

    @pytest.mark.asyncio
    async def test_track_creates_snapshot(self, temp_git_dir):
        """Test creating a snapshot captures current state."""
        manager = SnapshotManager(temp_git_dir)

        snapshot_hash = await manager.track()

        assert snapshot_hash is not None
        assert len(snapshot_hash) == 40

    @pytest.mark.asyncio
    async def test_track_after_file_change(self, temp_git_dir):
        """Test tracking detects file changes."""
        manager = SnapshotManager(temp_git_dir)

        snapshot1 = await manager.track()

        test_file = os.path.join(temp_git_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("modified content")

        snapshot2 = await manager.track()

        assert snapshot1 != snapshot2

    @pytest.mark.asyncio
    async def test_patch_returns_changed_files(self, temp_git_dir):
        """Test patch returns list of changed files."""
        manager = SnapshotManager(temp_git_dir)

        snapshot1 = await manager.track()

        test_file = os.path.join(temp_git_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("modified content")

        patch = await manager.patch(snapshot1)

        assert isinstance(patch, Patch)
        assert len(patch.files) > 0
        assert any("test.txt" in f for f in patch.files)

    @pytest.mark.asyncio
    async def test_restore_restores_files(self, temp_git_dir):
        """Test restoring a snapshot restores files."""
        manager = SnapshotManager(temp_git_dir)

        snapshot1 = await manager.track()

        test_file = os.path.join(temp_git_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("modified content")

        await manager.restore(snapshot1)

        with open(test_file) as f:
            content = f.read()

        assert content == "original content"

    @pytest.mark.asyncio
    async def test_list_snapshots(self, temp_git_dir):
        """Test listing snapshots."""
        manager = SnapshotManager(temp_git_dir)

        await manager.track()

        snapshots = await manager.list_snapshots()

        assert isinstance(snapshots, list)

    @pytest.mark.asyncio
    async def test_snapshot_disabled(self, temp_git_dir):
        """Test that disabled snapshot returns None."""
        manager = SnapshotManager(temp_git_dir)
        manager.enabled = False

        snapshot_hash = await manager.track()

        assert snapshot_hash is None

    @pytest.mark.asyncio
    async def test_restore_invalid_hash(self, temp_git_dir):
        """Test restoring with invalid hash fails gracefully."""
        manager = SnapshotManager(temp_git_dir)

        success = await manager.restore("invalid_hash_00000000000000000000000000")

        assert success is False


class TestSnapshotTools:
    """Test snapshot tools."""

    @pytest.fixture
    def temp_git_dir(self):
        """Create a temporary directory with a git repository."""
        tmpdir = tempfile.mkdtemp()

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)

        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original content")

        subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmpdir,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        yield tmpdir

        shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_snapshot_tool(self, temp_git_dir):
        """Test snapshot tool creates snapshot."""
        from nanocode.snapshot import SnapshotManager
        from nanocode.tools.builtin.snapshot import SnapshotTrackTool

        manager = SnapshotManager(temp_git_dir)
        tool = SnapshotTrackTool(manager)

        result = await tool.execute(description="test snapshot")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_revert_tool(self, temp_git_dir):
        """Test revert tool restores files."""
        from nanocode.snapshot import SnapshotManager
        from nanocode.tools.builtin.snapshot import SnapshotRevertTool

        manager = SnapshotManager(temp_git_dir)

        test_file = os.path.join(temp_git_dir, "test.txt")

        snapshot = await manager.track()
        assert snapshot is not None

        with open(test_file, "w") as f:
            f.write("modified content")

        revert_tool = SnapshotRevertTool(manager)
        result = await revert_tool.execute(snapshot=snapshot)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_diff_tool(self, temp_git_dir):
        """Test snapshot_diff tool shows changes."""
        from nanocode.snapshot import SnapshotManager
        from nanocode.tools.builtin.snapshot import SnapshotDiffTool

        manager = SnapshotManager(temp_git_dir)

        snapshot = await manager.track()
        assert snapshot is not None

        test_file = os.path.join(temp_git_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("modified content")

        diff_tool = SnapshotDiffTool(manager)
        result = await diff_tool.execute(snapshot=snapshot)

        assert result.success is True
        assert "Snapshot created" in result.content

    @pytest.mark.asyncio
    async def test_revert_tool(self, temp_git_dir):
        """Test revert tool restores files."""
        from nanocode.snapshot import SnapshotManager
        from nanocode.tools.builtin.snapshot import SnapshotTrackTool, SnapshotRevertTool

        manager = SnapshotManager(temp_git_dir)

        track_tool = SnapshotTrackTool(manager)
        await track_tool.execute()

        test_file = os.path.join(temp_git_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("modified content")

        revert_tool = SnapshotRevertTool(manager)
        snapshots = await manager.list_snapshots()

        result = await revert_tool.execute(snapshot=snapshots[0]["hash"])

        with open(test_file) as f:
            content = f.read()

        assert result.success is True
        assert content == "original content"

    @pytest.mark.asyncio
    async def test_list_snapshots_tool(self, temp_git_dir):
        """Test snapshots tool lists snapshots."""
        from nanocode.snapshot import SnapshotManager
        from nanocode.tools.builtin.snapshot import SnapshotListTool

        manager = SnapshotManager(temp_git_dir)

        list_tool = SnapshotListTool(manager)
        result = await list_tool.execute()

        assert result.success is True

    @pytest.mark.asyncio
    async def test_diff_tool(self, temp_git_dir):
        """Test snapshot_diff tool shows changes."""
        from nanocode.snapshot import SnapshotManager
        from nanocode.tools.builtin.snapshot import SnapshotTrackTool, SnapshotDiffTool

        manager = SnapshotManager(temp_git_dir)

        track_tool = SnapshotTrackTool(manager)
        snapshot = await track_tool.execute()

        test_file = os.path.join(temp_git_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("modified content")

        diff_tool = SnapshotDiffTool(manager)
        result = await diff_tool.execute(snapshot="latest")

        assert result.success is True
