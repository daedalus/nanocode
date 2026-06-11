"""Memory indexer - indexes memory files into SQLite FTS5."""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MemoryIndexer:
    """Indexes memory files into SQLite FTS5 for full-text search."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._initialized = False

    async def initialize(self):
        """Initialize FTS5 virtual table if not exists."""
        if self._initialized:
            return

        await self.session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS memory_fts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'global',
                    scope_id TEXT,
                    type TEXT NOT NULL DEFAULT 'memory',
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        await self.session.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_idx USING fts5(
                    path,
                    scope,
                    scope_id,
                    type,
                    content,
                    content=memory_fts,
                    content_rowid=id,
                    tokenize='porter unicode61'
                )
                """
            )
        )

        await self.session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memory_fts BEGIN
                    INSERT INTO memory_fts_idx(rowid, path, scope, scope_id, type, content)
                    VALUES (new.id, new.path, new.scope, new.scope_id, new.type, new.content);
                END
                """
            )
        )

        await self.session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memory_fts BEGIN
                    INSERT INTO memory_fts_idx(memory_fts_idx, rowid, path, scope, scope_id, type, content)
                    VALUES ('delete', old.id, old.path, old.scope, old.scope_id, old.type, old.content);
                END
                """
            )
        )

        await self.session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memory_fts BEGIN
                    INSERT INTO memory_fts_idx(memory_fts_idx, rowid, path, scope, scope_id, type, content)
                    VALUES ('delete', old.id, old.path, old.scope, old.scope_id, old.type, old.content);
                    INSERT INTO memory_fts_idx(rowid, path, scope, scope_id, type, content)
                    VALUES (new.id, new.path, new.scope, new.scope_id, new.type, new.content);
                END
                """
            )
        )

        await self.session.commit()
        self._initialized = True

    async def index_file(
        self,
        file_path: str,
        scope: str = "global",
        scope_id: Optional[str] = None,
        memory_type: str = "memory",
    ) -> int:
        """Index a single memory file into FTS5.

        Args:
            file_path: Path to the memory file
            scope: Scope of the memory (global, project, session)
            scope_id: Optional scope identifier
            memory_type: Type of memory (memory, checkpoint, notes, task)

        Returns:
            Number of chunks indexed
        """
        await self.initialize()

        if not os.path.exists(file_path):
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            return 0

        # Remove existing entries for this file
        await self.session.execute(
            text("DELETE FROM memory_fts WHERE path = :path"),
            {"path": file_path},
        )

        # Split content into chunks for better search results
        chunks = self._split_into_chunks(content)

        for chunk in chunks:
            if chunk.strip():
                await self.session.execute(
                    text(
                        """
                        INSERT INTO memory_fts (path, scope, scope_id, type, content)
                        VALUES (:path, :scope, :scope_id, :type, :content)
                        """
                    ),
                    {
                        "path": file_path,
                        "scope": scope,
                        "scope_id": scope_id,
                        "type": memory_type,
                        "content": chunk,
                    },
                )

        await self.session.commit()
        return len(chunks)

    def _split_into_chunks(self, content: str, max_chunk_size: int = 2000) -> list[str]:
        """Split content into manageable chunks for indexing.

        Splits on paragraph boundaries when possible, falls back to line boundaries.
        """
        if len(content) <= max_chunk_size:
            return [content]

        chunks = []
        current_chunk = ""

        # Try splitting on double newlines (paragraphs)
        paragraphs = content.split("\n\n")
        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) + 2 > max_chunk_size:
                if current_chunk:
                    chunks.append(current_chunk)
                # If single paragraph is too large, split on single newlines
                if len(paragraph) > max_chunk_size:
                    lines = paragraph.split("\n")
                    for line in lines:
                        if len(current_chunk) + len(line) + 1 > max_chunk_size:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = line
                        else:
                            current_chunk = f"{current_chunk}\n{line}" if current_chunk else line
                else:
                    current_chunk = paragraph
            else:
                current_chunk = f"{current_chunk}\n\n{paragraph}" if current_chunk else paragraph

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    async def index_directory(
        self,
        directory: str,
        scope: str = "global",
        scope_id: Optional[str] = None,
        patterns: Optional[list[str]] = None,
    ) -> int:
        """Index all memory files in a directory.

        Args:
            directory: Directory to index
            scope: Scope of the memory
            scope_id: Optional scope identifier
            patterns: File patterns to include (default: *.md)

        Returns:
            Total number of chunks indexed
        """
        if patterns is None:
            patterns = ["*.md"]

        total_chunks = 0
        dir_path = Path(directory)

        if not dir_path.exists():
            return 0

        for pattern in patterns:
            for file_path in dir_path.glob(pattern):
                if file_path.is_file():
                    chunks = await self.index_file(
                        str(file_path),
                        scope=scope,
                        scope_id=scope_id,
                        memory_type=self._detect_memory_type(file_path.name),
                    )
                    total_chunks += chunks

        return total_chunks

    def _detect_memory_type(self, filename: str) -> str:
        """Detect memory type from filename."""
        filename_lower = filename.lower()
        if "checkpoint" in filename_lower:
            return "checkpoint"
        elif "notes" in filename_lower:
            return "notes"
        elif "task" in filename_lower or "progress" in filename_lower:
            return "task"
        elif "memory" in filename_lower:
            return "memory"
        else:
            return "memory"

    async def remove_file(self, file_path: str) -> bool:
        """Remove all entries for a file from the index.

        Args:
            file_path: Path to the file to remove

        Returns:
            True if entries were removed
        """
        await self.initialize()

        result = await self.session.execute(
            text("DELETE FROM memory_fts WHERE path = :path"),
            {"path": file_path},
        )
        await self.session.commit()
        return result.rowcount > 0

    async def get_stats(self) -> dict:
        """Get indexing statistics."""
        await self.initialize()

        result = await self.session.execute(
            text(
                """
                SELECT
                    COUNT(*) as total_entries,
                    COUNT(DISTINCT path) as total_files,
                    COUNT(DISTINCT scope) as total_scopes,
                    MIN(created_at) as oldest_entry,
                    MAX(updated_at) as newest_entry
                FROM memory_fts
                """
            )
        )
        row = result.fetchone()
        return {
            "total_entries": row[0] if row else 0,
            "total_files": row[1] if row else 0,
            "total_scopes": row[2] if row else 0,
            "oldest_entry": row[3] if row else None,
            "newest_entry": row[4] if row else None,
        }
