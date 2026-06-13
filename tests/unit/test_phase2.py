"""Tests for Phase 2 features: checkpoint context injection, task progress reconciliation."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


class TestCheckpointContextInjection:
    """Tests for ContextReconstructor.render_rebuild_context."""

    def test_render_rebuild_context_returns_empty_when_no_files(self, tmp_path):
        """Test that render_rebuild_context returns empty when no checkpoint files exist."""
        from nanocode.context import ContextReconstructor, CheckpointManager

        manager = CheckpointManager(storage_dir=str(tmp_path / "checkpoints"))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=8000,
        )

        result = reconstructor.render_rebuild_context(
            session_id="test-session",
            project_id="test-project",
            data_dir=str(tmp_path),
        )

        assert result == ""

    def test_render_rebuild_context_includes_checkpoint(self, tmp_path):
        """Test that render_rebuild_context includes checkpoint content."""
        from nanocode.context import ContextReconstructor, CheckpointManager

        # Create checkpoint file
        session_dir = tmp_path / "memory" / "sessions" / "test-session"
        session_dir.mkdir(parents=True)
        checkpoint_file = session_dir / "checkpoint.md"
        checkpoint_file.write_text("# Session checkpoint\n\n## §1 Active intent\n\nTest content")

        manager = CheckpointManager(storage_dir=str(tmp_path / "checkpoints"))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=8000,
        )

        result = reconstructor.render_rebuild_context(
            session_id="test-session",
            project_id="test-project",
            data_dir=str(tmp_path),
        )

        assert "Session checkpoint" in result
        assert "Active intent" in result

    def test_render_rebuild_context_includes_memory(self, tmp_path):
        """Test that render_rebuild_context includes MEMORY.md content."""
        from nanocode.context import ContextReconstructor, CheckpointManager

        # Create memory file
        memory_dir = tmp_path / "memory" / "projects" / "test-project"
        memory_dir.mkdir(parents=True)
        memory_file = memory_dir / "MEMORY.md"
        memory_file.write_text("# Project memory\n\n## Rules\n\nTest rule")

        manager = CheckpointManager(storage_dir=str(tmp_path / "checkpoints"))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=8000,
        )

        result = reconstructor.render_rebuild_context(
            session_id="test-session",
            project_id="test-project",
            data_dir=str(tmp_path),
        )

        assert "Project memory" in result
        assert "Rules" in result

    def test_render_rebuild_context_includes_notes(self, tmp_path):
        """Test that render_rebuild_context includes notes.md content."""
        from nanocode.context import ContextReconstructor, CheckpointManager

        # Create notes file
        session_dir = tmp_path / "memory" / "sessions" / "test-session"
        session_dir.mkdir(parents=True)
        notes_file = session_dir / "notes.md"
        notes_file.write_text("# Session notes\n\nSome notes here")

        manager = CheckpointManager(storage_dir=str(tmp_path / "checkpoints"))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=8000,
        )

        result = reconstructor.render_rebuild_context(
            session_id="test-session",
            project_id="test-project",
            data_dir=str(tmp_path),
        )

        assert "Session notes" in result
        assert "Some notes here" in result

    def test_render_rebuild_context_has_already_loaded_header(self, tmp_path):
        """Test that render_rebuild_context includes 'Already loaded' header."""
        from nanocode.context import ContextReconstructor, CheckpointManager

        # Create checkpoint file
        session_dir = tmp_path / "memory" / "sessions" / "test-session"
        session_dir.mkdir(parents=True)
        checkpoint_file = session_dir / "checkpoint.md"
        checkpoint_file.write_text("# Session checkpoint\n\nContent")

        manager = CheckpointManager(storage_dir=str(tmp_path / "checkpoints"))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=8000,
        )

        result = reconstructor.render_rebuild_context(
            session_id="test-session",
            project_id="test-project",
            data_dir=str(tmp_path),
        )

        assert "already in your context" in result

    def test_render_rebuild_context_respects_caps(self, tmp_path):
        """Test that render_rebuild_context respects token budget caps."""
        from nanocode.context import ContextReconstructor, CheckpointManager

        # Create large checkpoint file
        session_dir = tmp_path / "memory" / "sessions" / "test-session"
        session_dir.mkdir(parents=True)
        checkpoint_file = session_dir / "checkpoint.md"
        checkpoint_file.write_text("# Session checkpoint\n\n" + "x " * 10000)

        manager = CheckpointManager(storage_dir=str(tmp_path / "checkpoints"))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=8000,
        )

        result = reconstructor.render_rebuild_context(
            session_id="test-session",
            project_id="test-project",
            data_dir=str(tmp_path),
            caps={"checkpoint": 100, "memory": 100, "notes": 100},
        )

        # Should be truncated
        assert "Warning" in result or "Truncated" in result


class TestTaskProgressReconciliation:
    """Tests for TaskRegistry progress methods."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def registry(self, mock_session):
        """Create a TaskRegistry with mock session."""
        from nanocode.planning.task_registry import TaskRegistry

        return TaskRegistry(mock_session)

    def test_progress_path_generation(self):
        """Test that progress_path generates correct paths."""
        from nanocode.checkpoint import progress_path

        path = progress_path("session-123", "T1", "/tmp/data")
        assert path == Path("/tmp/data/memory/sessions/session-123/tasks/T1/progress.md")

    def test_progress_path_nested_task(self):
        """Test progress_path for nested tasks."""
        from nanocode.checkpoint import progress_path

        path = progress_path("session-123", "T1.1", "/tmp/data")
        assert path == Path("/tmp/data/memory/sessions/session-123/tasks/T1.1/progress.md")

    def test_write_progress_creates_file(self, tmp_path):
        """Test that write_progress creates the progress file."""
        from nanocode.planning.task_registry import TaskRegistry

        session = AsyncMock()
        registry = TaskRegistry(session)

        # Run the async method
        import asyncio

        path = asyncio.run(
            registry.write_progress(
                session_id="test-session",
                task_id="T1",
                content="# Progress\n\nWorking on feature X",
                data_dir=str(tmp_path),
            )
        )

        assert Path(path).exists()
        assert Path(path).read_text() == "# Progress\n\nWorking on feature X"

    def test_read_progress_returns_content(self, tmp_path):
        """Test that read_progress returns file content."""
        from nanocode.planning.task_registry import TaskRegistry

        # Create progress file
        session_dir = tmp_path / "memory" / "sessions" / "test-session" / "tasks" / "T1"
        session_dir.mkdir(parents=True)
        progress_file = session_dir / "progress.md"
        progress_file.write_text("# Progress\n\nStep 1 complete")

        session = AsyncMock()
        registry = TaskRegistry(session)

        import asyncio

        content = asyncio.run(
            registry.read_progress(
                session_id="test-session",
                task_id="T1",
                data_dir=str(tmp_path),
            )
        )

        assert content == "# Progress\n\nStep 1 complete"

    def test_read_progress_returns_none_when_missing(self, tmp_path):
        """Test that read_progress returns None when file doesn't exist."""
        from nanocode.planning.task_registry import TaskRegistry

        session = AsyncMock()
        registry = TaskRegistry(session)

        import asyncio

        content = asyncio.run(
            registry.read_progress(
                session_id="test-session",
                task_id="T1",
                data_dir=str(tmp_path),
            )
        )

        assert content is None

    def test_render_task_ledger_empty(self):
        """Test render_task_ledger with no tasks."""
        from nanocode.planning.task_registry import TaskRegistry

        session = AsyncMock()
        session.execute = AsyncMock()
        session.execute.return_value.fetchall.return_value = []
        session.execute.return_value.scalars.return_value = []

        registry = TaskRegistry(session)

        import asyncio

        # Mock the list method to return empty
        with patch.object(registry, "list", return_value=[]):
            result = asyncio.run(
                registry.render_task_ledger(session_id="test-session")
            )

        assert result == "(none)"
