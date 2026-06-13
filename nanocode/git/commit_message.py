"""Commit Message Generator - LLM-powered conventional commits.

Ported from kilo's commit-message/generate.ts and git-context.ts.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
    "Pipfile.lock", "poetry.lock", "pdm.lock", "uv.lock",
    "Cargo.lock", "go.sum", "Gemfile.lock", "composer.lock",
    "flake.lock", "poetry.lock", "Pipfile.lock",
}

MAX_DIFF_LENGTH = 4000


@dataclass
class FileChange:
    """A single file change in a commit."""

    status: str  # added, modified, deleted, renamed
    path: str
    diff: str = ""
    old_path: str | None = None


@dataclass
class GitContext:
    """Git context for commit message generation."""

    branch: str
    recent_commits: list[str]
    files: list[FileChange]


@dataclass
class CommitMessageResult:
    """Result from commit message generation."""

    message: str
    error: str | None = None


def _git(args: list[str], cwd: str) -> str:
    """Run a git command and return output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Git command failed: {e}")
        return ""


def _parse_name_status(output: str) -> list[dict[str, str]]:
    """Parse git diff --name-status output."""
    if not output:
        return []
    entries = []
    for line in output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            entries.append({"status": "renamed", "path": parts[2] if len(parts) > 2 else parts[1]})
        elif status == "A" or status == "?":
            entries.append({"status": "added", "path": parts[1]})
        elif status == "D":
            entries.append({"status": "deleted", "path": parts[1]})
        else:
            entries.append({"status": "modified", "path": parts[1]})
    return entries


def _is_lock_file(filepath: str) -> bool:
    """Check if a file is a lock file."""
    name = Path(filepath).name
    return name in LOCK_FILES


async def get_git_context(
    repo_path: str | None = None, selected_files: list[str] | None = None
) -> GitContext:
    """Get git context for commit message generation.

    Args:
        repo_path: Repository path (defaults to cwd)
        selected_files: Optional list of files to include

    Returns:
        GitContext with branch, recent commits, and file changes
    """
    import asyncio

    repo_path = repo_path or "."

    def _get_context():
        branch = _git(["branch", "--show-current"], repo_path) or "HEAD"
        log_output = _git(["log", "--oneline", "-5"], repo_path)
        recent_commits = log_output.split("\n") if log_output else []

        staged = _parse_name_status(_git(["diff", "--name-status", "--cached"], repo_path))
        use_staged = len(staged) > 0

        if use_staged:
            raw = staged
        else:
            raw = _parse_name_status(_git(["status", "--porcelain"], repo_path))

        selected = set(selected_files) if selected_files else None
        files = []

        for entry in raw:
            path = entry["path"]
            if _is_lock_file(path):
                continue
            if selected and path not in selected:
                continue

            status = entry["status"]
            if status == "added":
                diff = f"New file: {path}"
            elif status == "deleted":
                diff = f"Deleted: {path}"
            else:
                diff = _git(["diff", "--cached" if use_staged else "", "--", path], repo_path)
                if "Binary files" in diff:
                    diff = f"Binary file {path} modified"
                elif len(diff) > MAX_DIFF_LENGTH:
                    diff = diff[:MAX_DIFF_LENGTH] + "\n... [truncated]"

            files.append(FileChange(status=status, path=path, diff=diff))

        return GitContext(branch=branch, recent_commits=recent_commits, files=files)

    return await asyncio.get_event_loop().run_in_executor(None, _get_context)


COMMIT_PROMPT = """You are an expert Git commit message generator that creates conventional commit messages.

Generate a commit message following this exact structure:
```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

## Types
- **feat**: New feature or functionality
- **fix**: Bug fix or error correction
- **docs**: Documentation changes only
- **style**: Code style changes (whitespace, formatting)
- **refactor**: Code refactoring without feature changes or bug fixes
- **perf**: Performance improvements
- **test**: Adding or fixing tests
- **build**: Build system or external dependency changes
- **ci**: CI/CD configuration changes
- **chore**: Maintenance tasks, tooling changes

## Rules
- Use imperative mood ("add" not "added")
- Start with lowercase letter
- No period at the end
- Maximum 72 characters for description
- Be concise but descriptive

## Changes to commit:
Branch: {branch}
Recent commits:
{recent_commits}

Changed files:
{file_list}

Diffs:
{diffs}

Return ONLY the commit message in the conventional format, nothing else."""


async def generate_commit_message(
    context: GitContext,
    previous_message: str | None = None,
    model_id: str = "default",
) -> CommitMessageResult:
    """Generate a commit message from git context.

    Args:
        context: GitContext with branch, files, diffs
        previous_message: Optional previous message to avoid duplicates
        model_id: Model to use for generation

    Returns:
        CommitMessageResult with message or error
    """
    if not context.files:
        return CommitMessageResult(message="", error="No changes to commit")

    try:
        from nanocode.llm import Message, create_llm_from_model_id

        llm, _ = await create_llm_from_model_id(model_id)

        file_list = "\n".join(f"{f.status} {f.path}" for f in context.files)
        diffs = "\n\n".join(
            f"--- {f.path} ---\n{f.diff}" for f in context.files if f.diff
        )

        prompt = COMMIT_PROMPT.format(
            branch=context.branch,
            recent_commits="\n".join(context.recent_commits),
            file_list=file_list,
            diffs=diffs,
        )

        if previous_message:
            prompt = (
                f"IMPORTANT: Generate a COMPLETELY DIFFERENT commit message from the previous one. "
                f'The previous message was: "{previous_message}". Use a different type, scope, or description.\n\n'
                + prompt
            )

        response = await llm.chat([Message("user", prompt)])
        message = _clean_message(response.content)

        return CommitMessageResult(message=message)

    except Exception as e:
        logger.error(f"Failed to generate commit message: {e}")
        return CommitMessageResult(message="", error=str(e))


def _clean_message(text: str) -> str:
    """Clean up generated commit message."""
    result = text.strip()

    if result.startswith("```"):
        newline_idx = result.find("\n")
        if newline_idx != -1:
            result = result[newline_idx + 1:]
        else:
            result = result[3:]

    if result.endswith("```"):
        result = result[:-3]

    result = result.strip()

    if (result.startswith('"') and result.endswith('"')) or (
        result.startswith("'") and result.endswith("'")
    ):
        result = result[1:-1]

    return result.strip()
