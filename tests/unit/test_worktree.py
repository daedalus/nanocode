"""Tests for worktree functionality."""

import pytest
import os
import subprocess
from nanocode.worktree import (
    WorktreeInfo,
    NotGitError,
    generate_name,
    list_worktrees,
    get_worktree_root,
    is_worktree,
    get_current_worktree,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    os.chdir(tmp_path)

    subprocess.run(["git", "init"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], capture_output=True)

    (tmp_path / "test.txt").write_text("test")
    subprocess.run(["git", "add", "."], capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], capture_output=True)

    return tmp_path


def test_generate_name():
    """Test generating worktree name."""
    info = generate_name(root="/tmp")
    assert info.name
    assert info.branch.startswith("opencode/")
    assert info.directory


def test_generate_name_with_base():
    """Test generating worktree name with base."""
    info = generate_name(base="test-base", root="/tmp")
    assert info.name == "test-base"
    assert info.branch == "opencode/test-base"
    assert info.directory == "/tmp/test-base"


def test_slug():
    """Test slug generation."""
    from nanocode.worktree import _slug

    assert _slug("Hello World") == "hello-world"
    assert _slug("Test  Multiple   Spaces") == "test-multiple-spaces"
    assert _slug("--leading-dashes") == "leading-dashes"


def test_get_worktree_root(git_repo):
    """Test getting worktree root."""
    root = get_worktree_root(str(git_repo))
    assert root == str(git_repo)


def test_is_worktree(git_repo):
    """Test checking if path is worktree."""
    assert is_worktree(str(git_repo)) is False


def test_list_worktrees(git_repo):
    """Test listing worktrees."""
    worktrees = list_worktrees(str(git_repo))
    assert len(worktrees) >= 1


def test_not_git_error():
    """Test NotGitError exception."""
    with pytest.raises(NotGitError):
        raise NotGitError("Not a git repo")


def test_worktree_info_dataclass():
    """Test WorktreeInfo dataclass."""
    info = WorktreeInfo(
        name="test",
        branch="opencode/test",
        directory="/tmp/test",
    )
    assert info.name == "test"
    assert info.branch == "opencode/test"
    assert info.directory == "/tmp/test"


def test_generate_name_unique():
    """Test that generated names are unique."""
    names = set()
    for _ in range(10):
        info = generate_name(root="/tmp")
        names.add(info.name)

    assert len(names) == 10


def test_get_current_worktree(git_repo):
    """Test getting current worktree info."""
    info = get_current_worktree(str(git_repo))
    assert info is not None


def test_list_worktrees_in_non_git(tmp_path):
    """Test listing worktrees in non-git directory."""
    worktrees = list_worktrees(str(tmp_path))
    assert worktrees == []
