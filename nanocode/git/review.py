"""Code Review System - Diff parser + structured review with severity levels.

Ported from kilo's kilocode/review/review.ts and types.ts.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DiffHunk:
    """A hunk in a diff."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    content: str


@dataclass
class DiffFile:
    """A file in a diff."""

    path: str
    status: str  # added, modified, deleted, renamed
    hunks: list[DiffHunk]
    old_path: str | None = None


@dataclass
class DiffResult:
    """Parsed diff result."""

    files: list[DiffFile]
    raw: str


@dataclass
class ReviewIssue:
    """A single issue found in review."""

    severity: str  # CRITICAL, WARNING, SUGGESTION
    file_line: str
    issue: str
    confidence: int = 85


@dataclass
class ReviewResult:
    """Code review result."""

    summary: str
    issues: list[ReviewIssue]
    detailed_findings: list[str]
    recommendation: str  # APPROVE, APPROVE_WITH_SUGGESTIONS, NEEDS_CHANGES


def _git(args: list[str], cwd: str) -> str:
    """Run a git command."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        return result.stdout
    except Exception as e:
        logger.warning(f"Git command failed: {e}")
        return ""


def parse_diff(raw: str) -> DiffResult:
    """Parse unified diff output into structured DiffResult.

    Args:
        raw: Raw git diff output

    Returns:
        DiffResult with parsed files and hunks
    """
    if not raw.strip():
        return DiffResult(files=[], raw=raw)

    file_diffs = raw.split("\ndiff --git ")
    files = []

    for file_diff in file_diffs:
        if not file_diff.strip():
            continue

        if not file_diff.startswith("diff --git "):
            file_diff = "diff --git " + file_diff

        lines = file_diff.split("\n")
        if not lines:
            continue

        header_match = lines[0].replace("diff --git ", "")
        parts = header_match.split(" ")
        if len(parts) < 2:
            continue

        old_path = parts[0].lstrip("a/")
        new_path = parts[1].lstrip("b/")

        status = "modified"
        if "new file mode" in file_diff:
            status = "added"
        elif "deleted file mode" in file_diff:
            status = "deleted"
        elif "rename from" in file_diff:
            status = "renamed"

        hunks = []
        current_hunk = None
        hunk_content = []

        for line in lines:
            import re
            hunk_match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if hunk_match:
                if current_hunk:
                    current_hunk.content = "\n".join(hunk_content)
                    hunks.append(current_hunk)
                current_hunk = DiffHunk(
                    old_start=int(hunk_match.group(1)),
                    old_lines=int(hunk_match.group(2) or "1"),
                    new_start=int(hunk_match.group(3)),
                    new_lines=int(hunk_match.group(4) or "1"),
                    content="",
                )
                hunk_content = [line]
            elif current_hunk:
                hunk_content.append(line)

        if current_hunk:
            current_hunk.content = "\n".join(hunk_content)
            hunks.append(current_hunk)

        files.append(DiffFile(
            path=new_path,
            status=status,
            hunks=hunks,
            old_path=old_path if old_path != new_path else None,
        ))

    return DiffResult(files=files, raw=raw)


def _count_changes(file: DiffFile) -> tuple[int, int]:
    """Count additions and deletions in a file."""
    additions = 0
    deletions = 0
    for hunk in file.hunks:
        for line in hunk.content.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
    return additions, deletions


def _format_file_list(files: list[DiffFile]) -> str:
    """Format file list for review prompt."""
    lines = []
    for f in files:
        status_icon = {"added": "[A]", "deleted": "[D]", "renamed": "[R]"}.get(f.status, "[M]")
        additions, deletions = _count_changes(f)
        renamed = f" (was: {f.old_path})" if f.old_path else ""
        lines.append(f"- {status_icon} {f.path}{renamed} (+{additions}, -{deletions})")
    return "\n".join(lines)


REVIEW_PROMPT = """You are an expert code reviewer. Review the following changes.

## Files Changed
{file_list}

