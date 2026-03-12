"""File tracking for auto-reload on modification."""

import os
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FileCacheEntry:
    """Cached file content with metadata."""
    path: str
    content: str
    mtime: float
    size: int
    cached_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0


class FileTracker:
    """Track file modifications for auto-reload."""

    def __init__(self, cache_dir: str = ".agent/cache"):
        self._cache: dict[str, FileCacheEntry] = {}
        self._cache_dir = cache_dir
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        """Ensure cache directory exists."""
        os.makedirs(self._cache_dir, exist_ok=True)

    def get(self, path: str) -> Optional[FileCacheEntry]:
        """Get cached file if exists."""
        return self._cache.get(path)

    def set(self, path: str, content: str):
        """Cache file content with metadata."""
        try:
            stat = os.stat(path)
            self._cache[path] = FileCacheEntry(
                path=path,
                content=content,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
        except OSError:
            pass

    def is_modified(self, path: str) -> bool:
        """Check if file has been modified since cached."""
        if path not in self._cache:
            return True
        
        try:
            current_stat = os.stat(path)
            cached = self._cache[path]
            return current_stat.st_mtime > cached.mtime or current_stat.st_size != cached.size
        except OSError:
            return True

    def invalidate(self, path: str):
        """Invalidate cached file."""
        self._cache.pop(path, None)

    def invalidate_pattern(self, pattern: str):
        """Invalidate cached files matching pattern."""
        import fnmatch
        to_remove = [p for p in self._cache if fnmatch.fnmatch(p, pattern)]
        for p in to_remove:
            self._cache.pop(p, None)

    def invalidate_dir(self, dir_path: str):
        """Invalidate all cached files in a directory."""
        dir_path = str(Path(dir_path).resolve())
        to_remove = [p for p in self._cache if str(Path(p).resolve()).startswith(dir_path)]
        for p in to_remove:
            self._cache.pop(p, None)

    def get_or_read(self, path: str, force_refresh: bool = False) -> tuple[str, bool]:
        """Get file content, re-reading if modified.
        
        Returns (content, was_refreshed).
        """
        path = str(Path(path).resolve())
        
        if force_refresh:
            self.invalidate(path)
        
        if not self.is_modified(path):
            cached = self._cache.get(path)
            if cached:
                cached.access_count += 1
                return cached.content, False
        
        try:
            content = Path(path).read_text()
            self.set(path, content)
            return content, True
        except Exception as e:
            cached = self._cache.get(path)
            if cached:
                return cached.content, False
            raise

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total_size = sum(len(e.content) for e in self._cache.values())
        return {
            "cached_files": len(self._cache),
            "total_content_size": total_size,
            "files": [
                {
                    "path": e.path,
                    "size": e.size,
                    "mtime": datetime.fromtimestamp(e.mtime).isoformat(),
                    "access_count": e.access_count,
                }
                for e in self._cache.values()
            ],
        }

    def clear(self):
        """Clear all cached files."""
        self._cache.clear()

    def save_index(self, path: str = None):
        """Save cache index to file."""
        path = path or os.path.join(self._cache_dir, "file_index.json")
        import json
        data = {
            path: {
                "mtime": entry.mtime,
                "size": entry.size,
                "cached_at": entry.cached_at.isoformat(),
            }
            for path, entry in self._cache.items()
        }
        with open(path, "w") as f:
            json.dump(data, f)

    def load_index(self, path: str = None) -> bool:
        """Load cache index from file. Returns True if loaded."""
        path = path or os.path.join(self._cache_dir, "file_index.json")
        if not os.path.exists(path):
            return False
        
        import json
        try:
            with open(path) as f:
                data = json.load(f)
            
            for path_str, info in data.items():
                if os.path.exists(path_str):
                    current_mtime = os.stat(path_str).st_mtime
                    if current_mtime == info.get("mtime"):
                        content = Path(path_str).read_text()
                        self.set(path_str, content)
            return True
        except Exception:
            return False
