"""Tests for the Git Introspection Tools."""

import pytest
import tempfile
import os
from pathlib import Path

from nanocode.git_tools import (
    GitIntrospection,
    GitBranch,
    GitStash,
    GitCommit,
    GitLogEntry,
    get_git_introspection,
    reset_git_introspection,
)


class TestGitBranch:
    """Tests for GitBranch dataclass."""

    def test_branch_creation(self):
        """Test creating a branch."""
        branch = GitBranch(name="main", is_current=True)
        assert branch.name == "main"
        assert branch.is_current is True
        assert branch.is_remote is False

    def test_branch_with_tracking(self):
        """Test branch with tracking info."""
        branch = GitBranch(
            name="feature",
            tracking="origin/feature",
        )
        assert branch.tracking == "origin/feature"


class TestGitStash:
    """Tests for GitStash dataclass."""

    def test_stash_creation(self):
        """Test creating a stash."""
        stash = GitStash(
            index=0,
            branch="main",
            description="WIP: work in progress",
            commit="abc123",
        )
        assert stash.index == 0
        assert stash.description == "WIP: work in progress"


class TestGitLogEntry:
    """Tests for GitLogEntry dataclass."""

    def test_log_entry_creation(self):
        """Test creating a log entry."""
        entry = GitLogEntry(
            hash="abc123def456",
            short_hash="abc123",
            author="Test User",
            date="2024-01-01",
            subject="Initial commit",
        )
        assert entry.hash == "abc123def456"
        assert entry.short_hash == "abc123"


class TestGitIntrospection:
    """Tests for GitIntrospection."""

    def test_init(self):
        """Test initialization."""
        gi = GitIntrospection(workdir="/tmp")
        assert gi.workdir == "/tmp"

    @pytest.mark.asyncio
    async def test_get_repo_root(self):
        """Test getting repo root."""
        gi = GitIntrospection()
        root = await gi.get_repo_root()
        # Should return something in the current repo
        assert root is None or "nanocode" in root or "my_code" in root

    @pytest.mark.asyncio
    async def test_is_dirty(self):
        """Test checking if repo is dirty."""
        gi = GitIntrospection()
        dirty = await gi.is_dirty()
        assert isinstance(dirty, bool)

    @pytest.mark.asyncio
    async def test_get_current_commit(self):
        """Test getting current commit."""
        gi = GitIntrospection()
        commit = await gi.get_current_commit()
        assert commit is None or len(commit) == 40

    @pytest.mark.asyncio
    async def test_branch_list(self):
        """Test listing branches."""
        gi = GitIntrospection()
        branches = await gi.branch_list()
        assert isinstance(branches, list)

    @pytest.mark.asyncio
    async def test_stash_list(self):
        """Test listing stashes."""
        gi = GitIntrospection()
        stashes = await gi.stash_list()
        assert isinstance(stashes, list)

    @pytest.mark.asyncio
    async def test_log_file(self):
        """Test getting log for a file."""
        gi = GitIntrospection()
        log = await gi.log_file("nanocode/core.py", max_count=5)
        assert isinstance(log, list)

    @pytest.mark.asyncio
    async def test_diff_stat(self):
        """Test getting diff stat."""
        gi = GitIntrospection()
        diff = await gi.diff_stat("HEAD~1")
        assert "content" in diff


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_git_introspection_singleton(self):
        """Test global instance is singleton."""
        reset_git_introspection()
        g1 = get_git_introspection()
        g2 = get_git_introspection()
        assert g1 is g2

    def test_reset_git_introspection(self):
        """Test resetting global instance."""
        g1 = get_git_introspection()
        reset_git_introspection()
        g2 = get_git_introspection()
        assert g1 is not g2
