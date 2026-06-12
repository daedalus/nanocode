"""Project Memory - High-level memory API with auto-save and search tool.

Based on Aura's memory_db.py:
- Auto-saves completed task/worker records
- Search tool for AI queries
- User-accessible memory entries
"""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .indexer import MemoryIndexer
from .search import MemorySearch

logger = logging.getLogger(__name__)


class MemoryEntryType(StrEnum):
    """Types of memory entries."""

    TASK_COMPLETE = "task_complete"
    DECISION = "decision"
    LEARNING = "learning"
    ERROR = "error"
    NOTE = "note"
    ARCHITECTURE = "architecture"


@dataclass
class MemoryEntry:
    """A single memory entry."""

    id: int | None = None
    key: str = ""
    content: str = ""
    entry_type: MemoryEntryType = MemoryEntryType.NOTE
    scope: str = "project"
    scope_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "content": self.content,
            "entry_type": self.entry_type.value,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ProjectMemory:
    """High-level project memory with auto-save and search.

    Based on Aura's memory_db.py:
    - Auto-saves completed task/worker records
    - Search tool for AI queries
    - User-accessible memory entries
    """

    def __init__(self, session: AsyncSession):
        """Initialize project memory.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session
        self.indexer = MemoryIndexer(session)
        self.search_engine = MemorySearch(session)
        self._initialized = False

    async def initialize(self):
        """Initialize the memory tables."""
        if self._initialized:
            return

        await self.indexer.initialize()

        # Create project_memory table for structured entries
        await self.session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS project_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    entry_type TEXT NOT NULL DEFAULT 'note',
                    scope TEXT NOT NULL DEFAULT 'project',
                    scope_id TEXT,
                    metadata JSON,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        )

        await self.session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_project_memory_key
                ON project_memory(key)
                """
            )
        )

        await self.session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_project_memory_type
                ON project_memory(entry_type)
                """
            )
        )

        await self.session.commit()
        self._initialized = True

    async def save_entry(self, entry: MemoryEntry) -> int:
        """Save a memory entry.

        Args:
            entry: Memory entry to save

        Returns:
            Entry ID
        """
        await self.initialize()

        result = await self.session.execute(
            text(
                """
                INSERT INTO project_memory (key, content, entry_type, scope, scope_id, metadata, created_at, updated_at)
                VALUES (:key, :content, :entry_type, :scope, :scope_id, :metadata, :created_at, :updated_at)
                """
            ),
            {
                "key": entry.key,
                "content": entry.content,
                "entry_type": entry.entry_type.value,
                "scope": entry.scope,
                "scope_id": entry.scope_id,
                "metadata": json.dumps(entry.metadata),
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
            },
        )
        await self.session.commit()

        entry_id = result.lastrowid
        logger.debug(f"Saved memory entry: {entry.key} (id={entry_id})")
        return entry_id

    async def save_task_complete(
        self,
        task_id: str,
        summary: str,
        details: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Auto-save a completed task record.

        Args:
            task_id: Task identifier
            summary: Task summary
            details: Additional details
            metadata: Extra metadata

        Returns:
            Entry ID
        """
        entry = MemoryEntry(
            key=f"task:{task_id}",
            content=f"## {summary}\n\n{details}" if details else summary,
            entry_type=MemoryEntryType.TASK_COMPLETE,
            metadata={"task_id": task_id, **(metadata or {})},
        )
        return await self.save_entry(entry)

    async def save_decision(
        self,
        key: str,
        decision: str,
        rationale: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save an architecture/design decision.

        Args:
            key: Decision identifier
            decision: The decision made
            rationale: Why this decision was made
            metadata: Extra metadata

        Returns:
            Entry ID
        """
        content = f"## Decision: {key}\n\n{decision}"
        if rationale:
            content += f"\n\n**Rationale:** {rationale}"

        entry = MemoryEntry(
            key=f"decision:{key}",
            content=content,
            entry_type=MemoryEntryType.DECISION,
            metadata=metadata or {},
        )
        return await self.save_entry(entry)

    async def save_learning(
        self,
        key: str,
        learning: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save a learning/pattern discovered.

        Args:
            key: Learning identifier
            learning: What was learned
            metadata: Extra metadata

        Returns:
            Entry ID
        """
        entry = MemoryEntry(
            key=f"learning:{key}",
            content=learning,
            entry_type=MemoryEntryType.LEARNING,
            metadata=metadata or {},
        )
        return await self.save_entry(entry)

    async def save_error(
        self,
        key: str,
        error: str,
        solution: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save an error and its solution.

        Args:
            key: Error identifier
            error: What went wrong
            solution: How it was fixed
            metadata: Extra metadata

        Returns:
            Entry ID
        """
        content = f"## Error: {key}\n\n{error}"
        if solution:
            content += f"\n\n**Solution:** {solution}"

        entry = MemoryEntry(
            key=f"error:{key}",
            content=content,
            entry_type=MemoryEntryType.ERROR,
            metadata=metadata or {},
        )
        return await self.save_entry(entry)

    async def get_entry(self, entry_id: int) -> MemoryEntry | None:
        """Get a memory entry by ID."""
        await self.initialize()

        result = await self.session.execute(
            text("SELECT * FROM project_memory WHERE id = :id"),
            {"id": entry_id},
        )
        row = result.fetchone()

        if not row:
            return None

        return MemoryEntry(
            id=row[0],
            key=row[1],
            content=row[2],
            entry_type=MemoryEntryType(row[3]),
            scope=row[4],
            scope_id=row[5],
            metadata=json.loads(row[6]) if row[6] else {},
            created_at=row[7],
            updated_at=row[8],
        )

    async def search(
        self,
        query: str,
        entry_type: MemoryEntryType | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Search memory entries.

        Args:
            query: Search query
            entry_type: Filter by entry type
            limit: Maximum results

        Returns:
            List of matching entries
        """
        await self.initialize()

        # Also search project_memory table
        conditions = ["content LIKE :query OR key LIKE :query"]
        params = {"query": f"%{query}%", "limit": limit}

        if entry_type:
            conditions.append("entry_type = :entry_type")
            params["entry_type"] = entry_type.value

        where_clause = " AND ".join(conditions)

        result = await self.session.execute(
            text(f"SELECT * FROM project_memory WHERE {where_clause} ORDER BY updated_at DESC LIMIT :limit"),
            params,
        )
        rows = result.fetchall()

        entries = []
        for row in rows:
            entries.append(
                MemoryEntry(
                    id=row[0],
                    key=row[1],
                    content=row[2],
                    entry_type=MemoryEntryType(row[3]),
                    scope=row[4],
                    scope_id=row[5],
                    metadata=json.loads(row[6]) if row[6] else {},
                    created_at=row[7],
                    updated_at=row[8],
                )
            )

        return entries

    async def list_entries(
        self,
        entry_type: MemoryEntryType | None = None,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """List memory entries.

        Args:
            entry_type: Filter by entry type
            limit: Maximum results

        Returns:
            List of entries
        """
        await self.initialize()

        conditions = []
        params: dict[str, Any] = {"limit": limit}

        if entry_type:
            conditions.append("entry_type = :entry_type")
            params["entry_type"] = entry_type.value

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        result = await self.session.execute(
            text(f"SELECT * FROM project_memory {where_clause} ORDER BY updated_at DESC LIMIT :limit"),
            params,
        )
        rows = result.fetchall()

        return [
            MemoryEntry(
                id=row[0],
                key=row[1],
                content=row[2],
                entry_type=MemoryEntryType(row[3]),
                scope=row[4],
                scope_id=row[5],
                metadata=json.loads(row[6]) if row[6] else {},
                created_at=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    async def delete_entry(self, entry_id: int) -> bool:
        """Delete a memory entry."""
        await self.initialize()

        result = await self.session.execute(
            text("DELETE FROM project_memory WHERE id = :id"),
            {"id": entry_id},
        )
        await self.session.commit()
        return result.rowcount > 0

    async def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        await self.initialize()

        result = await self.session.execute(
            text(
                """
                SELECT
                    entry_type,
                    COUNT(*) as count
                FROM project_memory
                GROUP BY entry_type
                """
            )
        )
        rows = result.fetchall()

        type_counts = {row[0]: row[1] for row in rows}
        total = sum(type_counts.values())

        return {
            "total_entries": total,
            "by_type": type_counts,
        }
