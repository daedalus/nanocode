"""Tests for the Project Memory system."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanocode.memory.project_memory import (
    ProjectMemory,
    MemoryEntry,
    MemoryEntryType,
)


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    # Mock the result of execute to return a proper async iterator
    mock_result = AsyncMock()
    mock_result.fetchall = MagicMock(return_value=[])
    mock_result.fetchone = MagicMock(return_value=None)
    mock_result.lastrowid = 1
    mock_result.rowcount = 1
    session.execute.return_value = mock_result

    return session


@pytest.fixture
def project_memory(mock_session):
    """Create a ProjectMemory with mock session."""
    return ProjectMemory(mock_session)


class TestMemoryEntry:
    """Tests for MemoryEntry dataclass."""

    def test_entry_creation(self):
        """Test creating an entry."""
        entry = MemoryEntry(
            key="test-key",
            content="Test content",
            entry_type=MemoryEntryType.NOTE,
        )
        assert entry.key == "test-key"
        assert entry.content == "Test content"
        assert entry.entry_type == MemoryEntryType.NOTE

    def test_entry_to_dict(self):
        """Test converting entry to dict."""
        entry = MemoryEntry(
            key="test",
            content="content",
            entry_type=MemoryEntryType.DECISION,
        )
        d = entry.to_dict()
        assert d["key"] == "test"
        assert d["entry_type"] == "decision"

    def test_entry_types(self):
        """Test all entry types exist."""
        assert MemoryEntryType.TASK_COMPLETE
        assert MemoryEntryType.DECISION
        assert MemoryEntryType.LEARNING
        assert MemoryEntryType.ERROR
        assert MemoryEntryType.NOTE
        assert MemoryEntryType.ARCHITECTURE


class TestProjectMemory:
    """Tests for ProjectMemory."""

    @pytest.mark.asyncio
    async def test_initialize(self, project_memory, mock_session):
        """Test initialization creates tables."""
        await project_memory.initialize()
        assert project_memory._initialized is True
        assert mock_session.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_save_entry(self, project_memory, mock_session):
        """Test saving an entry."""
        await project_memory.initialize()

        entry = MemoryEntry(
            key="test",
            content="content",
            entry_type=MemoryEntryType.NOTE,
        )

        entry_id = await project_memory.save_entry(entry)
        assert entry_id == 1

    @pytest.mark.asyncio
    async def test_save_task_complete(self, project_memory, mock_session):
        """Test saving a completed task."""
        await project_memory.initialize()

        entry_id = await project_memory.save_task_complete(
            task_id="T1",
            summary="Implement feature",
            details="Added new functionality",
        )
        assert entry_id == 1

    @pytest.mark.asyncio
    async def test_save_decision(self, project_memory, mock_session):
        """Test saving a decision."""
        await project_memory.initialize()

        entry_id = await project_memory.save_decision(
            key="use-async",
            decision="Use async/await for all I/O",
            rationale="Better performance",
        )
        assert entry_id == 1

    @pytest.mark.asyncio
    async def test_save_learning(self, project_memory, mock_session):
        """Test saving a learning."""
        await project_memory.initialize()

        entry_id = await project_memory.save_learning(
            key="fts5-setup",
            learning="FTS5 requires virtual table creation",
        )
        assert entry_id == 1

    @pytest.mark.asyncio
    async def test_save_error(self, project_memory, mock_session):
        """Test saving an error."""
        await project_memory.initialize()

        entry_id = await project_memory.save_error(
            key="import-error",
            error="ModuleNotFoundError",
            solution="Install the package",
        )
        assert entry_id == 1

    @pytest.mark.asyncio
    async def test_get_entry(self, project_memory, mock_session):
        """Test getting an entry."""
        await project_memory.initialize()

        # Mock return value
        mock_result = AsyncMock()
        mock_result.fetchone = MagicMock(
            return_value=(1, "test", "content", "note", "project", None, "{}", 1234567890.0, 1234567890.0)
        )
        mock_session.execute.return_value = mock_result

        entry = await project_memory.get_entry(1)
        assert entry is not None
        assert entry.key == "test"

    @pytest.mark.asyncio
    async def test_search(self, project_memory, mock_session):
        """Test searching entries."""
        await project_memory.initialize()

        entries = await project_memory.search("test query")
        assert isinstance(entries, list)

    @pytest.mark.asyncio
    async def test_list_entries(self, project_memory, mock_session):
        """Test listing entries."""
        await project_memory.initialize()

        entries = await project_memory.list_entries()
        assert isinstance(entries, list)

    @pytest.mark.asyncio
    async def test_delete_entry(self, project_memory, mock_session):
        """Test deleting an entry."""
        await project_memory.initialize()

        result = await project_memory.delete_entry(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_stats(self, project_memory, mock_session):
        """Test getting statistics."""
        await project_memory.initialize()

        # Mock stats result
        mock_result = AsyncMock()
        mock_result.fetchall = MagicMock(
            return_value=[("note", 5), ("decision", 3)]
        )
        mock_session.execute.return_value = mock_result

        stats = await project_memory.get_stats()
        assert "total_entries" in stats
        assert "by_type" in stats
