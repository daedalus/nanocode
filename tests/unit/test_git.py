"""Tests for git commit message and code review systems."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nanocode.git.commit_message import (
    CommitMessageResult,
    FileChange,
    GitContext,
    _clean_message,
    _is_lock_file,
    _parse_name_status,
    generate_commit_message,
    get_git_context,
)
from nanocode.git.review import (
    DiffFile,
    DiffHunk,
    DiffResult,
    ReviewIssue,
    ReviewResult,
    _count_changes,
    _format_file_list,
    build_review_prompt_uncommitted,
    get_base_branch,
    get_uncommitted_changes,
    parse_diff,
    run_review,
)


class TestCommitMessage:
    """Tests for commit message generator."""

    def test_is_lock_file(self):
        assert _is_lock_file("package-lock.json")
        assert _is_lock_file("yarn.lock")
        assert _is_lock_file("poetry.lock")
        assert not _is_lock_file("main.py")

    def test_parse_name_status_added(self):
        output = "A\tnew_file.py"
        result = _parse_name_status(output)
        assert len(result) == 1
        assert result[0]["status"] == "added"
        assert result[0]["path"] == "new_file.py"

    def test_parse_name_status_modified(self):
        output = "M\tmain.py"
        result = _parse_name_status(output)
        assert len(result) == 1
        assert result[0]["status"] == "modified"

    def test_parse_name_status_deleted(self):
        output = "D\told_file.py"
        result = _parse_name_status(output)
        assert len(result) == 1
        assert result[0]["status"] == "deleted"

    def test_parse_name_status_empty(self):
        result = _parse_name_status("")
        assert result == []

    def test_clean_message_removes_code_blocks(self):
        assert _clean_message("```feat: add feature```") == "feat: add feature"
        assert _clean_message("```python\nfeat: add feature\n```") == "feat: add feature"

    def test_clean_message_removes_quotes(self):
        assert _clean_message('"feat: add feature"') == "feat: add feature"
        assert _clean_message("'feat: add feature'") == "feat: add feature"

    def test_clean_message_strips_whitespace(self):
        assert _clean_message("  feat: add feature  ") == "feat: add feature"

    def test_file_change_fields(self):
        fc = FileChange(status="added", path="test.py", diff="+content")
        assert fc.status == "added"
        assert fc.path == "test.py"

    def test_git_context_fields(self):
        ctx = GitContext(
            branch="main",
            recent_commits=["abc123 initial commit"],
            files=[FileChange(status="modified", path="test.py")],
        )
        assert ctx.branch == "main"
        assert len(ctx.files) == 1

    def test_commit_message_result(self):
        result = CommitMessageResult(message="feat: add feature")
        assert result.message == "feat: add feature"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_generate_commit_message_no_files(self):
        ctx = GitContext(branch="main", recent_commits=[], files=[])
        result = await generate_commit_message(ctx)
        assert result.error == "No changes to commit"

    @pytest.mark.asyncio
    async def test_generate_commit_message_success(self):
        ctx = GitContext(
            branch="main",
            recent_commits=["abc123 initial"],
            files=[FileChange(status="modified", path="test.py", diff="+content")],
        )

        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm_instance = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = "feat: add feature\n\nAdded new feature"
            mock_llm_instance.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = (mock_llm_instance, {})

            result = await generate_commit_message(ctx)

            assert "feat" in result.message
            assert result.error is None

    @pytest.mark.asyncio
    async def test_generate_commit_message_with_previous(self):
        ctx = GitContext(
            branch="main",
            recent_commits=[],
            files=[FileChange(status="modified", path="test.py", diff="+content")],
        )

        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm_instance = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = "fix: different message"
            mock_llm_instance.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = (mock_llm_instance, {})

            result = await generate_commit_message(ctx, previous_message="feat: old message")

            assert "fix" in result.message


class TestCodeReview:
    """Tests for code review system."""

    def test_diff_hunk_fields(self):
        hunk = DiffHunk(old_start=1, old_lines=5, new_start=1, new_lines=5, content="line")
        assert hunk.old_start == 1
        assert hunk.new_start == 1

    def test_diff_file_fields(self):
        file = DiffFile(path="test.py", status="modified", hunks=[])
        assert file.path == "test.py"
        assert file.status == "modified"

    def test_diff_result_fields(self):
        result = DiffResult(files=[], raw="")
        assert result.files == []

    def test_parse_diff_empty(self):
        result = parse_diff("")
        assert result.files == []

    def test_parse_diff_simple(self):
        diff = """diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 line1
+added line
 line2
 line3"""
        result = parse_diff(diff)
        assert len(result.files) == 1
        assert result.files[0].path == "test.py"
        assert len(result.files[0].hunks) == 1

    def test_parse_diff_added_file(self):
        diff = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+line1
+line2"""
        result = parse_diff(diff)
        assert len(result.files) == 1
        assert result.files[0].status == "added"

    def test_parse_diff_deleted_file(self):
        diff = """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-line1
-line2"""
        result = parse_diff(diff)
        assert len(result.files) == 1
        assert result.files[0].status == "deleted"

    def test_count_changes(self):
        file = DiffFile(
            path="test.py",
            status="modified",
            hunks=[DiffHunk(1, 3, 1, 4, "+added\n-removed\n unchanged")],
        )
        additions, deletions = _count_changes(file)
        assert additions == 1
        assert deletions == 1

    def test_format_file_list(self):
        files = [
            DiffFile(path="a.py", status="added", hunks=[]),
            DiffFile(path="b.py", status="modified", hunks=[]),
        ]
        result = _format_file_list(files)
        assert "[A] a.py" in result
        assert "[M] b.py" in result

    def test_review_issue_fields(self):
        issue = ReviewIssue(severity="CRITICAL", file_line="test.py:10", issue="Bug found")
        assert issue.severity == "CRITICAL"
        assert issue.file_line == "test.py:10"

    def test_review_result_fields(self):
        result = ReviewResult(
            summary="Good code",
            issues=[],
            detailed_findings=[],
            recommendation="APPROVE",
        )
        assert result.recommendation == "APPROVE"

    @pytest.mark.asyncio
    async def test_run_review_success(self):
        prompt = "Review this code"

        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm_instance = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = '{"summary": "Good code", "issues": [], "recommendation": "APPROVE"}'
            mock_llm_instance.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = (mock_llm_instance, {})

            result = await run_review(prompt)

            assert result.recommendation == "APPROVE"
            assert result.summary == "Good code"

    @pytest.mark.asyncio
    async def test_run_review_with_issues(self):
        prompt = "Review this code"

        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm_instance = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = '{"summary": "Has issues", "issues": [{"severity": "WARNING", "file_line": "test.py:5", "issue": "Bug"}], "recommendation": "NEEDS_CHANGES"}'
            mock_llm_instance.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = (mock_llm_instance, {})

            result = await run_review(prompt)

            assert result.recommendation == "NEEDS_CHANGES"
            assert len(result.issues) == 1
            assert result.issues[0].severity == "WARNING"

    @pytest.mark.asyncio
    async def test_run_review_error(self):
        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm.side_effect = Exception("LLM unavailable")

            result = await run_review("Review")

            assert result.recommendation == "NEEDS_CHANGES"
            assert "failed" in result.summary.lower()