## Review Guidelines
- **CRITICAL (95%+)**: Security vulnerabilities, data loss risks, crashes
- **WARNING (85%+)**: Bugs, logic errors, performance issues
- **SUGGESTION (75%+)**: Code quality improvements, best practices

## Format
Respond with ONLY a JSON object:
{{
  "summary": "2-3 sentence summary of changes",
  "issues": [
    {{"severity": "CRITICAL|WARNING|SUGGESTION", "file_line": "path:line", "issue": "description"}}
  ],
  "recommendation": "APPROVE|APPROVE_WITH_SUGGESTIONS|NEEDS_CHANGES"
}}

If no issues found, return empty issues array and APPROVE recommendation."""


async def get_uncommitted_changes(cwd: str | None = None) -> DiffResult:
    """Get uncommitted changes (staged + unstaged).

    Args:
        cwd: Repository path

    Returns:
        DiffResult with parsed changes
    """
    import asyncio

    cwd = cwd or "."

    def _get():
        raw = _git(["diff", "HEAD"], cwd)
        return parse_diff(raw)

    return await asyncio.get_event_loop().run_in_executor(None, _get)


async def get_base_branch(cwd: str | None = None) -> str:
    """Detect base branch (main, master, dev, develop).

    Args:
        cwd: Repository path

    Returns:
        Base branch name
    """
    import asyncio

    cwd = cwd or "."

    def _get():
        candidates = ["main", "master", "dev", "develop"]
        for branch in candidates:
            result = _git(["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], cwd)
            if result == "":
                return f"origin/{branch}"
        for branch in candidates:
            result = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd)
            if result == "":
                return branch
        return "main"

    return await asyncio.get_event_loop().run_in_executor(None, _get)


async def build_review_prompt_uncommitted(cwd: str | None = None) -> str:
    """Build review prompt for uncommitted changes.

    Args:
        cwd: Repository path

    Returns:
        Review prompt string
    """
    diff = await get_uncommitted_changes(cwd)

    if not diff.files:
        return "No changes to review."

    file_list = _format_file_list(diff.files)
    return REVIEW_PROMPT.format(file_list=file_list)


async def build_review_prompt_branch(cwd: str | None = None) -> str:
    """Build review prompt for branch diff.

    Args:
        cwd: Repository path

    Returns:
        Review prompt string
    """
    import asyncio

    cwd = cwd or "."

    def _get():
        base = get_base_branch(cwd) if False else "main"
        raw = _git(["diff", "origin/main...HEAD"], cwd)
        return parse_diff(raw)

    diff = await asyncio.get_event_loop().run_in_executor(None, _get)

    if not diff.files:
        return "No changes to review."

    file_list = _format_file_list(diff.files)
    return REVIEW_PROMPT.format(file_list=file_list)


async def run_review(
    prompt: str,
    model_id: str = "default",
) -> ReviewResult:
    """Run a code review using LLM.

    Args:
        prompt: Review prompt
        model_id: Model to use

    Returns:
        ReviewResult with findings
    """
    try:
        import json
        from nanocode.llm import Message, create_llm_from_model_id

        llm, _ = await create_llm_from_model_id(model_id)
        response = await llm.chat([Message("user", prompt)])
        result_text = response.content.strip()

        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1]
            if result_text.endswith("```"):
                result_text = result_text[:-3]

        result = json.loads(result_text)

        issues = [
            ReviewIssue(
                severity=issue.get("severity", "SUGGESTION"),
                file_line=issue.get("file_line", ""),
                issue=issue.get("issue", ""),
            )
            for issue in result.get("issues", [])
        ]

        return ReviewResult(
            summary=result.get("summary", ""),
            issues=issues,
            detailed_findings=[],
            recommendation=result.get("recommendation", "APPROVE"),
        )

    except Exception as e:
        logger.error(f"Review failed: {e}")
        return ReviewResult(
            summary=f"Review failed: {e}",
            issues=[],
            detailed_findings=[],
            recommendation="NEEDS_CHANGES",
        )
