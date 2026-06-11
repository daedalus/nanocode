"""Dual-Engine Grep - Try ripgrep first, fall back to pure-Python.

Based on Aura's grep.py:
- Try ripgrep first (much faster)
- Fall back to pure-Python regex search
- Auto-retry as regex if literal search fails
"""

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GrepMatch:
    """A single grep match."""

    file_path: str
    line_number: int
    line_content: str
    match_start: int = 0
    match_end: int = 0


@dataclass
class GrepResult:
    """Result from a grep operation."""

    matches: List[GrepMatch] = field(default_factory=list)
    total_matches: int = 0
    files_searched: int = 0
    engine_used: str = ""
    query_time_ms: float = 0.0
    error: Optional[str] = None


class DualEngineGrep:
    """Dual-engine grep with ripgrep fallback.

    Based on Aura's approach:
    1. Try ripgrep first (much faster)
    2. Fall back to pure-Python regex search
    3. Auto-retry as regex if literal search fails
    """

    def __init__(
        self,
        max_results: int = 1000,
        timeout_seconds: int = 30,
    ):
        """Initialize the dual-engine grep.

        Args:
            max_results: Maximum number of results to return
            timeout_seconds: Timeout for ripgrep execution
        """
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self._ripgrep_available: Optional[bool] = None

    def is_ripgrep_available(self) -> bool:
        """Check if ripgrep is available."""
        if self._ripgrep_available is None:
            self._ripgrep_available = shutil.which("rg") is not None
        return self._ripgrep_available

    def search(
        self,
        pattern: str,
        path: str = ".",
        include: Optional[str] = None,
        exclude: Optional[str] = None,
        case_insensitive: bool = False,
        whole_word: bool = False,
        literal: bool = False,
    ) -> GrepResult:
        """Search using dual-engine approach.

        Args:
            pattern: Search pattern (regex or literal)
            path: Directory or file to search
            include: File pattern to include (e.g., "*.py")
            exclude: File pattern to exclude
            case_insensitive: Case-insensitive search
            whole_word: Match whole words only
            literal: Treat pattern as literal string

        Returns:
            GrepResult with matches
        """
        import time

        start_time = time.time()

        # Try ripgrep first
        if self.is_ripgrep_available():
            result = self._search_ripgrep(
                pattern, path, include, exclude,
                case_insensitive, whole_word, literal,
            )
            if result.error is None:
                result.query_time_ms = (time.time() - start_time) * 1000
                result.engine_used = "ripgrep"
                return result

        # Fall back to pure-Python
        result = self._search_python(
            pattern, path, include, exclude,
            case_insensitive, whole_word, literal,
        )
        result.query_time_ms = (time.time() - start_time) * 1000
        result.engine_used = "python"

        # Auto-retry as regex if literal search failed and pattern looks regex-like
        if result.total_matches == 0 and literal and self._looks_like_regex(pattern):
            logger.debug(f"Literal search failed, retrying as regex: {pattern}")
            result = self._search_python(
                pattern, path, include, exclude,
                case_insensitive, whole_word, literal=False,
            )
            result.query_time_ms = (time.time() - start_time) * 1000
            result.engine_used = "python-regex-retry"

        return result

    def _search_ripgrep(
        self,
        pattern: str,
        path: str,
        include: Optional[str],
        exclude: Optional[str],
        case_insensitive: bool,
        whole_word: bool,
        literal: bool,
    ) -> GrepResult:
        """Search using ripgrep."""
        cmd = ["rg", "--json", "--max-count", str(self.max_results)]

        if case_insensitive:
            cmd.append("-i")
        if whole_word:
            cmd.append("-w")
        if literal:
            cmd.append("-F")
        if include:
            cmd.extend(["-g", include])
        if exclude:
            cmd.extend(["-g", f"!{exclude}"])

        cmd.extend([pattern, path])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )

            if proc.returncode == 0 or proc.returncode == 1:
                # ripgrep returns 1 for no matches
                return self._parse_ripgrep_json(proc.stdout)
            else:
                return GrepResult(error=f"ripgrep failed: {proc.stderr}")

        except subprocess.TimeoutExpired:
            return GrepResult(error="ripgrep timeout")
        except Exception as e:
            return GrepResult(error=f"ripgrep error: {e}")

    def _parse_ripgrep_json(self, output: str) -> GrepResult:
        """Parse ripgrep JSON output."""
        result = GrepResult()
        files_seen = set()

        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                import json
                data = json.loads(line)

                if data.get("type") == "match":
                    match_data = data["data"]
                    file_path = match_data["path"]["text"]
                    line_number = match_data["line_number"]
                    line_content = match_data["lines"]["text"]

                    # Extract match submatches
                    submatches = match_data.get("submatches", [])
                    match_start = submatches[0]["start"] if submatches else 0
                    match_end = submatches[0]["end"] if submatches else len(line_content)

                    result.matches.append(
                        GrepMatch(
                            file_path=file_path,
                            line_number=line_number,
                            line_content=line_content.rstrip("\n"),
                            match_start=match_start,
                            match_end=match_end,
                        )
                    )
                    files_seen.add(file_path)

            except (json.JSONDecodeError, KeyError):
                continue

        result.total_matches = len(result.matches)
        result.files_searched = len(files_seen)
        return result

    def _search_python(
        self,
        pattern: str,
        path: str,
        include: Optional[str],
        exclude: Optional[str],
        case_insensitive: bool,
        whole_word: bool,
        literal: bool,
    ) -> GrepResult:
        """Search using pure-Python."""
        result = GrepResult()
        files_seen = set()

        # Compile regex pattern
        flags = re.IGNORECASE if case_insensitive else 0
        if whole_word:
            pattern = rf"\b{pattern}\b"
        if literal:
            pattern = re.escape(pattern)

        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return GrepResult(error=f"Invalid regex: {e}")

        # Determine files to search
        if os.path.isfile(path):
            files = [path]
        else:
            files = self._get_files(path, include, exclude)

        for file_path in files[:self.max_results]:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_number, line in enumerate(f, 1):
                        match = regex.search(line)
                        if match:
                            result.matches.append(
                                GrepMatch(
                                    file_path=file_path,
                                    line_number=line_number,
                                    line_content=line.rstrip("\n"),
                                    match_start=match.start(),
                                    match_end=match.end(),
                                )
                            )
                            files_seen.add(file_path)

                            if len(result.matches) >= self.max_results:
                                break

            except (IOError, UnicodeDecodeError):
                continue

            if len(result.matches) >= self.max_results:
                break

        result.total_matches = len(result.matches)
        result.files_searched = len(files_seen)
        return result

    def _get_files(
        self,
        path: str,
        include: Optional[str],
        exclude: Optional[str],
    ) -> List[str]:
        """Get files to search."""
        files = []
        include_pattern = self._glob_to_regex(include) if include else None
        exclude_pattern = self._glob_to_regex(exclude) if exclude else None

        for root, dirs, filenames in os.walk(path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for filename in filenames:
                if filename.startswith("."):
                    continue

                file_path = os.path.join(root, filename)

                if include_pattern and not include_pattern.match(filename):
                    continue
                if exclude_pattern and exclude_pattern.match(filename):
                    continue

                files.append(file_path)

        return files

    def _glob_to_regex(self, pattern: str):
        """Convert glob pattern to regex."""
        import fnmatch
        regex_str = fnmatch.translate(pattern)
        return re.compile(regex_str)

    def _looks_like_regex(self, pattern: str) -> bool:
        """Check if pattern looks like a regex."""
        regex_chars = set(".*+?^${}()|[]\\")
        return any(c in regex_chars for c in pattern)


# Global instance
_dual_engine_grep: Optional[DualEngineGrep] = None


def get_dual_engine_grep(max_results: int = 1000) -> DualEngineGrep:
    """Get or create the global dual-engine grep."""
    global _dual_engine_grep
    if _dual_engine_grep is None:
        _dual_engine_grep = DualEngineGrep(max_results=max_results)
    return _dual_engine_grep


def reset_dual_engine_grep():
    """Reset the global dual-engine grep."""
    global _dual_engine_grep
    _dual_engine_grep = None
