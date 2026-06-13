"""Task Registry - Tree-shaped task system based on MiMo-Code.

Provides hierarchical task management with parent-child relationships,
status lifecycle, and event logging.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from nanocode.storage.models import Task, TaskEvent


class TaskStatus(str, Enum):
    """Task status lifecycle."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    ABANDONED = "abandoned"


class TaskEventKind(str, Enum):
    """Task event types."""

    CREATED = "created"
    STARTED = "started"
    UNSTARTED = "unstarted"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    DONE = "done"
    ABANDONED = "abandoned"
    RENAMED = "renamed"


@dataclass
class TaskData:
    """Task data transfer object."""

    id: str
    session_id: str
    parent_task_id: Optional[str]
    status: TaskStatus
    summary: str
    owner: Optional[str]
    created_at: int
    last_event_at: int
    ended_at: Optional[int]
    cleanup_after: Optional[int]


@dataclass
class TaskEventData:
    """Task event data transfer object."""

    id: int
    task_id: str
    at: int
    kind: TaskEventKind
    summary: Optional[str]


class TaskRegistry:
    """Hierarchical task registry with lifecycle management.

    Based on MiMo-Code's tree-shaped task system.
    Tasks are identified by IDs like T1, T1.1, T1.2, etc.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    def _now_ms(self) -> int:
        """Get current time in milliseconds."""
        import time
        return int(time.time() * 1000)

    def _next_child_id(self, parent_id: Optional[str], siblings: list[str]) -> str:
        """Calculate next child task ID."""
        prefix = f"{parent_id}." if parent_id else "T"
        used = []
        for s in siblings:
            if parent_id:
                if s.startswith(prefix):
                    tail = s[len(prefix):]
                    if tail.isdigit():
                        used.append(int(tail))
            else:
                if s.startswith("T") and s[1:].isdigit():
                    used.append(int(s[1:]))

        next_num = max(used) + 1 if used else 1
        return f"{prefix}{next_num}"

    def _to_task_data(self, task: Task) -> TaskData:
        """Convert SQLAlchemy Task to TaskData."""
        return TaskData(
            id=task.id,
            session_id=task.session_id,
            parent_task_id=task.parent_task_id,
            status=TaskStatus(task.status),
            summary=task.summary,
            owner=task.owner,
            created_at=task.created_at,
            last_event_at=task.last_event_at,
            ended_at=task.ended_at,
            cleanup_after=task.cleanup_after,
        )

    def _to_event_data(self, event: TaskEvent) -> TaskEventData:
        """Convert SQLAlchemy TaskEvent to TaskEventData."""
        return TaskEventData(
            id=event.id,
            task_id=event.task_id,
            at=event.at,
            kind=TaskEventKind(event.kind),
            summary=event.summary,
        )

    async def create(
        self,
        session_id: str,
        summary: str,
        parent_id: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> TaskData:
        """Create a new task.

        Args:
            session_id: Session ID
            summary: Task description
            parent_id: Optional parent task ID
            owner: Optional task owner

        Returns:
            Created task data
        """
        # Get sibling tasks to calculate next ID
        result = await self.session.execute(
            select(Task.id).where(
                and_(
                    Task.session_id == session_id,
                    Task.parent_task_id == parent_id,
                )
            )
        )
        siblings = [row[0] for row in result.fetchall()]
        task_id = self._next_child_id(parent_id, siblings)

        now = self._now_ms()
        task = Task(
            id=task_id,
            session_id=session_id,
            parent_task_id=parent_id,
            status=TaskStatus.OPEN.value,
            summary=summary,
            owner=owner,
            created_at=now,
            last_event_at=now,
        )
        self.session.add(task)

        # Add creation event
        event = TaskEvent(
            session_id=session_id,
            task_id=task_id,
            at=now,
            kind=TaskEventKind.CREATED.value,
        )
        self.session.add(event)
        await self.session.commit()

        return self._to_task_data(task)

    async def get(self, session_id: str, task_id: str) -> Optional[TaskData]:
        """Get a task by ID."""
        result = await self.session.execute(
            select(Task).where(
                and_(Task.session_id == session_id, Task.id == task_id)
            )
        )
        task = result.scalar_one_or_none()
        return self._to_task_data(task) if task else None

    async def list(
        self,
        session_id: str,
        status: Optional[TaskStatus] = None,
        owner: Optional[str] = None,
        include_terminal: bool = False,
        include_archived: bool = False,
    ) -> List[TaskData]:
        """List tasks with optional filters."""
        query = select(Task).where(Task.session_id == session_id)

        if status:
            query = query.where(Task.status == status.value)
        elif not include_terminal:
            # Exclude terminal states by default
            query = query.where(
                Task.status.in_([
                    TaskStatus.OPEN.value,
                    TaskStatus.IN_PROGRESS.value,
                    TaskStatus.BLOCKED.value,
                ])
            )

        if owner:
            query = query.where(Task.owner == owner)

        if not include_archived:
            now = self._now_ms()
            query = query.where(
                or_(Task.cleanup_after.is_(None), Task.cleanup_after > now)
            )

        query = query.order_by(Task.created_at)
        result = await self.session.execute(query)
        return [self._to_task_data(task) for task in result.scalars()]

    async def start(
        self,
        session_id: str,
        task_id: str,
        owner: Optional[str] = None,
        event_summary: Optional[str] = None,
    ) -> TaskData:
        """Start or resume a task.

        Args:
            session_id: Session ID
            task_id: Task ID
            owner: Optional owner assignment
            event_summary: Optional event description

        Returns:
            Updated task data
        """
        task = await self._get_task(session_id, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Refuse to start terminal tasks
        if task.status in [TaskStatus.DONE.value, TaskStatus.ABANDONED.value]:
            raise ValueError(f"Cannot start terminal task {task_id} (status={task.status})")

        now = self._now_ms()
        task.status = TaskStatus.IN_PROGRESS.value
        task.last_event_at = now
        if owner:
            task.owner = owner

        event = TaskEvent(
            session_id=session_id,
            task_id=task_id,
            at=now,
            kind=TaskEventKind.STARTED.value,
            summary=event_summary,
        )
        self.session.add(event)
        await self.session.commit()

        return self._to_task_data(task)

    async def block(
        self,
        session_id: str,
        task_id: str,
        event_summary: Optional[str] = None,
    ) -> TaskData:
        """Block a task."""
        task = await self._get_task(session_id, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        now = self._now_ms()
        task.status = TaskStatus.BLOCKED.value
        task.last_event_at = now

        event = TaskEvent(
            session_id=session_id,
            task_id=task_id,
            at=now,
            kind=TaskEventKind.BLOCKED.value,
            summary=event_summary,
        )
        self.session.add(event)
        await self.session.commit()

        return self._to_task_data(task)

    async def unblock(
        self,
        session_id: str,
        task_id: str,
        event_summary: Optional[str] = None,
    ) -> TaskData:
        """Unblock a task."""
        task = await self._get_task(session_id, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        now = self._now_ms()
        task.status = TaskStatus.OPEN.value
        task.last_event_at = now

        event = TaskEvent(
            session_id=session_id,
            task_id=task_id,
            at=now,
            kind=TaskEventKind.UNBLOCKED.value,
            summary=event_summary,
        )
        self.session.add(event)
        await self.session.commit()

        return self._to_task_data(task)

    async def done(
        self,
        session_id: str,
        task_id: str,
        event_summary: Optional[str] = None,
        retention_days: int = 7,
    ) -> TaskData:
        """Mark a task as done.

        Args:
            session_id: Session ID
            task_id: Task ID
            event_summary: Optional event description
            retention_days: Days to keep task before archival
        """
        task = await self._get_task(session_id, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        now = self._now_ms()
        task.status = TaskStatus.DONE.value
        task.ended_at = now
        task.cleanup_after = now + (retention_days * 24 * 60 * 60 * 1000)
        task.last_event_at = now

        event = TaskEvent(
            session_id=session_id,
            task_id=task_id,
            at=now,
            kind=TaskEventKind.DONE.value,
            summary=event_summary,
        )
        self.session.add(event)
        await self.session.commit()

        return self._to_task_data(task)

    async def abandon(
        self,
        session_id: str,
        task_id: str,
        event_summary: Optional[str] = None,
        retention_days: int = 7,
    ) -> TaskData:
        """Abandon a task."""
        task = await self._get_task(session_id, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        now = self._now_ms()
        task.status = TaskStatus.ABANDONED.value
        task.ended_at = now
        task.cleanup_after = now + (retention_days * 24 * 60 * 60 * 1000)
        task.last_event_at = now

        event = TaskEvent(
            session_id=session_id,
            task_id=task_id,
            at=now,
            kind=TaskEventKind.ABANDONED.value,
            summary=event_summary,
        )
        self.session.add(event)
        await self.session.commit()

        return self._to_task_data(task)

    async def rename(
        self,
        session_id: str,
        task_id: str,
        summary: str,
    ) -> TaskData:
        """Rename a task's summary."""
        task = await self._get_task(session_id, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        now = self._now_ms()
        task.summary = summary
        task.last_event_at = now

        event = TaskEvent(
            session_id=session_id,
            task_id=task_id,
            at=now,
            kind=TaskEventKind.RENAMED.value,
            summary=summary,
        )
        self.session.add(event)
        await self.session.commit()

        return self._to_task_data(task)

    async def events(
        self,
        session_id: str,
        task_id: str,
    ) -> List[TaskEventData]:
        """Get all events for a task."""
        result = await self.session.execute(
            select(TaskEvent)
            .where(
                and_(
                    TaskEvent.session_id == session_id,
                    TaskEvent.task_id == task_id,
                )
            )
            .order_by(TaskEvent.at)
        )
        return [self._to_event_data(event) for event in result.scalars()]

    async def _get_task(self, session_id: str, task_id: str) -> Optional[Task]:
        """Get raw SQLAlchemy Task object."""
        result = await self.session.execute(
            select(Task).where(
                and_(Task.session_id == session_id, Task.id == task_id)
            )
        )
        return result.scalar_one_or_none()

    async def write_progress(
        self,
        session_id: str,
        task_id: str,
        content: str,
        data_dir: str | None = None,
    ) -> str:
        """Write progress.md for a task.

        Args:
            session_id: Session ID
            task_id: Task ID (e.g., T1, T1.1)
            content: Progress content to write
            data_dir: Optional data directory override

        Returns:
            Path to the written progress file
        """
        from nanocode.checkpoint import progress_path

        path = progress_path(session_id, task_id, data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return str(path)

    async def read_progress(
        self,
        session_id: str,
        task_id: str,
        data_dir: str | None = None,
    ) -> str | None:
        """Read progress.md for a task.

        Args:
            session_id: Session ID
            task_id: Task ID
            data_dir: Optional data directory override

        Returns:
            Progress content or None if not found
        """
        from nanocode.checkpoint import progress_path

        path = progress_path(session_id, task_id, data_dir)
        if path.exists():
            return path.read_text()
        return None

    async def render_task_ledger(
        self,
        session_id: str,
        include_terminal: bool = True,
        data_dir: str | None = None,
    ) -> str:
        """Render a hierarchical task ledger for checkpoint injection.

        Args:
            session_id: Session ID
            include_terminal: Include done/abandoned tasks
            data_dir: Optional data directory override

        Returns:
            Formatted task ledger string
        """
        from nanocode.checkpoint import progress_path

        tasks = await self.list(session_id, include_terminal=include_terminal)

        if not tasks:
            return "(none)"

        status_icons = {
            TaskStatus.OPEN: "🔵",
            TaskStatus.IN_PROGRESS: "🔄",
            TaskStatus.BLOCKED: "🟡",
            TaskStatus.DONE: "✅",
            TaskStatus.ABANDONED: "❌",
        }

        # Build parent -> children mapping
        by_parent: dict[str | None, list[TaskData]] = {}
        for task in tasks:
            parent = task.parent_task_id
            if parent not in by_parent:
                by_parent[parent] = []
            by_parent[parent].append(task)

        lines: list[str] = []

        def render_task(task: TaskData, indent: int = 0):
            icon = status_icons.get(task.status, "")
            prefix = "  " * indent
            progress_hint = ""
            path = progress_path(session_id, task.id, data_dir)
            if path.exists():
                progress_hint = f" (progress: tasks/{task.id}/progress.md)"
            lines.append(f"{prefix}- {icon} {task.id} {task.status.value} — {task.summary}{progress_hint}")
            # Render children
            children = by_parent.get(task.id, [])
            for child in children:
                render_task(child, indent + 1)

        # Render top-level tasks
        top_level = by_parent.get(None, [])
        for task in top_level:
            render_task(task)

        return "\n".join(lines)
