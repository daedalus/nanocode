"""Tests for session summary generation."""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from nanocode.session_summary import (
    SessionSummary,
    SessionSummaryGenerator,
    FileChange,
    SUMMARY_PROMPT,
)


class TestFileChange:
    """Tests for FileChange dataclass."""

    def test_creation(self):
        """Test creating a FileChange."""
        change = FileChange(file="test.py", additions=10, deletions=5)
        assert change.file == "test.py"
        assert change.additions == 10
        assert change.deletions == 5


class TestSessionSummary:
    """Tests for SessionSummary."""

    def test_default_creation(self):
        """Test default SessionSummary."""
        summary = SessionSummary()
        assert summary.additions == 0
        assert summary.deletions == 0
        assert summary.files == 0
        assert summary.text == ""
        assert summary.diffs == []

    def test_custom_creation(self):
        """Test creating with values."""
        diffs = [FileChange(file="a.py", additions=5, deletions=2)]
        summary = SessionSummary(
            additions=10,
            deletions=5,
            files=3,
            text="Fixed bugs",
            diffs=diffs,
        )
        assert summary.additions == 10
        assert summary.deletions == 5
        assert summary.files == 3
        assert summary.text == "Fixed bugs"
        assert len(summary.diffs) == 1

    def test_additions_and_deletions(self):
        """Test additions and deletions."""
        summary = SessionSummary(additions=10, deletions=5)
        assert summary.additions == 10
        assert summary.deletions == 5


class TestSessionSummaryGenerator:
    """Tests for SessionSummaryGenerator."""

    def test_creation(self):
        """Test creating generator."""
        llm = Mock()
        generator = SessionSummaryGenerator(llm)
        assert generator.llm is llm
        assert generator.storage is None

    def test_creation_with_storage(self):
        """Test creating with storage."""
        llm = Mock()
        storage = Mock()
        generator = SessionSummaryGenerator(llm, storage)
        assert generator.storage is storage


class TestSummaryPrompt:
    """Tests for SUMMARY_PROMPT."""

    def test_prompt_exists(self):
        """Test summary prompt exists."""
        assert SUMMARY_PROMPT is not None
        assert len(SUMMARY_PROMPT) > 0

    def test_prompt_contains_rules(self):
        """Test prompt contains rules."""
        assert "Rules:" in SUMMARY_PROMPT

    def test_prompt_contains_format(self):
        """Test prompt contains format info."""
        assert "pull request" in SUMMARY_PROMPT.lower()