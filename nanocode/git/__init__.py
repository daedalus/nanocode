"""Git utilities for commit message and code review."""

from .commit_message import (
    CommitMessageResult,
    FileChange,
    GitContext,
    generate_commit_message,
    get_git_context,
)
from .review import (
    DiffFile,
    DiffHunk,
    DiffResult,
    ReviewResult,
    build_review_prompt_branch,
    build_review_prompt_uncommitted,
    get_base_branch,
    get_uncommitted_changes,
    parse_diff,
)

__all__ = [
    "CommitMessageResult",
    "FileChange",
    "GitContext",
    "generate_commit_message",
    "get_git_context",
    "DiffFile",
    "DiffHunk",
    "DiffResult",
    "ReviewResult",
    "build_review_prompt_branch",
    "build_review_prompt_uncommitted",
    "get_base_branch",
    "get_uncommitted_changes",
    "parse_diff",
]
