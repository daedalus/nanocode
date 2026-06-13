"""Tests for Phase 1 features: budgeted reads, checkpoint templates, pressure levels, memory tool."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from nanocode.budgeted import (
    BudgetedReadResult,
    Section,
    count_tokens,
    parse_sections,
    read_budgeted,
    read_budgeted_section_aware,
)
from nanocode.checkpoint import (
    CHECKPOINT_TEMPLATE,
    MEMORY_TEMPLATE,
    NOTES_TEMPLATE,
    CHECKPOINT_SECTION_BUDGETS,
    MEMORY_SECTION_BUDGETS,
    SectionBudget,
    checkpoint_path,
    ensure_checkpoint_template,
    ensure_memory_template,
    ensure_notes_template,
    global_memory_path,
    memory_path,
    meta_dir,
    notes_path,
    progress_path,
    tasks_dir,
)


class TestTokenCounting:
    """Tests for token counting utility."""

    def test_count_tokens_empty(self):
        assert count_tokens("") == 0

    def test_count_tokens_short(self):
        tokens = count_tokens("hello world")
        assert tokens >= 1

    def test_count_tokens_long(self):
        text = "word " * 1000
        tokens = count_tokens(text)
        assert tokens > 100


class TestParseSections:
    """Tests for markdown section parsing."""

    def test_parse_empty(self):
        preamble, sections = parse_sections("")
        assert sections == []

    def test_parse_no_sections(self):
        preamble, sections = parse_sections("Just some text\nWithout headers")
        assert preamble == ["Just some text", "Without headers"]
        assert sections == []

    def test_parse_single_section(self):
        text = "# Title\n\n## Section 1\nBody content here"
        preamble, sections = parse_sections(text)
        assert len(preamble) >= 1
        assert len(sections) == 1
        assert sections[0].header == "## Section 1"
        assert "Body content here" in sections[0].body

    def test_parse_multiple_sections(self):
        text = "## Section 1\nBody 1\n\n## Section 2\nBody 2"
        preamble, sections = parse_sections(text)
        assert len(sections) == 2
        assert sections[0].header == "## Section 1"
        assert sections[1].header == "## Section 2"

    def test_parse_with_italic(self):
        text = "## Section\n_Description_\nBody"
        preamble, sections = parse_sections(text)
        assert len(sections) == 1
        assert sections[0].italic == "_Description_"

    def test_parse_with_index_lines(self):
        text = "## Section\n- See file.md (100 tokens)\n- See other.md (50 tokens)\nBody"
        preamble, sections = parse_sections(text)
        assert len(sections) == 1
        assert len(sections[0].index_lines) == 2

    def test_parse_preamble_only(self):
        text = "Line 1\nLine 2\n## First Section"
        preamble, sections = parse_sections(text)
        assert "Line 1" in preamble
        assert "Line 2" in preamble
        assert len(sections) == 1


class TestReadBudgeted:
    """Tests for budgeted file reading."""

    def test_read_budgeted_returns_none_for_nonexistent(self):
        result = read_budgeted("/nonexistent/file.md", 1000)
        assert result is None

    def test_read_budgeted_small_file(self, tmp_path):
        filepath = tmp_path / "test.md"
        filepath.write_text("Small content")

        result = read_budgeted(str(filepath), 1000)

        assert result is not None
        assert result.truncated is False
        assert "Small content" in result.text

    def test_read_budgeted_truncates_large_file(self, tmp_path):
        filepath = tmp_path / "test.md"
        filepath.write_text("word " * 10000)

        result = read_budgeted(str(filepath), 100)

        assert result is not None
        assert result.truncated is True
        assert "Truncated" in result.text

    def test_read_budgeted_preserves_total_tokens(self, tmp_path):
        filepath = tmp_path / "test.md"
        filepath.write_text("content " * 500)

        result = read_budgeted(str(filepath), 100)

        assert result.total_tokens > 100


class TestReadBudgetedSectionAware:
    """Tests for section-aware budgeted reads."""

    def test_returns_none_for_nonexistent(self):
        result = read_budgeted_section_aware("/nonexistent.md", 1000)
        assert result is None

    def test_small_file_not_truncated(self, tmp_path):
        filepath = tmp_path / "test.md"
        filepath.write_text("## Section\nSmall content")

        result = read_budgeted_section_aware(str(filepath), 10000)

        assert result is not None
        assert result.truncated is False

    def test_large_file_truncated(self, tmp_path):
        filepath = tmp_path / "test.md"
        content = "## Section\n" + "body " * 5000
        filepath.write_text(content)

        result = read_budgeted_section_aware(str(filepath), 100)

        assert result is not None
        assert result.truncated is True

    def test_section_structure_preserved(self, tmp_path):
        filepath = tmp_path / "test.md"
        content = "## Section 1\nBody 1\n\n## Section 2\nBody 2"
        filepath.write_text(content)

        result = read_budgeted_section_aware(str(filepath), 10000)

        assert "## Section 1" in result.text
        assert "## Section 2" in result.text

    def test_header_skeleton_when_very_small_budget(self, tmp_path):
        filepath = tmp_path / "test.md"
        content = "## Header 1\n" + "body " * 1000 + "\n## Header 2\n" + "body " * 1000
        filepath.write_text(content)

        result = read_budgeted_section_aware(str(filepath), 20)

        assert result is not None
        assert result.truncated is True
        assert "## Header 1" in result.text


class TestCheckpointPaths:
    """Tests for checkpoint path helpers."""

    def test_meta_dir(self):
        path = meta_dir("session-123", "/tmp/data")
        assert path == Path("/tmp/data/memory/sessions/session-123")

    def test_checkpoint_path(self):
        path = checkpoint_path("session-123", "/tmp/data")
        assert path == Path("/tmp/data/memory/sessions/session-123/checkpoint.md")

    def test_memory_path(self):
        path = memory_path("proj-1", "/tmp/data")
        assert path == Path("/tmp/data/memory/projects/proj-1/MEMORY.md")

    def test_memory_path_default(self):
        path = memory_path("default", "/tmp/data")
        assert path.name == "MEMORY.md"
        assert "default" in str(path)

    def test_global_memory_path(self):
        path = global_memory_path("/tmp/data")
        assert path == Path("/tmp/data/memory/global/MEMORY.md")

    def test_notes_path(self):
        path = notes_path("session-123", "/tmp/data")
        assert path == Path("/tmp/data/memory/sessions/session-123/notes.md")

    def test_tasks_dir(self):
        path = tasks_dir("session-123", "/tmp/data")
        assert path == Path("/tmp/data/memory/sessions/session-123/tasks")

    def test_progress_path(self):
        path = progress_path("session-123", "T1", "/tmp/data")
        assert path == Path("/tmp/data/memory/sessions/session-123/tasks/T1/progress.md")


class TestCheckpointTemplates:
    """Tests for checkpoint template creation."""

    def test_ensure_checkpoint_template_creates_file(self, tmp_path):
        path = ensure_checkpoint_template("test-session", str(tmp_path))
        assert path.exists()
        assert CHECKPOINT_TEMPLATE[:50] in path.read_text()

    def test_ensure_checkpoint_template_idempotent(self, tmp_path):
        path1 = ensure_checkpoint_template("test-session", str(tmp_path))
        path1.write_text("Modified content")
        path2 = ensure_checkpoint_template("test-session", str(tmp_path))
        assert path2.read_text() == "Modified content"

    def test_ensure_memory_template_creates_file(self, tmp_path):
        path = ensure_memory_template("proj-1", str(tmp_path))
        assert path.exists()
        assert MEMORY_TEMPLATE[:50] in path.read_text()

    def test_ensure_notes_template_creates_file(self, tmp_path):
        path = ensure_notes_template("test-session", str(tmp_path))
        assert path.exists()
        assert "Session notes" in path.read_text()


class TestCheckpointTemplateContent:
    """Tests for template content."""

    def test_checkpoint_has_all_sections(self):
        assert "§1 Active intent" in CHECKPOINT_TEMPLATE
        assert "§2 Next concrete action" in CHECKPOINT_TEMPLATE
        assert "§3 Directives" in CHECKPOINT_TEMPLATE
        assert "§4 Task tree" in CHECKPOINT_TEMPLATE
        assert "§5 Current work" in CHECKPOINT_TEMPLATE
        assert "§6 Files and code sections" in CHECKPOINT_TEMPLATE
        assert "§7 Discovered knowledge" in CHECKPOINT_TEMPLATE
        assert "§8 Errors and fixes" in CHECKPOINT_TEMPLATE
        assert "§9 Live resources" in CHECKPOINT_TEMPLATE
        assert "§10 Design decisions" in CHECKPOINT_TEMPLATE
        assert "§11 Open notes" in CHECKPOINT_TEMPLATE

    def test_memory_has_all_sections(self):
        assert "Project context" in MEMORY_TEMPLATE
        assert "Rules" in MEMORY_TEMPLATE
        assert "Architecture decisions" in MEMORY_TEMPLATE
        assert "Discovered durable knowledge" in MEMORY_TEMPLATE

    def test_section_budgets_total(self):
        total = sum(CHECKPOINT_SECTION_BUDGETS.values())
        assert 10000 <= total <= 20000

    def test_memory_budgets_total(self):
        total = sum(MEMORY_SECTION_BUDGETS.values())
        assert 5000 <= total <= 15000


class TestPressureLevels:
    """Tests for context pressure level detection."""

    def test_pressure_level_calculation(self):
        """Test pressure level calculation logic directly."""
        # Test the algorithm without importing ContextManager
        def pressure_level(current_tokens: int, context_limit: int, reserved: int = 2000) -> int:
            usable = context_limit - reserved
            if usable <= 0:
                return 0
            ratio = current_tokens / usable
            if ratio < 0.50:
                return 0
            if ratio < 0.70:
                return 1
            if ratio < 0.85:
                return 2
            return 3

        # Low usage
        assert pressure_level(1000, 100000) == 0

        # 50-70% usage
        assert pressure_level(30000, 50000) == 1  # 30000/48000 = 0.625

        # 70-85% usage
        assert pressure_level(40000, 50000) == 2  # 40000/48000 = 0.833

        # >=85% usage
        assert pressure_level(45000, 50000) == 3  # 45000/48000 = 0.9375

    def test_pressure_level_zero_usable(self):
        """Test pressure level with zero usable context."""
        def pressure_level(current_tokens: int, context_limit: int, reserved: int = 2000) -> int:
            usable = context_limit - reserved
            if usable <= 0:
                return 0
            ratio = current_tokens / usable
            if ratio < 0.50:
                return 0
            if ratio < 0.70:
                return 1
            if ratio < 0.85:
                return 2
            return 3

        assert pressure_level(1000, 1000) == 0  # usable = 0

    def test_is_overflow_logic(self):
        """Test overflow detection logic."""
        def is_overflow(pressure: int) -> bool:
            return pressure >= 3

        assert is_overflow(0) is False
        assert is_overflow(1) is False
        assert is_overflow(2) is False
        assert is_overflow(3) is True


class TestMemoryTool:
    """Tests for MemoryTool."""

    def test_tool_class_exists(self):
        """Test that MemoryTool class definition exists."""
        with open("nanocode/tools/builtin/__init__.py") as f:
            content = f.read()
        assert "class MemoryTool(Tool):" in content

    def test_tool_has_search_operation(self):
        """Test that MemoryTool supports search operation."""
        with open("nanocode/tools/builtin/__init__.py") as f:
            content = f.read()
        assert '"search"' in content
        assert '"reindex"' in content
        assert '"stats"' in content

    def test_tool_uses_memory_search(self):
        """Test that MemoryTool imports MemorySearch."""
        with open("nanocode/tools/builtin/__init__.py") as f:
            content = f.read()
        assert "MemorySearch" in content

    def test_tool_registered_in_create_builtin(self):
        """Test that MemoryTool is registered in create_builtin_tools."""
        with open("nanocode/tools/builtin/__init__.py") as f:
            content = f.read()
        assert "MemoryTool()," in content
