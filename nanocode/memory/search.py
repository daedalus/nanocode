"""Memory search with BM25 ranking."""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SearchResult:
    """A single search result."""

    path: str
    snippet: str
    score: float
    scope: str
    scope_id: Optional[str]
    memory_type: str


class MemorySearch:
    """Search memory using SQLite FTS5 with BM25 ranking."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(
        self,
        query: str,
        scope: Optional[str] = None,
        scope_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 10,
        score_floor_ratio: float = 0.15,
    ) -> list[SearchResult]:
        """Search memory with BM25 ranking.

        Args:
            query: Search query
            scope: Filter by scope (global, project, session)
            scope_id: Filter by scope ID
            memory_type: Filter by memory type (memory, checkpoint, notes, task)
            limit: Maximum number of results
            score_floor_ratio: Minimum score as ratio of top result (0 to disable)

        Returns:
            List of search results sorted by relevance
        """
        if not query.strip():
            return []

        # Build FTS5 query
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []

        # Build WHERE clauses for filtering
        conditions = []
        params = {"query": fts_query, "limit": limit * 3}  # Over-fetch for floor filtering

        if scope:
            conditions.append("m.scope = :scope")
            params["scope"] = scope
        if scope_id:
            conditions.append("m.scope_id = :scope_id")
            params["scope_id"] = scope_id
        if memory_type:
            conditions.append("m.type = :memory_type")
            params["memory_type"] = memory_type

        where_clause = f"AND {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT
                m.path,
                snippet(memory_fts_idx, 4, '<<', '>>', '...', 32) AS snippet,
                bm25(memory_fts_idx) AS score,
                m.scope,
                m.scope_id,
                m.type
            FROM memory_fts_idx
            JOIN memory_fts m ON m.id = memory_fts_idx.rowid
            WHERE memory_fts_idx MATCH :query
            {where_clause}
            ORDER BY score
            LIMIT :limit
        """

        result = await self.session.execute(text(sql), params)
        rows = result.fetchall()

        if not rows:
            return []

        # Convert to SearchResult objects
        results = []
        for row in rows:
            # BM25 returns lower = better, convert to higher = better
            # Row order: path(0), snippet(1), score(2), scope(3), scope_id(4), type(5)
            score = -row[2] if row[2] else 0
            results.append(
                SearchResult(
                    path=row[0],
                    snippet=row[1] or "",
                    score=score,
                    scope=row[3],
                    scope_id=row[4],
                    memory_type=row[5],
                )
            )

        # Apply score floor filtering
        if score_floor_ratio > 0 and results:
            top_score = results[0].score
            cutoff = top_score * score_floor_ratio
            results = [r for i, r in enumerate(results) if i == 0 or r.score >= cutoff]

        return results[:limit]

    def _build_fts_query(self, query: str) -> str:
        """Build FTS5 query from user input.

        Splits query into tokens and OR-joins them as phrase-quoted literals.
        Punctuation becomes separators.
        """
        import re

        # Split on non-alphanumeric characters
        tokens = re.findall(r"[a-zA-Z0-9_]+", query)

        if not tokens:
            return ""

        # Quote each token and OR-join
        quoted = [f'"{token}"' for token in tokens]
        return " OR ".join(quoted)

    async def search_with_context(
        self,
        query: str,
        context_window: int = 2,
        **kwargs,
    ) -> list[SearchResult]:
        """Search with surrounding context from the same file.

        Args:
            query: Search query
            context_window: Number of chunks before/after to include
            **kwargs: Additional arguments for search()

        Returns:
            Search results with expanded context
        """
        results = await self.search(query, **kwargs)

        if not results or context_window <= 0:
            return results

        # Group results by file
        file_chunks: dict[str, list[SearchResult]] = {}
        for result in results:
            if result.path not in file_chunks:
                file_chunks[result.path] = []
            file_chunks[result.path].append(result)

        # For each file, get surrounding chunks
        expanded_results = []
        for file_path, chunks in file_chunks.items():
            for chunk in chunks:
                # Get chunks around this one
                surrounding = await self._get_surrounding_chunks(
                    file_path, chunk.snippet, context_window
                )
                expanded_results.append(
                    SearchResult(
                        path=chunk.path,
                        snippet=surrounding,
                        score=chunk.score,
                        scope=chunk.scope,
                        scope_id=chunk.scope_id,
                        memory_type=chunk.memory_type,
                    )
                )

        return expanded_results

    async def _get_surrounding_chunks(
        self, file_path: str, current_snippet: str, window: int
    ) -> str:
        """Get surrounding chunks from the same file."""
        # Simple implementation - just return the snippet with context markers
        return f"[...]\n{current_snippet}\n[...]"

    async def get_scope_stats(self) -> dict:
        """Get statistics by scope."""
        result = await self.session.execute(
            text(
                """
                SELECT
                    scope,
                    COUNT(*) as count,
                    COUNT(DISTINCT path) as files
                FROM memory_fts
                GROUP BY scope
                """
            )
        )
        rows = result.fetchall()
        return {row[0]: {"count": row[1], "files": row[2]} for row in rows}

    async def get_type_stats(self) -> dict:
        """Get statistics by memory type."""
        result = await self.session.execute(
            text(
                """
                SELECT
                    type,
                    COUNT(*) as count,
                    COUNT(DISTINCT path) as files
                FROM memory_fts
                GROUP BY type
                """
            )
        )
        rows = result.fetchall()
        return {row[0]: {"count": row[1], "files": row[2]} for row in rows}
