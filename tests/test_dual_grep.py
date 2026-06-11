"""Tests for the Dual-Engine Grep system."""

import os
import tempfile
import pytest
from pathlib import Path

from nanocode.grep import (
    DualEngineGrep,
    GrepMatch,
    GrepResult,
    get_dual_engine_grep,
    reset_dual_engine_grep,
)


class TestGrepMatch:
    """Tests for GrepMatch dataclass."""

    def test_match_creation(self):
        """Test creating a match."""
        match = GrepMatch(
            file_path="/test/file.py",
            line_number=10,
            line_content="def hello():",
        )
        assert match.file_path == "/test/file.py"
        assert match.line_number == 10
        assert match.line_content == "def hello():"

    def test_match_with_positions(self):
        """Test match with positions."""
        match = GrepMatch(
            file_path="test.py",
            line_number=1,
            line_content="hello world",
            match_start=0,
            match_end=5,
        )
        assert match.match_start == 0
        assert match.match_end == 5


class TestGrepResult:
    """Tests for GrepResult dataclass."""

    def test_result_creation(self):
        """Test creating a result."""
        result = GrepResult()
        assert result.total_matches == 0
        assert result.engine_used == ""

    def test_result_with_error(self):
        """Test result with error."""
        result = GrepResult(error="Something went wrong")
        assert result.error == "Something went wrong"


class TestDualEngineGrep:
    """Tests for DualEngineGrep."""

    def test_init(self):
        """Test initialization."""
        grep = DualEngineGrep(max_results=100)
        assert grep.max_results == 100

    def test_is_ripgrep_available(self):
        """Test ripgrep availability check."""
        grep = DualEngineGrep()
        # Should return True or False without error
        result = grep.is_ripgrep_available()
        assert isinstance(result, bool)

    def test_search_empty_pattern(self, tmp_path):
        """Test search with empty pattern."""
        grep = DualEngineGrep()
        result = grep.search("", str(tmp_path))
        assert isinstance(result, GrepResult)

    def test_search_no_matches(self, tmp_path):
        """Test search with no matches."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("hello world\n")

        grep = DualEngineGrep()
        result = grep.search("nonexistent", str(tmp_path))
        assert result.total_matches == 0

    def test_search_with_matches(self, tmp_path):
        """Test search with matches."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    pass\n\ndef world():\n    pass\n")

        grep = DualEngineGrep()
        result = grep.search("def", str(tmp_path))
        assert result.total_matches == 2
        assert len(result.matches) == 2

    def test_search_case_insensitive(self, tmp_path):
        """Test case-insensitive search."""
        test_file = tmp_path / "test.py"
        test_file.write_text("Hello World\n")

        grep = DualEngineGrep()
        result = grep.search("hello", str(tmp_path), case_insensitive=True)
        assert result.total_matches == 1

    def test_search_literal(self, tmp_path):
        """Test literal search."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n")

        grep = DualEngineGrep()
        result = grep.search("def hello()", str(tmp_path), literal=True)
        assert result.total_matches == 1

    def test_search_regex(self, tmp_path):
        """Test regex search."""
        test_file = tmp_path / "test.py"
        test_file.write_text("test123\ntest456\nhello\n")

        grep = DualEngineGrep()
        result = grep.search(r"test\d+", str(tmp_path))
        assert result.total_matches == 2

    def test_search_whole_word(self, tmp_path):
        """Test whole word search."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def test():\ntesting\ntested\n")

        grep = DualEngineGrep()
        result = grep.search("test", str(tmp_path), whole_word=True)
        assert result.total_matches == 1

    def test_search_with_include(self, tmp_path):
        """Test search with include pattern."""
        (tmp_path / "test.py").write_text("hello\n")
        (tmp_path / "test.txt").write_text("hello\n")

        grep = DualEngineGrep()
        result = grep.search("hello", str(tmp_path), include="*.py")
        assert result.files_searched == 1

    def test_search_file_not_directory(self, tmp_path):
        """Test searching a specific file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("hello world\nhello again\n")

        grep = DualEngineGrep()
        result = grep.search("hello", str(test_file))
        assert result.total_matches == 2

    def test_looks_like_regex(self):
        """Test regex detection."""
        grep = DualEngineGrep()
        assert grep._looks_like_regex("test.*")
        assert grep._looks_like_regex("test+")
        assert grep._looks_like_regex("[abc]")
        assert not grep._looks_like_regex("hello")

    def test_engine_selection(self, tmp_path):
        """Test engine selection."""
        test_file = tmp_path / "test.py"
        test_file.write_text("hello\n")

        grep = DualEngineGrep()
        result = grep.search("hello", str(tmp_path))
        # Should use either ripgrep or python
        assert result.engine_used in ["ripgrep", "python", "python-regex-retry"]


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_dual_engine_grep_singleton(self):
        """Test global instance is singleton."""
        reset_dual_engine_grep()
        g1 = get_dual_engine_grep()
        g2 = get_dual_engine_grep()
        assert g1 is g2

    def test_reset_dual_engine_grep(self):
        """Test resetting global instance."""
        g1 = get_dual_engine_grep()
        reset_dual_engine_grep()
        g2 = get_dual_engine_grep()
        assert g1 is not g2
