"""Git worktree management."""

import os
import re
import random
import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


ADJECTIVES = [
    "brave",
    "calm",
    "clever",
    "cosmic",
    "crisp",
    "curious",
    "eager",
    "gentle",
    "glowing",
    "happy",
    "hidden",
    "jolly",
    "kind",
    "lucky",
    "mighty",
    "misty",
    "neon",
    "nimble",
    "playful",
    "proud",
    "quick",
    "quiet",
    "shiny",
    "silent",
    "stellar",
    "sunny",
    "swift",
    "tidy",
    "witty",
]

NOUNS = [
    "cabin",
    "cactus",
    "canyon",
    "circuit",
    "comet",
    "eagle",
    "engine",
    "falcon",
    "forest",
    "garden",
    "harbor",
    "island",
    "knight",
    "lagoon",
    "meadow",
    "moon",
    "mountain",
    "nebula",
    "orchid",
    "otter",
    "panda",
    "pixel",
    "planet",
    "river",
    "rocket",
    "sailor",
    "squid",
    "star",
    "tiger",
    "wizard",
    "wolf",
]


@dataclass
class WorktreeInfo:
    """Information about a worktree."""

    name: str
    branch: str
    directory: str


class WorktreeError(Exception):
    """Base exception for worktree errors."""

    pass


class NotGitError(WorktreeError):
    """Raised when project is not a git repository."""

    pass


class CreateFailedError(WorktreeError):
    """Raised when worktree creation fails."""

    pass


class RemoveFailedError(WorktreeError):
    """Raised when worktree removal fails."""

    pass


class ResetFailedError(WorktreeError):
    """Raised when worktree reset fails."""

    pass


