"""Tests for topic-ID compaction."""

import json
import tempfile
from pathlib import Path

from nanocode.storage.topic_cache import TopicCache, Topic


def test_topic_cache_basic():
    """Test basic put/get operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        topic_id = cache.put("This is a test topic", "concept")
        assert topic_id.startswith("topic_")
        assert len(topic_id) == 14

        retrieved = cache.get(topic_id)
        assert retrieved is not None
        assert retrieved.content == "This is a test topic"
        assert retrieved.topic_type == "concept"


def test_topic_cache_stats():
    """Test cache statistics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        id1 = cache.put("Topic 1", "persona")
        id2 = cache.put("Topic 2", "fact")
        id3 = cache.put("Topic 3", "place")

        stats = cache.stats
        assert stats["hits"] == 0
        assert stats["topic_count"] == 3

        cache.get(id1)
        cache.get(id2)

        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 0


def test_topic_cache_missing():
    """Test missing topic returns None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        result = cache.get("topic_00000000")
        assert result is None


def test_topic_cache_has():
    """Test has() method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        assert cache.has("topic_12345678") is False

        cache.put("Some content", "concept")

        stored_id = cache.put("Some content", "concept")
        assert cache.has(stored_id) is True


def test_list_topics():
    """Test listing topics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        cache.put("Persona 1", "persona")
        cache.put("Fact 1", "fact")
        cache.put("Fact 2", "fact")
        cache.put("Place 1", "place")

        all_topics = cache.list_topics()
        assert len(all_topics) == 4

        persona_topics = cache.list_topics("persona")
        assert len(persona_topics) == 1

        fact_topics = cache.list_topics("fact")
        assert len(fact_topics) == 2


def test_deterministic_id():
    """Test same content produces same ID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        content = "Same content"
        id1 = cache.put(content, "concept")
        id2 = cache.put(content, "concept")

        assert id1 == id2


def test_file_format():
    """Test JSON file format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        topic_id = cache.put("Test content", "entity", {"key": "value"})
        filepath = cache._get_filepath(topic_id)

        assert filepath.exists()

        with open(filepath) as f:
            data = json.load(f)

        assert data["id"] == topic_id
        assert data["content"] == "Test content"
        assert data["topic_type"] == "entity"
        assert data["metadata"]["key"] == "value"


def test_empty_content():
    """Test empty content is filtered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        id1 = cache.put("", "fact")
        id2 = cache.put("   ", "fact")

        assert id1 == "topic_e3b0c442"
        retrieved = cache.get_content(id1)
        assert retrieved is None


def test_get_none_on_corrupt_json():
    """Test get returns None on corrupt JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        id1 = cache.put("Valid content", "fact")
        filepath = cache._get_filepath(id1)

        with open(filepath, "w") as f:
            f.write("{ corrupt json")

        result = cache.get(id1)
        assert result is None


def test_context_strategy_enum():
    """Test TOPIC_ID strategy exists."""
    from nanocode.context import ContextStrategy

    assert ContextStrategy.TOPIC_ID is not None
    assert ContextStrategy.TOPIC_ID.value == "topic_id"