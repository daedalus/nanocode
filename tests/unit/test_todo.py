"""Tests for TodoService."""

import pytest
import tempfile
from pathlib import Path

from nanocode.todo_service import TodoService, TodoItem, get_todo_service


class TestTodoService:
    """Tests for TodoService."""

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def todo_service(self, temp_storage):
        """Create a TodoService with temp storage."""
        return TodoService(storage_dir=temp_storage)

    def test_create_service(self, temp_storage):
        """Test TodoService can be created."""
        service = TodoService(storage_dir=temp_storage)
        assert service.storage_dir == temp_storage
        assert service.todos_file == temp_storage / "todos.json"

    def test_add_todo(self, todo_service):
        """Test adding a todo."""
        todo = todo_service.add_todo("session1", "Test todo", "high")

        assert todo.content == "Test todo"
        assert todo.status == "pending"
        assert todo.priority == "high"

    def test_get_todos_empty(self, todo_service):
        """Test getting todos when none exist."""
        todos = todo_service.get_todos("session1")
        assert todos == []

    def test_get_todos_with_todos(self, todo_service):
        """Test getting todos."""
        todo_service.add_todo("session1", "Todo 1", "high")
        todo_service.add_todo("session1", "Todo 2", "medium")

        todos = todo_service.get_todos("session1")
        assert len(todos) == 2
        assert todos[0].content == "Todo 1"
        assert todos[1].content == "Todo 2"

    def test_update_todos(self, todo_service):
        """Test updating all todos."""
        todos = [
            {"content": "Updated 1", "status": "pending", "priority": "high"},
            {"content": "Updated 2", "status": "in_progress", "priority": "medium"},
            {"content": "Updated 3", "status": "completed", "priority": "low"},
        ]
        todo_service.update_todos("session1", todos)

        result = todo_service.get_todos("session1")
        assert len(result) == 3
        assert result[0].status == "pending"
        assert result[1].status == "in_progress"
        assert result[2].status == "completed"

    def test_complete_todo(self, todo_service):
        """Test completing a todo."""
        todo_service.add_todo("session1", "Todo 1", "high")
        todo_service.add_todo("session1", "Todo 2", "medium")

        result = todo_service.complete_todo("session1", 0)
        assert result is True

        todos = todo_service.get_todos("session1")
        assert todos[0].status == "completed"
        assert todos[1].status == "pending"

    def test_complete_todo_invalid_index(self, todo_service):
        """Test completing with invalid index."""
        result = todo_service.complete_todo("session1", 99)
        assert result is False

    def test_delete_todo(self, todo_service):
        """Test deleting a todo."""
        todo_service.add_todo("session1", "Todo 1", "high")
        todo_service.add_todo("session1", "Todo 2", "medium")

        result = todo_service.delete_todo("session1", 0)
        assert result is True

        todos = todo_service.get_todos("session1")
        assert len(todos) == 1
        assert todos[0].content == "Todo 2"

    def test_clear_todos(self, todo_service):
        """Test clearing todos."""
        todo_service.add_todo("session1", "Todo 1", "high")
        todo_service.add_todo("session1", "Todo 2", "medium")

        todo_service.clear_todos("session1")

        todos = todo_service.get_todos("session1")
        assert todos == []

    def test_get_stats_empty(self, todo_service):
        """Test getting stats with no todos."""
        stats = todo_service.get_stats("session1")

        assert stats["pending"] == 0
        assert stats["in_progress"] == 0
        assert stats["completed"] == 0
        assert stats["total"] == 0

    def test_get_stats_with_todos(self, todo_service):
        """Test getting todo statistics."""
        todo_service.update_todos("session1", [
            {"content": "Todo 1", "status": "pending", "priority": "high"},
            {"content": "Todo 2", "status": "in_progress", "priority": "medium"},
            {"content": "Todo 3", "status": "completed", "priority": "low"},
        ])

        stats = todo_service.get_stats("session1")

        assert stats["pending"] == 1
        assert stats["in_progress"] == 1
        assert stats["completed"] == 1
        assert stats["total"] == 3

    def test_persistence(self, todo_service):
        """Test todos are persisted to file."""
        todo_service.add_todo("session1", "Persisted todo", "high")

        new_service = TodoService(storage_dir=todo_service.storage_dir)
        todos = new_service.get_todos("session1")

        assert len(todos) == 1
        assert todos[0].content == "Persisted todo"

    def test_get_stats_nonexistent_session(self, todo_service):
        """Test getting stats for non-existent session."""
        stats = todo_service.get_stats("nonexistent")
        assert stats["total"] == 0


class TestTodoTool:
    """Tests for TodoTool with TodoService."""

    @pytest.mark.asyncio
    async def test_todo_read_action(self):
        """Test TodoTool read action."""
        import tempfile
        from pathlib import Path
        from nanocode.tools.builtin import TodoTool
        from nanocode.todo_service import TodoService
        from nanocode.core import set_current_session_id

        with tempfile.TemporaryDirectory() as tmpdir:
            service = TodoService(storage_dir=Path(tmpdir))
            tool = TodoTool(todo_service=service)
            set_current_session_id("test-session")
            service.add_todo("test-session", "Test todo", "high")

            result = await tool.execute(action="read")

            assert result.success is True
            assert "pending" in result.content

    @pytest.mark.asyncio
    async def test_todo_write_action(self):
        """Test TodoTool write action."""
        import tempfile
        from pathlib import Path
        from nanocode.tools.builtin import TodoTool
        from nanocode.todo_service import TodoService
        from nanocode.core import set_current_session_id

        with tempfile.TemporaryDirectory() as tmpdir:
            service = TodoService(storage_dir=Path(tmpdir))
            tool = TodoTool(todo_service=service)
            set_current_session_id("test-session")

            todos = [
                {"content": "New todo 1", "status": "pending", "priority": "high"},
                {"content": "New todo 2", "status": "completed", "priority": "low"},
            ]
            result = await tool.execute(action="write", todos=todos)

            assert result.success is True
            assert "pending" in result.content

    @pytest.mark.asyncio
    async def test_todo_invalid_action(self):
        """Test TodoTool with invalid action."""
        import tempfile
        from pathlib import Path
        from nanocode.tools.builtin import TodoTool
        from nanocode.todo_service import TodoService

        service = TodoService(storage_dir=Path(tempfile.mkdtemp()))
        tool = TodoTool(todo_service=service)

        result = await tool.execute(action="invalid")

        assert result.success is False
        assert "Invalid action" in str(result.error)


class TestGetTodoService:
    """Tests for get_todo_service singleton."""

    def test_get_todo_service_singleton(self):
        """Test get_todo_service returns singleton."""
        service1 = get_todo_service()
        service2 = get_todo_service()

        assert service1 is service2