def _run_git_command(cmd: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise WorktreeError(result.stderr or result.stdout or f"Command failed: {' '.join(cmd)}")
    return result


def _slug(text: str) -> str:
    """Convert text to a Slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def _random_name() -> str:
    """Generate a random worktree name."""
    return f"{random.choice(ADJECTIVES)}-{random.choice(NOUNS)}"


def _exists(path: str) -> bool:
    """Check if a path exists."""
    return os.path.exists(path)


async def _canonical(path: str) -> str:
    """Get canonical path."""
    return os.path.realpath(path)


def _is_git_repo(path: str) -> bool:
    """Check if path is a git repository."""
    return os.path.exists(os.path.join(path, ".git"))


def _get_git_common_dir(cwd: str) -> Optional[str]:
    """Get the git common directory (handles worktrees)."""
    try:
        result = _run_git_command(["git", "rev-parse", "--git-common-dir"], cwd, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_worktree_root(cwd: str = None) -> str:
    """Get the worktree root for a directory."""
    cwd = cwd or os.getcwd()

    common_dir = _get_git_common_dir(cwd)
    if common_dir and common_dir != ".git":
        return os.path.dirname(common_dir)

    return cwd


def is_worktree(path: str) -> bool:
    """Check if a path is a git worktree."""
    git_dir = os.path.join(path, ".git")
    if os.path.isfile(git_dir):
        content = Path(git_dir).read_text()
        return "gitdir:" in content
    return False


def generate_name(base: Optional[str] = None, root: str = None) -> WorktreeInfo:
    """Generate a unique worktree name."""
    if base:
        base = _slug(base)

    attempts = 0
    while attempts < 26:
        if base:
            name = base if attempts == 0 else f"{base}-{_random_name()}"
        else:
            name = _random_name()

        branch = f"opencode/{name}"
        directory = os.path.join(root or ".", name)

        if not _exists(directory):
            ref_result = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
            )
            if ref_result.returncode != 0:
                return WorktreeInfo(name=name, branch=branch, directory=directory)

        attempts += 1

    raise WorktreeError("Failed to generate a unique worktree name")


def list_worktrees(cwd: str = None) -> list[WorktreeInfo]:
    """List all worktrees."""
    cwd = cwd or os.getcwd()
    worktree_root = get_worktree_root(cwd)

    if not _is_git_repo(worktree_root):
        return []

    result = _run_git_command(
        ["git", "worktree", "list", "--porcelain"], worktree_root, check=False
    )
    if result.returncode != 0:
        return []

    worktrees = []
    current = None

    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("worktree "):
            path = line[len("worktree ") :].strip()
            current = {"path": path}
        elif line.startswith("branch "):
            branch = line[len("branch ") :].strip()
            if current:
                current["branch"] = branch
                worktrees.append(
                    WorktreeInfo(
                        name=os.path.basename(current["path"]),
                        branch=branch,
                        directory=current["path"],
                    )
                )
                current = None
        elif line == "bare":
            pass
        elif line == "head detached":
            if current:
                current["branch"] = "HEAD"

    return worktrees


def create(
    name: Optional[str] = None,
    cwd: str = None,
    start_command: Optional[str] = None,
) -> WorktreeInfo:
    """Create a new git worktree."""
    cwd = cwd or os.getcwd()
    worktree_root = get_worktree_root(cwd)

    if not _is_git_repo(worktree_root):
        raise NotGitError("Worktrees are only supported for git projects")

    info = generate_name(name, root=worktree_root)

    result = _run_git_command(
        ["git", "worktree", "add", "--no-checkout", "-b", info.branch, info.directory],
        worktree_root,
        check=False,
    )

    if result.returncode != 0:
        raise CreateFailedError(result.stderr or "Failed to create git worktree")

    checkout_result = _run_git_command(
        ["git", "checkout", info.branch],
        info.directory,
        check=False,
    )

    if checkout_result.returncode != 0:
        raise CreateFailedError(checkout_result.stderr or "Failed to checkout branch")

    if start_command:
        subprocess.run(
            ["bash", "-lc", start_command],
            cwd=info.directory,
            capture_output=True,
        )

    return info


def remove(directory: str, force: bool = False) -> bool:
    """Remove a git worktree."""
    cwd = os.getcwd()
    worktree_root = get_worktree_root(cwd)

    if not _is_git_repo(worktree_root):
        raise NotGitError("Worktrees are only supported for git projects")

    directory = os.path.realpath(directory)

    worktrees = list_worktrees(worktree_root)
    entry = None
    for wt in worktrees:
        if os.path.realpath(wt.directory) == directory:
            entry = wt
            break

    if not entry:
        if _exists(directory):
            import shutil

            shutil.rmtree(directory)
        return True

    if entry.branch == "HEAD":
        result = _run_git_command(
            ["git", "worktree", "remove", "--force" if force else directory],
            worktree_root,
            check=False,
        )
    else:
        result = _run_git_command(
            ["git", "worktree", "remove", "--force" if force else entry.directory],
            worktree_root,
            check=False,
        )

    if result.returncode != 0:
        raise RemoveFailedError(result.stderr or "Failed to remove git worktree")

    if entry.branch != "HEAD":
        branch_result = _run_git_command(
            ["git", "branch", "-D", entry.branch.replace("refs/heads/", "")],
            worktree_root,
            check=False,
        )

    return True


def reset(directory: str) -> bool:
    """Reset a worktree to the default branch."""
    cwd = os.getcwd()
    worktree_root = get_worktree_root(cwd)

    if not _is_git_repo(worktree_root):
        raise NotGitError("Worktrees are only supported for git projects")

    directory = os.path.realpath(directory)
    primary = os.path.realpath(worktree_root)

    if directory == primary:
        raise ResetFailedError("Cannot reset the primary workspace")

    worktrees = list_worktrees(worktree_root)
    entry = None
    for wt in worktrees:
        if os.path.realpath(wt.directory) == directory:
            entry = wt
            break

    if not entry:
        raise ResetFailedError("Worktree not found")

    remote_result = _run_git_command(["git", "remote"], worktree_root, check=False)
    if remote_result.returncode != 0:
        raise ResetFailedError("Failed to list git remotes")

    remotes = [r.strip() for r in remote_result.stdout.split("\n") if r.strip()]
    remote = "origin" if "origin" in remotes else (remotes[0] if remotes else "")

    main_check = _run_git_command(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"],
        worktree_root,
        check=False,
    )
    master_check = _run_git_command(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/master"],
        worktree_root,
        check=False,
    )

    if main_check.returncode == 0:
        target = "origin/main" if remote else "main"
    elif master_check.returncode == 0:
        target = "origin/master" if remote else "master"
    else:
        raise ResetFailedError("Default branch not found")

    if remote:
        fetch_result = _run_git_command(
            ["git", "fetch", remote, target.split("/")[1]],
            worktree_root,
            check=False,
        )
        if fetch_result.returncode != 0:
            raise ResetFailedError(f"Failed to fetch {target}")

    reset_result = _run_git_command(
        ["git", "reset", "--hard", target],
        directory,
        check=False,
    )

    if reset_result.returncode != 0:
        raise ResetFailedError(reset_result.stderr or "Failed to reset worktree")

    clean_result = _run_git_command(
        ["git", "clean", "-ffdx"],
        directory,
        check=False,
    )

    if clean_result.returncode != 0:
        raise ResetFailedError(clean_result.stderr or "Failed to clean worktree")

    return True


def get_current_worktree(cwd: str = None) -> Optional[WorktreeInfo]:
    """Get the current worktree info."""
    cwd = cwd or os.getcwd()
    worktrees = list_worktrees(cwd)

    cwd_real = os.path.realpath(cwd)

    for wt in worktrees:
        if os.path.realpath(wt.directory) == cwd_real:
            return wt

    return None
