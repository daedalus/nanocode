"""Todo service for managing persistent todo list."""

import json
import logging
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("nanocode.todo")


@dataclass
class TodoItem:
    """A single todo item."""
    content: str
    status: str = "pending"
    priority: str = "medium"


class TodoService:
    """Service for managing todos with file-based persistence."""

    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            storage_dir = Path.home() / ".local/share/nanocode/storage"
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.todos_file = self.storage_dir / "todos.json"

    def get_todos(self, session_id: str) -> list[TodoItem]:
        """Get todos for a session."""
        todos = self._load()
        return todos.get(session_id, [])

    def update_todos(self, session_id: str, todos: list[dict]) -> None:
        """Update todos for a session."""
        all_todos = self._load()
        all_todos[session_id] = [
            TodoItem(
                content=t.get("content", ""),
                status=t.get("status", "pending"),
                priority=t.get("priority", "medium"),
            )
            for t in todos
        ]
        self._save(all_todos)
        logger.debug(f"Updated {len(todos)} todos for session {session_id}")

    def add_todo(self, session_id: str, content: str, priority: str = "medium") -> TodoItem:
        """Add a new todo to a session."""
        todos = self.get_todos(session_id)
        todo = TodoItem(content=content, status="pending", priority=priority)
        todos.append(todo)
        self.update_todos(session_id, [{"content": t.content, "status": t.status, "priority": t.priority} for t in todos])
        return todo

    def complete_todo(self, session_id: str, index: int) -> bool:
        """Mark a todo as completed by index."""
        todos = self.get_todos(session_id)
        if 0 <= index < len(todos):
            todos[index].status = "completed"
            self.update_todos(session_id, [{"content": t.content, "status": t.status, "priority": t.priority} for t in todos])
            return True
        return False

    def delete_todo(self, session_id: str, index: int) -> bool:
        """Delete a todo by index."""
        todos = self.get_todos(session_id)
        if 0 <= index < len(todos):
            todos.pop(index)
            self.update_todos(session_id, [{"content": t.content, "status": t.status, "priority": t.priority} for t in todos])
            return True
        return False

    def clear_todos(self, session_id: str) -> None:
        """Clear all todos for a session."""
        all_todos = self._load()
        if session_id in all_todos:
            del all_todos[session_id]
            self._save(all_todos)

    def get_stats(self, session_id: str) -> dict:
        """Get todo statistics for a session."""
        todos = self.get_todos(session_id)
        pending = sum(1 for t in todos if t.status == "pending")
        in_progress = sum(1 for t in todos if t.status == "in_progress")
        completed = sum(1 for t in todos if t.status == "completed")
        return {
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed,
            "total": len(todos),
        }

    def _load(self) -> dict[str, list[TodoItem]]:
        """Load todos from file."""
        if not self.todos_file.exists():
            return {}
        try:
            with open(self.todos_file) as f:
                data = json.load(f)
            return {
                session_id: [
                    TodoItem(
                        content=t.get("content", ""),
                        status=t.get("status", "pending"),
                        priority=t.get("priority", "medium"),
                    )
                    for t in todos
                ]
                for session_id, todos in data.items()
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load todos: {e}")
            return {}

    def _save(self, todos: dict[str, list[TodoItem]]) -> None:
        """Save todos to file."""
        data = {
            session_id: [
                {"content": t.content, "status": t.status, "priority": t.priority}
                for t in session_todos
            ]
            for session_id, session_todos in todos.items()
        }
        with open(self.todos_file, "w") as f:
            json.dump(data, f, indent=2)


# Global service instance
_service: Optional[TodoService] = None


def get_todo_service() -> TodoService:
    """Get the global todo service instance."""
    global _service
    if _service is None:
        _service = TodoService()
    return _service