"""Find usages tool: word-boundary grep for symbols.

Helps models locate where a function, class, or variable is defined/used
without needing to construct regex patterns themselves.
"""

from __future__ import annotations

import re
from pathlib import Path

from nanocode.tools import Tool, ToolResult


def _search_file(
    file_path: Path, pattern: re.Pattern, context_lines: int,
    search_path: Path
) -> dict | None:
    """Search a single file for pattern matches. Returns result dict or None."""
    try:
        text = file_path.read_text(errors="ignore")
    except Exception:
        return None

    lines = text.splitlines()
    matches = []
    for i, line in enumerate(lines):
        if pattern.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            context_block = lines[start:end]
            context_str = "\n".join(
                f"{start + j + 1}: {context_block[j]}"
                for j in range(len(context_block))
            )
            matches.append({
                "line_number": i + 1,
                "line": line,
                "context": context_str,
            })

    if not matches:
        return None

    try:
        rel = file_path.relative_to(search_path)
    except ValueError:
        rel = file_path

    return {"file": str(rel), "matches": matches}


class FindUsagesTool(Tool):
    """Find word-boundary usages of a symbol in the codebase."""

    def __init__(self, root_dir: str | None = None):
        super().__init__(
            name="find_usages",
            description="Find all usages of a symbol (function, class, variable) in the codebase "
            "using word-boundary matching. Simpler than grep — just give a symbol name.",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol name to search for (e.g. 'validate_token', 'Config')",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (defaults to workspace root)",
                    },
                    "include": {
                        "type": "string",
                        "description": "Glob filter (e.g. '*.py', '*.{ts,js}')",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Lines of context around each match (default: 1)",
                        "default": 1,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum files with matches to return (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["symbol"],
            },
        )
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()

    def _collect_files(self, search_path: Path, include: str | None) -> list[Path]:
        if include:
            return list(search_path.glob(include))
        return [f for f in sorted(search_path.rglob("*")) if f.is_file()]

    def _format_results(self, symbol: str, results: list[dict]) -> str:
        total_matches = sum(len(r["matches"]) for r in results)
        lines_out = [
            f"Found {total_matches} usage(s) of '{symbol}' in {len(results)} file(s):\n"
        ]
        for r in results:
            lines_out.append(f"--- {r['file']} ---")
            for m in r["matches"]:
                lines_out.append(f"  {m['line_number']}: {m['line']}")
        return "\n".join(lines_out)

    async def execute(
        self,
        symbol: str,
        path: str | None = None,
        include: str | None = None,
        context_lines: int = 1,
        max_results: int = 20,
    ) -> ToolResult:
        try:
            search_path = Path(path) if path else self.root_dir
            escaped = re.escape(symbol)
            pattern = re.compile(rf"\b{escaped}\b")
            files = self._collect_files(search_path, include)

            results: list[dict] = []
            for file_path in files:
                if len(results) >= max_results:
                    break
                r = _search_file(file_path, pattern, context_lines, search_path)
                if r is not None:
                    results.append(r)

            if not results:
                return ToolResult.ok(
                    content=f"No usages of '{symbol}' found.",
                    metadata={"symbol": symbol, "match_count": 0},
                )

            total_matches = sum(len(r["matches"]) for r in results)
            return ToolResult.ok(
                content=self._format_results(symbol, results),
                metadata={
                    "symbol": symbol,
                    "file_count": len(results),
                    "match_count": total_matches,
                    "results": results,
                },
            )
        except Exception as e:
            return ToolResult.err(f"find_usages failed: {e}")
