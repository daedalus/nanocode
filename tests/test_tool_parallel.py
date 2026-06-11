"""Tests for the Tool Parallelism module."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanocode.tools.parallel import (
    ToolParallelismManager,
    ToolAccessMode,
    ToolClassification,
    get_parallelism_manager,
    reset_parallelism_manager,
    DEFAULT_READ_TOOLS,
    DEFAULT_WRITE_TOOLS,
)


class TestToolClassification:
    """Tests for ToolClassification."""

    def test_read_classification(self):
        """Test read-only classification."""
        classification = ToolClassification(
            name="read",
            mode=ToolAccessMode.READ,
            is_read_only=True,
        )
        assert classification.can_parallel is True
        assert classification.is_read_only is True

    def test_write_classification(self):
        """Test write classification."""
        classification = ToolClassification(
            name="write",
            mode=ToolAccessMode.WRITE,
            is_read_only=False,
        )
        assert classification.can_parallel is False
        assert classification.is_read_only is False


class TestToolParallelismManager:
    """Tests for ToolParallelismManager."""

    def test_init_default(self):
        """Test default initialization."""
        manager = ToolParallelismManager()
        assert len(manager.read_tools) > 0
        assert len(manager.write_tools) > 0
        assert manager.max_concurrency == 10

    def test_classify_read_tool(self):
        """Test classifying read-only tools."""
        manager = ToolParallelismManager()

        classification = manager.classify_tool("read")
        assert classification.mode == ToolAccessMode.READ
        assert classification.can_parallel is True

        classification = manager.classify_tool("grep")
        assert classification.mode == ToolAccessMode.READ

        classification = manager.classify_tool("glob")
        assert classification.mode == ToolAccessMode.READ

    def test_classify_write_tool(self):
        """Test classifying write tools."""
        manager = ToolParallelismManager()

        classification = manager.classify_tool("write")
        assert classification.mode == ToolAccessMode.WRITE
        assert classification.can_parallel is False

        classification = manager.classify_tool("edit")
        assert classification.mode == ToolAccessMode.WRITE

        classification = manager.classify_tool("bash")
        assert classification.mode == ToolAccessMode.WRITE

    def test_classify_unknown_tool_default_write(self):
        """Test unknown tools default to write (conservative)."""
        manager = ToolParallelismManager()

        classification = manager.classify_tool("unknown_tool_xyz")
        assert classification.mode == ToolAccessMode.WRITE

    def test_classify_tools_splits_correctly(self):
        """Test classify_tools splits into read and write."""
        manager = ToolParallelismManager()

        tool_calls = [
            ("read", {"path": "file1.py"}),
            ("write", {"path": "file2.py", "content": "x"}),
            ("grep", {"pattern": "test"}),
            ("edit", {"path": "file3.py"}),
            ("glob", {"pattern": "*.py"}),
        ]

        read_calls, write_calls = manager.classify_tools(tool_calls)

        assert len(read_calls) == 3  # read, grep, glob
        assert len(write_calls) == 2  # write, edit

    def test_caching_classifications(self):
        """Test that classifications are cached."""
        manager = ToolParallelismManager()

        c1 = manager.classify_tool("read")
        c2 = manager.classify_tool("read")

        assert c1 is c2
        assert "read" in manager._classifications

    def test_add_read_tool(self):
        """Test adding a tool to read list."""
        manager = ToolParallelismManager()

        manager.add_read_tool("custom_read_tool")
        assert "custom_read_tool" in manager.read_tools
        assert "custom_read_tool" not in manager.write_tools

    def test_add_write_tool(self):
        """Test adding a tool to write list."""
        manager = ToolParallelismManager()

        manager.add_write_tool("custom_write_tool")
        assert "custom_write_tool" in manager.write_tools
        assert "custom_write_tool" not in manager.read_tools

    def test_get_stats(self):
        """Test getting stats."""
        manager = ToolParallelismManager()
        stats = manager.get_stats()

        assert "read_tools" in stats
        assert "write_tools" in stats
        assert "max_concurrency" in stats
        assert stats["read_tools"] > 0
        assert stats["write_tools"] > 0


class TestGlobalManager:
    """Tests for global manager."""

    def test_get_parallelism_manager_singleton(self):
        """Test global manager is singleton."""
        reset_parallelism_manager()
        m1 = get_parallelism_manager()
        m2 = get_parallelism_manager()
        assert m1 is m2

    def test_reset_parallelism_manager(self):
        """Test resetting global manager."""
        m1 = get_parallelism_manager()
        reset_parallelism_manager()
        m2 = get_parallelism_manager()
        assert m1 is not m2


class TestDefaultTools:
    """Tests for default tool lists."""

    def test_read_tools_not_empty(self):
        """Test read tools list is not empty."""
        assert len(DEFAULT_READ_TOOLS) > 0

    def test_write_tools_not_empty(self):
        """Test write tools list is not empty."""
        assert len(DEFAULT_WRITE_TOOLS) > 0

    def test_no_overlap(self):
        """Test read and write tools don't overlap."""
        overlap = DEFAULT_READ_TOOLS & DEFAULT_WRITE_TOOLS
        assert len(overlap) == 0, f"Overlapping tools: {overlap}"

    def test_core_read_tools_present(self):
        """Test core read tools are present."""
        core_reads = {"read", "grep", "glob", "find_usages"}
        assert core_reads.issubset(DEFAULT_READ_TOOLS)

    def test_core_write_tools_present(self):
        """Test core write tools are present."""
        core_writes = {"write", "edit", "bash"}
        assert core_writes.issubset(DEFAULT_WRITE_TOOLS)
