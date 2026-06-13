"""Scheduler - Interval-based task scheduler.

Ported from kilo's scheduler/index.ts.
Useful for periodic memory reconciliation, cache cleanup, or watchdog tasks.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A scheduled task."""

    id: str
    interval: float  # seconds
    callback: Callable[[], Coroutine[Any, Any, None]]
    scope: str = "instance"  # "instance" or "global"
    last_run: float = 0.0
    next_run: float = 0.0
    running: bool = False
    cancelled: bool = False


class Scheduler:
    """Simple interval-based task scheduler.

    Tasks run periodically at their specified interval.
    Supports instance-scoped and global-scoped tasks.
    """

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._tasks_by_scope: dict[str, dict[str, ScheduledTask]] = {
            "instance": {},
            "global": {},
        }
        self._running = False
        self._task: asyncio.Task | None = None

    def register(
        self,
        id: str,
        interval: float,
        callback: Callable[[], Coroutine[Any, Any, None]],
        scope: str = "instance",
    ) -> ScheduledTask:
        """Register a scheduled task.

        Args:
            id: Unique task identifier
            interval: Interval in seconds between runs
            callback: Async function to call
            scope: "instance" or "global"

        Returns:
            The registered ScheduledTask
        """
        if id in self._tasks:
            logger.warning(f"Task {id} already registered, replacing")
            self.unregister(id)

        now = time.monotonic()
        task = ScheduledTask(
            id=id,
            interval=interval,
            callback=callback,
            scope=scope,
            last_run=0,
            next_run=now + interval,
        )

        self._tasks[id] = task
        self._tasks_by_scope[scope][id] = task

        logger.debug(f"Registered task {id} (interval={interval}s, scope={scope})")
        return task

    def unregister(self, id: str) -> bool:
        """Unregister a task.

        Args:
            id: Task identifier

        Returns:
            True if task was unregistered
        """
        task = self._tasks.pop(id, None)
        if task:
            task.cancelled = True
            if id in self._tasks_by_scope.get(task.scope, {}):
                del self._tasks_by_scope[task.scope][id]
            logger.debug(f"Unregistered task {id}")
            return True
        return False

    def get_task(self, id: str) -> ScheduledTask | None:
        """Get a task by ID."""
        return self._tasks.get(id)

    def list_tasks(self, scope: str | None = None) -> list[ScheduledTask]:
        """List all tasks, optionally filtered by scope."""
        if scope:
            return list(self._tasks_by_scope.get(scope, {}).values())
        return list(self._tasks.values())

    async def start(self):
        """Start the scheduler loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.debug("Scheduler started")

    async def stop(self):
        """Stop the scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.debug("Scheduler stopped")

    async def _loop(self):
        """Main scheduler loop."""
        while self._running:
            now = time.monotonic()

            for task in list(self._tasks.values()):
                if task.cancelled or task.running:
                    continue

                if now >= task.next_run:
                    task.running = True
                    task.last_run = now
                    task.next_run = now + task.interval

                    try:
                        await task.callback()
                    except Exception as e:
                        logger.error(f"Task {task.id} failed: {e}")
                    finally:
                        task.running = False

            await asyncio.sleep(0.1)

    def clear(self, scope: str | None = None):
        """Clear all tasks, optionally filtered by scope."""
        if scope:
            for id in list(self._tasks_by_scope.get(scope, {}).keys()):
                self.unregister(id)
        else:
            for id in list(self._tasks.keys()):
                self.unregister(id)

    async def run_now(self, id: str) -> bool:
        """Immediately run a task.

        Args:
            id: Task identifier

        Returns:
            True if task was run successfully
        """
        task = self._tasks.get(id)
        if not task:
            return False

        task.running = True
        task.last_run = time.monotonic()
        try:
            await task.callback()
            return True
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            return False
        finally:
            task.running = False


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    """Get or create the global scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
