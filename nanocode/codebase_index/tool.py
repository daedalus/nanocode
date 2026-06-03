"""``search_codebase`` tool for nanocode.

Wraps :class:`CodebaseIndex` into a nanocode Tool that can be registered
in ``register_builtin_tools`` and invoked by the LLM.
"""

from __future__ import annotations

from pathlib import Path

from nanocode.codebase_index.indexer import CodebaseIndex
from nanocode.tools import Tool, ToolResult

# Module-level singleton: workspace_root -> CodebaseIndex
_INDEX_CACHE: dict[str, CodebaseIndex] = {}


def _get_index(workspace_root: str | Path | None = None) -> CodebaseIndex:
    root = Path(workspace_root or Path.cwd()).resolve()
    root_str = str(root)
    if root_str not in _INDEX_CACHE:
        _INDEX_CACHE[root_str] = CodebaseIndex(root)
    return _INDEX_CACHE[root_str]


class SearchCodebaseTool(Tool):
    """BM25-powered codebase search tool."""

    def __init__(self, workspace_root: str | None = None):
        super().__init__(
            name="search_codebase",
            description="Search the workspace codebase using BM25 to find relevant files. "
            "Works across Python, JS/TS, Go, Rust, Java, C/C++, and more. "
            "Understands camelCase and snake_case. Returns paths, relevance scores, and snippets.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language or keyword search query (e.g. 'authentication handler')",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        )
        self._workspace_root = workspace_root

    async def execute(self, query: str, top_k: int = 5) -> ToolResult:
        try:
            index = _get_index(self._workspace_root)
            result = index.search(query, top_k=top_k)

            results = result.get("results", [])
            if not results:
                return ToolResult.ok(
                    content="No matching files found.",
                    metadata={
                        "indexed_file_count": result.get("indexed_file_count", 0),
                        "indexed_term_count": result.get("indexed_term_count", 0),
                        "results": [],
                    },
                )

            lines = [
                f"Found {len(results)} result(s) in "
                f"{result['indexed_file_count']} indexed files "
                f"({result['indexed_term_count']} terms):\n"
            ]
            for r in results:
                lines.append(f"  [{r['score']:4.2f}] {r['path']}")
                snippet = r.get("snippet", "")
                if snippet:
                    lines.append(f"         {snippet.replace(chr(10), chr(10)+'         ')})")

            return ToolResult.ok(
                content="\n".join(lines),
                metadata={
                    "indexed_file_count": result.get("indexed_file_count", 0),
                    "indexed_term_count": result.get("indexed_term_count", 0),
                    "results": results,
                },
            )
        except Exception as e:
            return ToolResult.err(f"Search failed: {e}")
