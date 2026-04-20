"""
Topic-ID based context compaction system.

Each topic gets a unique ID (hash) and is stored in a separate JSON file.
References use topic_{ID} format to save tokens.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("nanocode.topic_cache")


@dataclass
class Topic:
    """A topic with ID and content."""

    id: str
    content: str
    topic_type: str = "general"
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "topic_type": self.topic_type,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Topic":
        return cls(
            id=data["id"],
            content=data["content"],
            topic_type=data.get("topic_type", "general"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
            metadata=data.get("metadata", {}),
        )


class TopicCache:
    """File-based topic cache - one JSON file per topic ID.

    Storage structure:
        storage/
            topic_{8charhash}.json

    Each file contains:
        {
            "id": "topic_abc12345",
            "content": "...",
            "topic_type": "persona|fact|entity|place|concept|...",
            "created_at": "2024-01-01T00:00:00",
            "metadata": {}
        }
    """

    def __init__(self, storage_dir: str | Path | None = None, hash_length: int = 8):
        self.storage_dir = Path(storage_dir or "storage")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.hash_length = hash_length
        self._hits = 0
        self._misses = 0

    def _compute_id(self, content: str) -> str:
        """Compute topic ID from content using SHA256 hash."""
        hash_obj = hashlib.sha256(content.encode())
        hash_hex = hash_obj.hexdigest()[: self.hash_length]
        return f"topic_{hash_hex}"

    def put(self, content: str, topic_type: str = "general", metadata: dict = None) -> str:
        """Store topic and return its ID."""
        if not content or not content.strip():
            logger.debug("Skipping empty content")
            return self._compute_id("")

        topic_id = self._compute_id(content)
        filepath = self._get_filepath(topic_id)

        if not filepath.exists():
            topic = Topic(
                id=topic_id,
                content=content,
                topic_type=topic_type,
                metadata=metadata or {},
            )
            with open(filepath, "w") as f:
                json.dump(topic.to_dict(), f, indent=2)
            logger.debug(f"Stored topic: {topic_id}")

        return topic_id

    def get(self, topic_id: str) -> Topic | None:
        """Get topic by ID, or None if not found."""
        filepath = self._get_filepath(topic_id)

        if filepath.exists():
            try:
                self._hits += 1
                with open(filepath) as f:
                    return Topic.from_dict(json.load(f))
            except (json.JSONDecodeError, IOError) as e:
                logger.debug(f"Failed to load topic {topic_id}: {e}")
                return None

        self._misses += 1
        return None

    def get_content(self, topic_id: str) -> str | None:
        """Get topic content directly, or None if not found."""
        topic = self.get(topic_id)
        return topic.content if topic else None

    def has(self, topic_id: str) -> bool:
        """Check if topic exists in cache."""
        return self._get_filepath(topic_id).exists()

    def _get_filepath(self, topic_id: str) -> Path:
        """Get filepath for topic ID."""
        return self.storage_dir / f"{topic_id}.json"

    @property
    def stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_lookups": total,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "topic_count": len(list(self.storage_dir.glob("topic_*.json"))),
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters."""
        self._hits = 0
        self._misses = 0

    def list_topics(self, topic_type: str = None) -> list[Topic]:
        """List all topics, optionally filtered by type."""
        topics = []
        for filepath in self.storage_dir.glob("topic_*.json"):
            with open(filepath) as f:
                topic = Topic.from_dict(json.load(f))
                if topic_type is None or topic.topic_type == topic_type:
                    topics.append(topic)
        return topics

    def clear(self) -> None:
        """Clear all topics from cache."""
        for filepath in self.storage_dir.glob("topic_*.json"):
            filepath.unlink()
        self.reset_stats()
        logger.info("Topic cache cleared")


_default_cache: TopicCache | None = None


def get_topic_cache(storage_dir: str | Path = "storage") -> TopicCache:
    """Get the global topic cache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = TopicCache(storage_dir)
    return _default_cache