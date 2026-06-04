"""Tests for topic extraction from conversation messages.

The topic_extractor module imports `topic_cache` which may not be installed.
Tests mock it at import time via sys.modules and importlib hooks.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_topic_cache():
    """Mock the topic_cache module before any imports."""
    import sys
    mock_cache_module = MagicMock()
    mock_cache_module.TopicCache = MagicMock
    mock_cache_module.get_topic_cache = MagicMock(return_value=MagicMock())
    sys.modules["topic_cache"] = mock_cache_module
    yield
    if "topic_cache" in sys.modules:
        del sys.modules["topic_cache"]


class TestExtractedTopic:
    """Test ExtractedTopic dataclass."""

    def test_creation(self):
        """Test ExtractedTopic creation."""
        from nanocode.storage.topic_extractor import ExtractedTopic

        topic = ExtractedTopic(description="user likes Python", topic_type="fact")
        assert topic.description == "user likes Python"
        assert topic.topic_type == "fact"


class TestTopicExtractor:
    """Test TopicExtractor."""

    def test_init_no_llm(self):
        """Test TopicExtractor can be created without LLM."""
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        assert extractor.llm is None

    def test_init_with_llm(self):
        """Test TopicExtractor with LLM."""
        from nanocode.storage.topic_extractor import TopicExtractor

        llm = MagicMock()
        cache = MagicMock()
        extractor = TopicExtractor(llm=llm, cache=cache)
        assert extractor.llm is llm
        assert extractor.cache is cache

    def test_topic_types(self):
        """Test TOPIC_TYPES contains expected categories."""
        from nanocode.storage.topic_extractor import TOPIC_TYPES

        assert "persona" in TOPIC_TYPES
        assert "code" in TOPIC_TYPES
        assert "fact" in TOPIC_TYPES

    def test_extract_topics_no_llm(self):
        """Test extract_topics returns empty when no LLM."""
        import asyncio
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        result = asyncio.run(extractor.extract_topics([{"role": "user", "content": "hello"}]))
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_topics_with_llm(self):
        """Test extract_topics calls LLM and parses response."""
        from unittest.mock import AsyncMock
        from nanocode.storage.topic_extractor import TopicExtractor

        llm = MagicMock()
        response_mock = MagicMock()
        response_mock.content = '[{"description": "Python", "type": "code"}]'
        llm.chat = AsyncMock(return_value=response_mock)
        cache = MagicMock()
        cache.put.return_value = "topic_hash"

        extractor = TopicExtractor(llm=llm, cache=cache)
        result = await extractor.extract_topics([{"role": "user", "content": "I love Python"}])

        llm.chat.assert_called_once()
        cache.put.assert_called_once_with("Python", "code")
        assert result == ["topic_hash"]

    @pytest.mark.asyncio
    async def test_extract_topics_llm_error(self):
        """Test extract_topics handles LLM errors gracefully."""
        from nanocode.storage.topic_extractor import TopicExtractor

        llm = MagicMock()
        llm.chat = MagicMock(side_effect=Exception("API error"))
        extractor = TopicExtractor(llm=llm)
        result = await extractor.extract_topics([{"role": "user", "content": "hi"}])
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_topics_invalid_json(self):
        """Test extract_topics handles invalid JSON response."""
        from nanocode.storage.topic_extractor import TopicExtractor

        llm = MagicMock()
        llm.chat = MagicMock(return_value={"content": "not valid json"})
        extractor = TopicExtractor(llm=llm)
        result = await extractor.extract_topics([{"role": "user", "content": "hi"}])
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_topics_unknown_type(self):
        """Test extract_topics filters unknown topic types."""
        from nanocode.storage.topic_extractor import TopicExtractor

        llm = MagicMock()
        llm.chat = MagicMock(return_value={
            "content": '[{"description": "stuff", "type": "unknown_category"}]'
        })
        cache = MagicMock()
        extractor = TopicExtractor(llm=llm, cache=cache)
        result = await extractor.extract_topics([{"role": "user", "content": "hi"}])
        assert result == []
        cache.put.assert_not_called()

    def test_extract_topics_sync(self):
        """Test synchronous topic extraction."""
        from nanocode.storage.topic_extractor import TopicExtractor

        cache = MagicMock()
        cache.put.return_value = "topic_hash"
        extractor = TopicExtractor(cache=cache)
        messages = [{"role": "user", "content": "check this file /path/to/config"}]
        result = extractor.extract_topics_sync(messages)
        assert len(result) > 0

    def test_format_messages(self):
        """Test _format_messages formats correctly."""
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi there"}]
        result = extractor._format_messages(messages)
        assert "user: hello" in result
        assert "assistant: hi there" in result

    def test_format_messages_skip_empty(self):
        """Test _format_messages skips messages with no content."""
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": ""}]
        result = extractor._format_messages(messages)
        assert "assistant:" not in result

    def test_format_messages_limit(self):
        """Test _format_messages limits to last 20 messages."""
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        messages = [{"role": "user", "content": f"msg_{i}"} for i in range(30)]
        result = extractor._format_messages(messages)
        assert result.count("user:") == 20

    def test_parse_response_valid(self):
        """Test _parse_response parses JSON array."""
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        result = extractor._parse_response('[{"description": "test", "type": "code"}]')
        assert len(result) == 1
        assert result[0]["description"] == "test"

    def test_parse_response_invalid(self):
        """Test _parse_response returns empty on invalid JSON."""
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        result = extractor._parse_response("not json")
        assert result == []

    def test_parse_response_embedded(self):
        """Test _parse_response extracts JSON from surrounding text."""
        from nanocode.storage.topic_extractor import TopicExtractor

        extractor = TopicExtractor()
        result = extractor._parse_response(
            'Here:\n[{"description": "test", "type": "code"}]\nDone.'
        )
        assert len(result) == 1
