"""
Prompt caching system for avoiding redundant LLM calls.

This module provides persistent caching of LLM responses to reduce API costs and improve
response times for repeated or similar prompts.

Architecture:
    - BloomFilter: Probabilistic set membership checker for fast negative lookups
    - SQLiteCache: Generic SQLite-backed cache with bloom filter pre-filtering
    - PromptCache: LLM-specific cache using SHA256 hash of messages as key

Cache Behavior:
    - When --cache flag is enabled, responses are cached based on message hash
    - Cache key includes FULL message history (system + user + assistant)
    - Each new conversation generates a new cache key (different history)
    - Caching works within multi-turn sessions where message history is identical

Important Notes:
    - The cache key is derived from the complete message history, not just the prompt
    - Running `nanocode --prompt "..." --cache` multiple times will NOT hit cache
      because each invocation creates a new session with different system messages
    - For multi-turn conversations in CLI mode, caching works if messages stay the same
    - This is different from provider-level caching (e.g., Anthropic's cacheControl)
      which caches system prompts automatically

To clear the cache:
    agent.clear_cache()  # via Python API
    # Or delete ~/.nanocode/cache/prompt_cache.db directly
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("nanocode.cache")


class BloomFilter:
    """Fast probabilistic duplicate checker using bloom filter.

    Provides O(1) membership testing with configurable false positive rate.
    Used as a pre-filter before SQLite lookups to avoid expensive DB queries
    for non-existent keys.

    Note: False positives are possible (item reported as in set when it may not be),
    but false negatives are impossible (if reported as not in set, it's definitely not).
    """

    def __init__(self, capacity: int = 100000, false_positive_rate: float = 0.01):
        self.size = self._optimal_size(capacity, false_positive_rate)
        self.hash_count = self._optimal_hash_count(capacity, self.size)
        self.array = [False] * self.size

    def _optimal_size(self, n: int, p: float) -> int:
        return int(-n * math.log(p) / (math.log(2) ** 2))

    def _optimal_hash_count(self, n: int, m: int) -> int:
        return max(1, int((m / n) * math.log(2)))

    def _hashes(self, item: str) -> list:
        result = []
        for i in range(self.hash_count):
            h = hashlib.md5((item + str(i)).encode()).hexdigest()
            result.append(int(h, 16) % self.size)
        return result

    def add(self, item: str):
        for idx in self._hashes(item):
            self.array[idx] = True

    def __contains__(self, item: str) -> bool:
        return all(self.array[idx] for idx in self._hashes(item))

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(
                {
                    "array_size": self.size,
                    "hash_count": self.hash_count,
                    "array": self.array,
                },
                f,
            )

    @classmethod
    def load(cls, path: str) -> "BloomFilter":
        if not os.path.exists(path):
            return cls()
        with open(path, "r") as f:
            data = json.load(f)
        bf = cls.__new__(cls)
        bf.size = data["array_size"]
        bf.hash_count = data["hash_count"]
        bf.array = data["array"]
        return bf


class SQLiteCache:
    """Generic SQLite cache with bloom filter for fast pre-filtering.

    Combines a bloom filter (for quick negative lookups) with SQLite (for persistent storage).
    The bloom filter provides fast "probably exists" checks before expensive DB queries.

    Architecture:
        - In-memory BloomFilter for O(1) pre-filtering
        - SQLite for persistent key-value storage
        - JSON serialization for complex values

    Args:
        db_path: Path to SQLite database file
        table: Table name for key-value pairs
        key_col: Column name for keys
        value_col: Column name for serialized values
        key_hash: Optional custom hash function for keys
    """

    def __init__(
        self,
        db_path: Path,
        table: str,
        key_col: str,
        value_col: str,
        key_hash: Callable[[str], str] | None = None,
    ) -> None:
        self.db_path = db_path
        self.bloom_path = str(db_path) + ".bloom"
        self.table = table
        self.key_col = key_col
        self.value_col = value_col
        self.key_hash = key_hash or (lambda x: x)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._key_set: set[str] = set()
        self._hits = 0
        self._misses = 0
        self.bloom = BloomFilter()
        self._initialize()
        self._load()
        logger.info("Cache initialized: %s", db_path)

    def _initialize(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                {self.key_col} TEXT PRIMARY KEY,
                {self.value_col} TEXT NOT NULL
            )
        """)
        self._conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.key_col} ON {self.table}({self.key_col})
        """)
        self._conn.commit()

    def _load(self) -> None:
        cursor = self._conn.execute(f"SELECT {self.key_col} FROM {self.table}")
        self._key_set = {row[0] for row in cursor.fetchall()}
        if self._key_set and os.path.exists(self.bloom_path):
            self.bloom = BloomFilter.load(self.bloom_path)
        else:
            self.bloom = BloomFilter(capacity=max(1000, len(self._key_set) * 10))
            for k in self._key_set:
                self.bloom.add(k)

    def flush(self) -> None:
        self._conn.commit()
        self.bloom.save(self.bloom_path)

    @property
    def stats(self) -> dict:
        return {"hits": self._hits, "misses": self._misses}

    def reset_stats(self) -> None:
        self._hits = 0
        self._misses = 0

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def _compute_hash(self, key: str) -> str:
        """Compute hash for key. Override in subclasses."""
        return self.key_hash(key)

    @property
    def _hash_set(self) -> set[str]:
        """Access internal key set (for tests)."""
        return self._key_set

    def get(self, key: str) -> Any | None:
        """Get cached value for key, or None if not cached."""
        cache_key = self.key_hash(key)

        if cache_key in self.bloom:
            if cache_key in self._key_set:
                cursor = self._conn.execute(
                    f"SELECT {self.value_col} FROM {self.table} WHERE {self.key_col} = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                if row:
                    return json.loads(row[self.value_col])
            return None

        return None

    def put(self, key: str, value: Any) -> None:
        """Store key → value mapping."""
        cache_key = self.key_hash(key)
        self._key_set.add(cache_key)
        value_json = json.dumps(value)
        try:
            self._conn.execute(
                f"INSERT INTO {self.table} ({self.key_col}, {self.value_col}) VALUES (?, ?)",
                (cache_key, value_json),
            )
        except sqlite3.IntegrityError:
            return

        self.bloom.add(cache_key)

    def close(self) -> None:
        self.flush()
        self._conn.close()

    def clear(self) -> None:
        """Clear all cached entries."""
        self._conn.execute(f"DELETE FROM {self.table}")
        self._conn.commit()
        self._key_set.clear()
        self.bloom = BloomFilter(capacity=10000)
        if os.path.exists(self.bloom_path):
            os.remove(self.bloom_path)
        logger.info("Cache cleared: %s", self.db_path)


@dataclass
class CachedResponse:
    """A cached LLM response.

    Represents a stored response from the LLM that can be retrieved on cache hit.

    Attributes:
        content: The text content of the response
        thinking: Reasoning/thinking content (if present)
        tool_calls: List of tool calls to execute (if any)
        model: Model used to generate the response
    """

    content: str
    thinking: str | None = None
    tool_calls: list[dict] | None = None
    model: str | None = None


class PromptCache(SQLiteCache):
    """Persistent cache for LLM prompt responses indexed by prompt hash.

    Stores complete LLM responses (content + thinking + tool_calls) keyed on SHA256 hash
    of the full message history. Uses bloom filter + SQLite for efficient lookups.

    Cache Key Generation:
        The key is SHA256(JSON(messages + tools)), which means:
        - Different message sequences → different keys
        - Identical multi-turn sessions → cache hits

    Storage:
        - Default location: ~/.nanocode/cache/prompt_cache.db
        - Can be overridden via config: cache.dir or cache_path in constructor

    Example:
        >>> cache = PromptCache()  # Uses default location
        >>> cache.put(key, CachedResponse(content="Hello!", thinking="..."))
        >>> result = cache.get(key)
        >>> if result:
        ...     print(result.content)  # "Hello!"

    Note on Provider Caching:
        This is APPLICATION-LEVEL caching, different from provider-native caching
        (e.g., Anthropic's cacheControl). Provider caching is handled in the
        LLM SDK layer. This cache is for application-level deduplication.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        cache_dir = db_path or Path.home() / ".nanocode" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            cache_dir / "prompt_cache.db",
            "prompt_responses",
            "prompt_hash",
            "response",
            key_hash=lambda x: hashlib.sha256(x.encode()).hexdigest(),
        )

    def get(self, prompt: str) -> CachedResponse | None:
        """Get cached response for prompt, or None if not cached."""
        result = super().get(prompt)
        if result is not None:
            self._hits += 1
            logger.debug("Prompt cache HIT: %s...", prompt[:50])
            return CachedResponse(**result)
        else:
            self._misses += 1
            logger.debug("Prompt cache MISS: %s...", prompt[:50])
        return None

    def put(self, prompt: str, response: CachedResponse) -> None:
        """Store prompt hash → response mapping."""
        data = {
            "content": response.content,
            "thinking": response.thinking,
            "tool_calls": response.tool_calls,
            "model": response.model,
        }
        super().put(prompt, data)
        logger.debug("Prompt cached: %s...", prompt[:50])

    def put_from_dict(self, prompt: str, response_dict: dict) -> None:
        """Store prompt from a response dict (like from LLM.chat)."""
        response = CachedResponse(
            content=response_dict.get("content", ""),
            thinking=response_dict.get("thinking"),
            tool_calls=response_dict.get("tool_calls"),
            model=response_dict.get("model"),
        )
        self.put(prompt, response)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        stats = super().stats
        stats["hit_rate"] = self.hit_rate
        stats["entries"] = len(self._key_set)
        return stats


_prompt_cache: PromptCache | None = None


def get_prompt_cache() -> PromptCache:
    """Get the global prompt cache instance."""
    global _prompt_cache
    if _prompt_cache is None:
        _prompt_cache = PromptCache()
    return _prompt_cache


def close_prompt_cache() -> None:
    """Close the global prompt cache."""
    global _prompt_cache
    if _prompt_cache is not None:
        _prompt_cache.close()
        _prompt_cache = None
