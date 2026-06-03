"""Orchestrates file walking, tokenization, mtime-based staleness, and search.

The :class:`CodebaseIndex` lazily builds a BM25 inverted index over the
workspace on first search, then incrementally refreshes on subsequent calls.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nanocode.codebase_index.bm25 import BM25Scorer, tokenize

# ---- Default configuration constants -----------------------------------------

INDEX_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".scala", ".md", ".txt", ".toml", ".yaml", ".yml", ".json",
    ".css", ".html", ".htm", ".scss", ".sql", ".sh", ".bash",
    ".zsh", ".fish", ".lua", ".zig", ".tex", ".r", ".m",
}

SKIP_DIRS: set[str] = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    ".venv", "venv", ".env", "env",
    "dist", "build", "target", ".next", ".nuxt", ".svelte-kit",
    ".cache", ".tox", ".eggs", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".hypothesis", ".coverage", "coverage",
}

SKIP_FILE_SUFFIXES: set[str] = {
    ".min.js", ".min.css", ".map", ".pyc", ".pyo", ".pyd",
    ".so", ".dll", ".dylib", ".o", ".a", ".lib",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".lock",
}

MAX_INDEX_FILES: int = 1500
MAX_FILE_BYTES: int = 128 * 1024  # 128 KB


def _cache_dir() -> Path:
    """Return the BM25 cache directory."""
    cache_dir = Path.home() / ".local" / "share" / "nanocode" / "bm25_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cache_path(workspace_root: Path) -> Path:
    """Return the cache file path for a given workspace root."""
    h = hashlib.sha256(str(workspace_root.resolve()).encode()).hexdigest()[:16]
    return _cache_dir() / f"{h}.json"


class CodebaseIndex:
    """Lazy-built BM25 index of the workspace codebase.

    Usage::

        index = CodebaseIndex(workspace_root)
        result = index.search("authentication handler")
    """

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root.resolve()
        self._scorer = BM25Scorer()
        self._files: dict[str, tuple[Path, float]] = {}
        self._built: bool = False
        self._extensions: set[str] = INDEX_EXTENSIONS
        self._max_files: int = MAX_INDEX_FILES
        self._max_file_bytes: int = MAX_FILE_BYTES
        self._loaded_from_cache = self._load_cache()

    @property
    def built(self) -> bool:
        return self._built

    @property
    def file_count(self) -> int:
        return len(self._files)

    # ---- file filtering ----------------------------------------------------

    def _should_index(self, file_path: Path, rel_path: Path) -> bool:
        if file_path.suffix.lower() not in self._extensions:
            return False

        try:
            size = file_path.stat().st_size
        except OSError:
            return False
        if size > self._max_file_bytes or size == 0:
            return False

        parts = rel_path.parts
        for part in parts:
            if part in SKIP_DIRS:
                return False
            if part.startswith("."):
                return False

        if file_path.suffix.lower() in SKIP_FILE_SUFFIXES:
            return False

        return True

    # ---- file reading ------------------------------------------------------

    @staticmethod
    def _read_file_safe(absolute_path: Path) -> str | None:
        try:
            return absolute_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return absolute_path.read_text(encoding="latin-1")
            except (OSError, UnicodeDecodeError):
                return None
        except OSError:
            return None

    # ---- file collection ---------------------------------------------------

    def _walk_and_collect(self) -> dict[str, tuple[Path, float]]:
        collected: dict[str, tuple[Path, float]] = {}
        for file_path in self._root.rglob("*"):
            if not file_path.is_file():
                continue
            if len(collected) >= self._max_files:
                break

            try:
                rel_path = file_path.relative_to(self._root)
            except ValueError:
                continue

            rel_str = rel_path.as_posix()

            if not self._should_index(file_path, rel_path):
                continue

            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                continue

            collected[rel_str] = (file_path, mtime)

        return collected

    # ---- cache layer -------------------------------------------------------

    def _load_cache(self) -> bool:
        cache_path = _cache_path(self._root)
        if not cache_path.is_file():
            return False

        try:
            raw = cache_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return False

        if not all(k in data for k in ("workspace_root", "files", "scorer")):
            return False

        if data.get("workspace_root") != str(self._root):
            return False

        files_data: dict[str, list] = data.get("files", {})
        scorer_data: dict = data.get("scorer", {})

        restored_files: dict[str, tuple[Path, float]] = {}
        for rel_str, (abs_path_str, cached_mtime) in files_data.items():
            abs_path = Path(abs_path_str)
            if not abs_path.is_file():
                continue
            try:
                current_mtime = abs_path.stat().st_mtime
            except OSError:
                continue
            if abs(current_mtime - cached_mtime) < 0.001:
                restored_files[rel_str] = (abs_path, cached_mtime)

        try:
            self._scorer = BM25Scorer.from_dict(scorer_data)
        except (KeyError, TypeError):
            return False

        self._files = restored_files

        cached_keys = set(files_data.keys())
        restored_keys = set(restored_files.keys())
        for stale_rel in cached_keys - restored_keys:
            self._scorer.remove_document(stale_rel)

        self._built = True
        return True

    def _save_cache(self) -> None:
        cache_path = _cache_path(self._root)
        data = {
            "workspace_root": str(self._root),
            "files": {
                rel: [str(abs_path), mtime]
                for rel, (abs_path, mtime) in self._files.items()
            },
            "scorer": self._scorer.to_dict(),
        }
        tmp_path = cache_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(cache_path)
        except OSError:
            pass

    # ---- build / refresh ---------------------------------------------------

    def build(self) -> None:
        self._scorer = BM25Scorer()
        self._files = {}

        collected = self._walk_and_collect()

        for rel_str, (abs_path, _mtime) in collected.items():
            content = self._read_file_safe(abs_path)
            if content is None:
                continue
            tokens = tokenize(content)
            if not tokens:
                continue
            self._scorer.add_document(rel_str, tokens)
            self._files[rel_str] = (abs_path, _mtime)

        self._built = True
        self._save_cache()

    def refresh(self) -> None:
        current = self._walk_and_collect()
        current_keys = set(current.keys())
        old_keys = set(self._files.keys())

        for rel_str in old_keys - current_keys:
            self._scorer.remove_document(rel_str)
            del self._files[rel_str]

        for rel_str in current_keys:
            abs_path, new_mtime = current[rel_str]

            if rel_str in old_keys:
                _, old_mtime = self._files[rel_str]
                if abs(new_mtime - old_mtime) < 0.001:
                    continue
                self._scorer.remove_document(rel_str)

            content = self._read_file_safe(abs_path)
            if content is None:
                continue
            tokens = tokenize(content)
            if not tokens:
                continue
            self._scorer.add_document(rel_str, tokens)
            self._files[rel_str] = (abs_path, new_mtime)

        self._save_cache()

    # ---- search ------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> dict:
        if not self._built:
            self.build()
        else:
            self.refresh()

        query_tokens = tokenize(query)

        if not query_tokens:
            return {
                "ok": True,
                "query": query,
                "results": [],
                "indexed_file_count": self._scorer.doc_count,
                "indexed_term_count": self._scorer.term_count,
            }

        raw_results = self._scorer.search(query_tokens, top_k=top_k)

        results: list[dict] = []
        for rel_str, score in raw_results:
            abs_path = self._files.get(rel_str, (None, None))[0]
            snippet = self._extract_snippet(abs_path, query_tokens)
            results.append({
                "path": rel_str,
                "score": round(score, 4),
                "snippet": snippet,
            })

        return {
            "ok": True,
            "query": query,
            "results": results,
            "indexed_file_count": self._scorer.doc_count,
            "indexed_term_count": self._scorer.term_count,
        }

    @staticmethod
    def _extract_snippet(file_path: Path | None, query_tokens: list[str]) -> str:
        if file_path is None:
            return "(file unavailable)"

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(file unavailable)"

        lines = text.splitlines()
        if not lines:
            return "(empty file)"

        matched_lines: list[str] = []
        for line in lines:
            line_lower = line.lower()
            if any(tok in line_lower for tok in query_tokens):
                matched_lines.append(line)
                if len("".join(matched_lines)) > 500:
                    break

        if matched_lines:
            snippet = "\n".join(matched_lines)
        else:
            snippet = "\n".join(lines[:3])

        if len(snippet) > 500:
            snippet = snippet[:497] + "..."

        return snippet

    # ---- root management ---------------------------------------------------

    def set_workspace_root(self, root: Path) -> None:
        self._root = root.resolve()
        self._scorer = BM25Scorer()
        self._files = {}
        self._built = False
