"""
Topic extraction from conversation messages.

Extracts topics (personas, places, things, concepts, facts, entities, code, etc.)
from messages during context compaction.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from topic_cache import TopicCache, get_topic_cache

TOPIC_TYPES = [
    "persona",    # User personas, agents, roles
    "place",      # File paths, directories, locations
    "thing",     # Tools, files, specific objects
    "concept",   # Ideas, patterns, abstractions
    "fact",      # True statements, historical info
    "entity",    # Named entities (URLs, IDs, etc.)
    "code",      # Code snippets, functions, classes
    "context",   # Conversation context, summaries
]


EXTRACTION_PROMPT = """Extract topics from this conversation. For each topic provide:
1. A brief description (key identifying info)
2. The topic type from: {topic_types}

Output as JSON array:
[
  {{"description": "...", "type": "persona"}},
  {{"description": "...", "type": "place"}},
  ...
]

Rules:
- Only extract topics that are referenced multiple times or are important
- Descriptions should be concise but uniquely identifying
- If no topics worth extracting, return []
- Do not hallucinate topics - if unsure, exclude
"""


@dataclass
class ExtractedTopic:
    """A topic extracted from conversation."""

    description: str
    topic_type: str


class TopicExtractor:
    """Extracts topics from messages using LLM."""

    def __init__(self, llm=None, cache: TopicCache = None):
        self.llm = llm
        self.cache = cache or get_topic_cache()

    async def extract_topics(self, messages: list[dict]) -> list[str]:
        """Extract topics from messages, store in cache, return topic IDs.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            List of topic IDs (topic_{hash} format)
        """
        if not self.llm:
            return []

        conversation = self._format_messages(messages)
        prompt = EXTRACTION_PROMPT.format(topic_types=", ".join(TOPIC_TYPES))
        full_prompt = f"{prompt}\n\nConversation:\n{conversation}"

        try:
            response = await self.llm.chat([{"role": "user", "content": full_prompt}])
            extracted = self._parse_response(response.content)
        except Exception as e:
            return []

        topic_ids = []
        for item in extracted:
            description = item.get("description", "")
            topic_type = item.get("type", "general")

            if description and topic_type in TOPIC_TYPES:
                topic_id = self.cache.put(description, topic_type)
                topic_ids.append(topic_id)

        return topic_ids

    def extract_topics_sync(self, messages: list[dict]) -> list[str]:
        """Synchronous wrapper (for non-async contexts)."""
        extracted = self._extract_sync_impl(messages)
        topic_ids = []
        for item in extracted:
            description = item.get("description", "")
            topic_type = item.get("type", "general")
            if description and topic_type in TOPIC_TYPES:
                topic_id = self.cache.put(description, topic_type)
                topic_ids.append(topic_id)
        return topic_ids

    def _extract_sync_impl(self, messages: list[dict]) -> list[dict]:
        """Implementation without LLM (manual extraction)."""
        topics = []
        seen_content = set()

        for msg in messages:
            content = msg.get("content", "")
            if not content or len(content) < 20:
                continue

            if "file" in content.lower() or "path" in content.lower():
                topics.append({"description": content[:100], "type": "place"})
            elif "function" in content.lower() or "def " in content:
                topics.append({"description": content[:100], "type": "code"})
            elif any(word in content.lower() for word in ["user", "person", "role"]):
                topics.append({"description": content[:100], "type": "persona"})

        return topics[:10]

    def _format_messages(self, messages: list[dict]) -> str:
        """Format messages for LLM prompt."""
        lines = []
        for msg in messages[-20:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                lines.append(f"{role}: {content[:500]}")
        return "\n".join(lines)

    def _parse_response(self, response: str) -> list[dict]:
        """Parse LLM response into topic list."""
        try:
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        return []