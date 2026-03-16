"""Tests for session summary feature."""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from agent_smith.session_summary import (
    SessionSummaryGenerator,
    SessionSummary,
    FileChange,
    SUMMARY_PROMPT,
)


class TestFileChange:
    """Tests for FileChange dataclass."""

    def test_file_change_creation(self):
        """Test creating a FileChange."""
        change = FileChange(file="src/main.py", additions=10, deletions=5)
        assert change.file == "src/main.py"
        assert change.additions == 10
        assert change.deletions == 5


class TestSessionSummary:
    """Tests for SessionSummary dataclass."""

    def test_session_summary_creation(self):
        """Test creating a SessionSummary."""
        summary = SessionSummary(
            additions=100,
            deletions=50,
            files=5,
            text="Added new feature",
        )
        assert summary.additions == 100
        assert summary.deletions == 50
        assert summary.files == 5
        assert summary.text == "Added new feature"
        assert summary.diffs == []

    def test_session_summary_defaults(self):
        """Test SessionSummary default values."""
        summary = SessionSummary()
        assert summary.additions == 0
        assert summary.deletions == 0
        assert summary.files == 0
        assert summary.text == ""
        assert summary.diffs == []


class TestSessionSummaryGenerator:
    """Tests for SessionSummaryGenerator."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = Mock()
        llm.chat = AsyncMock()
        mock_response = Mock()
        mock_response.content = "I added a new feature to the project."
        llm.chat.return_value = mock_response
        return llm

    def test_summary_prompt_format(self):
        """Test that SUMMARY_PROMPT follows PR description format."""
        assert "2-3 sentences max" in SUMMARY_PROMPT
        assert "Write in first person" in SUMMARY_PROMPT
        assert "I added" in SUMMARY_PROMPT or "I fixed" in SUMMARY_PROMPT

    @pytest.mark.asyncio
    async def test_generate_text_summary(self, mock_llm):
        """Test generating text summary from messages."""
        generator = SessionSummaryGenerator(mock_llm)

        messages = [
            {"role": "user", "content": "Add a new feature to the project"},
            {"role": "assistant", "content": "I'll add a new feature"},
        ]

        summary = await generator._generate_text_summary(messages)

        assert mock_llm.chat.called

    @pytest.mark.asyncio
    async def test_generate_text_summary_empty_messages(self, mock_llm):
        """Test generating summary with empty messages."""
        generator = SessionSummaryGenerator(mock_llm)

        summary = await generator._generate_text_summary([])

        assert summary == ""

    @pytest.mark.asyncio
    async def test_generate_text_summary_handles_error(self, mock_llm):
        """Test that _generate_text_summary handles LLM errors gracefully."""
        mock_llm.chat.side_effect = Exception("API Error")

        generator = SessionSummaryGenerator(mock_llm)

        messages = [{"role": "user", "content": "Test"}]

        summary = await generator._generate_text_summary(messages)

        assert summary == ""

    @pytest.mark.asyncio
    async def test_summarize_no_llm(self):
        """Test summarize without LLM - only computes diffs."""
        generator = SessionSummaryGenerator(None)

        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "src/main.py\t10 additions, 5 deletions"
            mock_run.return_value = mock_result

            summary = await generator.summarize([])

            assert summary.additions >= 0
            assert summary.diffs is not None

    @pytest.mark.asyncio
    async def test_compute_diffs_no_git(self):
        """Test compute_diffs when not in a git repo."""
        generator = SessionSummaryGenerator(None)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")

            diffs = await generator._compute_diffs()

            assert diffs == []

    @pytest.mark.asyncio
    async def test_compute_diffs_handles_timeout(self):
        """Test compute_diffs handles timeout gracefully."""
        import subprocess

        generator = SessionSummaryGenerator(None)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git diff", 10)

            diffs = await generator._compute_diffs()

            assert diffs == []


class TestSessionSummaryIntegration:
    """Integration tests for session summary."""

    @pytest.mark.asyncio
    async def test_summarize_with_messages_and_tool_results(self):
        """Test full summarize with messages and tool results."""
        mock_llm = Mock()
        mock_llm.chat = AsyncMock()
        mock_response = Mock()
        mock_response.content = "Test summary"
        mock_llm.chat.return_value = mock_response

        generator = SessionSummaryGenerator(mock_llm)

        messages = [
            {"role": "user", "content": "Fix the bug in main.py"},
            {"role": "assistant", "content": "I'll fix that bug"},
        ]

        tool_results = [
            {"tool": "read", "result": "file content"},
            {"tool": "edit", "result": "file edited"},
        ]

        with patch.object(generator, "_compute_diffs", return_value=[]):
            summary = await generator.summarize(messages, tool_results)

            assert summary.text == "Test summary"
            assert mock_llm.chat.called

    def test_summary_prompt_rules(self):
        """Test that summary prompt has all required rules."""
        assert "Do not mention running tests" in SUMMARY_PROMPT
        assert "Do not explain what the user asked for" in SUMMARY_PROMPT
        assert "Never ask questions" in SUMMARY_PROMPT
        assert "If the conversation ends with an unanswered question" in SUMMARY_PROMPT


class TestFileChangeParsing:
    """Tests for parsing file changes from git diff."""

    @pytest.mark.asyncio
    async def test_parse_git_diff_stat(self):
        """Test parsing git diff --stat output."""
        generator = SessionSummaryGenerator(None)

        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = """src/main.py           | 10 ++---
src/utils.py         |  5 +++
2 files changed, 10 insertions(+), 5 deletions(-)"""
            mock_run.return_value = mock_result

            diffs = await generator._compute_diffs()

            assert len(diffs) == 2
            assert any(d.file == "src/main.py" for d in diffs)
            assert any(d.file == "src/utils.py" for d in diffs)

    @pytest.mark.asyncio
    async def test_parse_git_diff_no_changes(self):
        """Test parsing git diff with no changes."""
        generator = SessionSummaryGenerator(None)

        with patch("subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            diffs = await generator._compute_diffs()

            assert diffs == []
