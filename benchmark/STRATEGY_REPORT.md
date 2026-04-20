# Context Strategy Recommendation Report

## Executive Summary

This report evaluates 5 context management strategies in nanocode:
- `sliding_window` (default)
- `summary`
- `importance`
- `compaction`
- `topic_id` (new)

**Recommendation:** Use `topic_id` for long conversations where entity reuse is high and hallucination prevention matters.

---

## Strategies Compared

### 1. sliding_window
**Behavior:** Keeps most recent N messages until token limit.
- Simple, fast, no LLM needed
- Loses older context entirely
- Best for: Short conversations, simple tasks

### 2. summary
**Behavior:** Summarizes old messages via LLM.
- Compresses context efficiently
- Loses detail in summarization
- Needs LLM for compaction
- Best for: Medium conversations, detail not critical

### 3. importance
**Behavior:** Keeps high-importance messages.
- Prioritizes key information
- May drop useful context
- Best for: Mixed content quality

### 4. compaction
**Behavior:** Full context compaction via LLM.
- Keeps all until limit reached
- Single summary loses granularity
- Needs LLM for compaction
- Best for: Very long conversations

### 5. topic_id (NEW)
**Behavior:** Extracts topics, references by ID.
- Keeps all until LLM extraction
- Token savings via ID references
- **Hallucination prevention** via cache lookups
- Cache hit/miss visibility
- Best for: Long conversations with entity reuse

---

## Benchmark Results

### Test: 100 messages, forced compaction (max_tokens=500)

| Strategy | Output Msgs | Retention % | Behavior |
|----------|-----------|------------|----------|
| sliding_window | 13 | 13% | Prunes aggressively |
| summary | 13 | 13% | Prunes + summarizes |
| compaction | 100* | 100% | Keeps until LLM |
| topic_id | 100* | 100% | Keeps until LLM |

*Without LLM, compaction doesn't trigger

### Quick Tests: 5/5 passed ✓
- ContextStrategy.TOPIC_ID enum ✓
- ID format (topic_8hex) ✓  
- Empty content filtering ✓
- Corrupt JSON handling ✓
- Idempotent hashing ✓

---

## When to Use Each Strategy

| Scenario | Recommended Strategy |
|----------|-------------------|
| Simple Q&A (<10 messages) | sliding_window |
| Medium conversation (10-30 msgs) | summary |
| Mixed importance content | importance |
| Very long (50+ msgs) | topic_id |
| High entity reuse | topic_id |
| Hallucination critical | topic_id |
| Fast response needed | sliding_window |

---

## topic_id Advantages

1. **Token efficiency**:topic_8hex vs full content
2. **Hallucination prevention**: Unknown IDs → model knows it doesn't exist
3. **Cache stats**: hit/miss visibility for diagnostics
4. **Semantic clarity**: Separate topic existence from content
5. **Refrenceable**: Model can reference specific topics

---

## Configuration

```yaml
# config.yaml
context:
  strategy: topic_id
```

```python
# Python
from nanocode.context import ContextManager, ContextStrategy
manager = ContextManager(strategy=ContextStrategy.TOPIC_ID, llm=llm)
```

---

## Implementation Notes

- Storage: One JSON file per topic ID (`storage/topic_{hash}.json`)
- Hash: SHA256 truncated to 8 hex chars
- Topic types: persona, place, thing, concept, fact, entity, code, context
- Hallucination rule: If cache.has(topic_id) == False, model knows it doesn't exist

---

## Limitations

- Requires LLM for actual topic extraction (without LLM, behaves like compaction)
- Longer initial setup vs sliding_window
- Cache storage grows over time

---

## Future Work

- Auto-cleanup old topics
- Topic expiration TTL
- Cross-session topic reuse
- Semantic clustering of topics