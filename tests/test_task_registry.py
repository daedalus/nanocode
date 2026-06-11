"""Tests for the Task Registry."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from nanocode.planning.task_registry import (
    TaskRegistry,
    TaskStatus,
    TaskEventKind,
    TaskData,
    TaskEventData,
)


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    
    # Mock the result of execute to return a proper async iterator
    mock_result = AsyncMock()
    mock_result.fetchall = MagicMock(return_value=[])
    mock_result.scalars = MagicMock()
    mock_result.scalars.return_value = []
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute.return_value = mock_result
    
    return session


@pytest.fixture
def registry(mock_session):
    """Create a TaskRegistry with mock session."""
    return TaskRegistry(mock_session)


class TestTaskRegistry:
    """Tests for TaskRegistry."""

    def test_next_child_id_root(self, registry):
        """Test next child ID generation for root tasks."""
        assert registry._next_child_id(None, []) == "T1"
        assert registry._next_child_id(None, ["T1"]) == "T2"
        assert registry._next_child_id(None, ["T1", "T2"]) == "T3"

    def test_next_child_id_nested(self, registry):
        """Test next child ID generation for nested tasks."""
        assert registry._next_child_id("T1", []) == "T1.1"
        assert registry._next_child_id("T1", ["T1.1"]) == "T1.2"
        assert registry._next_child_id("T1", ["T1.1", "T1.2"]) == "T1.3"

    def test_to_task_data(self, registry):
        """Test conversion from SQLAlchemy Task to TaskData."""
        task = MagicMock()
        task.id = "T1"
        task.session_id = "session-123"
        task.parent_task_id = None
        task.status = "open"
        task.summary = "Test task"
        task.owner = None
        task.created_at = 1000000
        task.last_event_at = 1000000
        task.ended_at = None
        task.cleanup_after = None

        result = registry._to_task_data(task)

        assert result.id == "T1"
        assert result.session_id == "session-123"
        assert result.status == TaskStatus.OPEN
        assert result.summary == "Test task"

    def test_to_event_data(self, registry):
        """Test conversion from SQLAlchemy TaskEvent to TaskEventData."""
        event = MagicMock()
        event.id = 1
        event.task_id = "T1"
        event.at = 1000000
        event.kind = "created"
        event.summary = None

        result = registry._to_event_data(event)

        assert result.id == 1
        assert result.task_id == "T1"
        assert result.kind == TaskEventKind.CREATED

    @pytest.mark.asyncio
    async def test_create_task(self, registry, mock_session):
        """Test creating a new task."""
        # Mock the execute result for sibling query
        mock_result = AsyncMock()
        mock_result.fetchall = MagicMock(return_value=[])
        mock_session.execute.return_value = mock_result

        task = await registry.create(
            session_id="session-123",
            summary="Test task",
        )

        assert task.id == "T1"
        assert task.session_id == "session-123"
        assert task.status == TaskStatus.OPEN
        assert task.summary == "Test task"
        assert mock_session.add.call_count == 2  # Task + Event
        assert mock_session.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_create_nested_task(self, registry, mock_session):
        """Test creating a nested task."""
        # Mock siblings
        mock_result = AsyncMock()
        mock_result.fetchall = MagicMock(return_value=[("T1.1",)])
        mock_session.execute.return_value = mock_result

        task = await registry.create(
            session_id="session-123",
            summary="Subtask",
            parent_id="T1",
        )

        assert task.id == "T1.2"
        assert task.parent_task_id == "T1"

    @pytest.mark.asyncio
    async def test_start_task(self, registry, mock_session):
        """Test starting a task."""
        # Mock task retrieval
        mock_task = MagicMock()
        mock_task.status = "open"
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_task)
        mock_session.execute.return_value = mock_result

        task = await registry.start(
            session_id="session-123",
            task_id="T1",
        )

        assert mock_task.status == "in_progress"
        assert mock_session.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_start_terminal_task_fails(self, registry, mock_session):
        """Test that starting a terminal task fails."""
        mock_task = MagicMock()
        mock_task.status = "done"
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_task)
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Cannot start terminal task"):
            await registry.start(session_id="session-123", task_id="T1")

    @pytest.mark.asyncio
    async def test_block_task(self, registry, mock_session):
        """Test blocking a task."""
        mock_task = MagicMock()
        mock_task.status = "in_progress"
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_task)
        mock_session.execute.return_value = mock_result

        task = await registry.block(
            session_id="session-123",
            task_id="T1",
        )

        assert mock_task.status == "blocked"

    @pytest.mark.asyncio
    async def test_done_task(self, registry, mock_session):
        """Test completing a task."""
        mock_task = MagicMock()
        mock_task.status = "in_progress"
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_task)
        mock_session.execute.return_value = mock_result

        task = await registry.done(
            session_id="session-123",
            task_id="T1",
        )

        assert mock_task.status == "done"
        assert mock_task.ended_at is not None
        assert mock_task.cleanup_after is not None

    @pytest.mark.asyncio
    async def test_list_tasks(self, registry, mock_session):
        """Test listing tasks."""
        mock_task = MagicMock()
        mock_task.id = "T1"
        mock_task.session_id = "session-123"
        mock_task.parent_task_id = None
        mock_task.status = "open"
        mock_task.summary = "Test"
        mock_task.owner = None
        mock_task.created_at = 1000000
        mock_task.last_event_at = 1000000
        mock_task.ended_at = None
        mock_task.cleanup_after = None

        mock_result = AsyncMock()
        mock_result.scalars = MagicMock(return_value=[mock_task])
        mock_session.execute.return_value = mock_result

        tasks = await registry.list(session_id="session-123")

        assert len(tasks) == 1
        assert tasks[0].id == "T1"

    @pytest.mark.asyncio
    async def test_events(self, registry, mock_session):
        """Test getting task events."""
        mock_event = MagicMock()
        mock_event.id = 1
        mock_event.task_id = "T1"
        mock_event.at = 1000000
        mock_event.kind = "created"
        mock_event.summary = None

        mock_result = AsyncMock()
        mock_result.scalars = MagicMock(return_value=[mock_event])
        mock_session.execute.return_value = mock_result

        events = await registry.events(session_id="session-123", task_id="T1")

        assert len(events) == 1
        assert events[0].kind == TaskEventKind.CREATED
