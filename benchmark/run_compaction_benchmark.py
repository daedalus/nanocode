#!/usr/bin/env python3
"""Run benchmark that TRIGGERS compaction.

Tests with messages approaching/exceeding context limit to force
compaction to actually run and extract topics.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/dclavijo/my_code/nanocode")

from nanocode.context import ContextManager, ContextStrategy, TokenCounter
from nanocode.storage.topic_cache import TopicCache


def create_long_conversation(count: int) -> list[dict]:
    """Create realistic long conversation that will trigger compaction."""
    base_messages = [
        {"role": "user", "content": "Read /home/dclavijo/my_code/nanocode/nanocode/context.py and tell me how compaction works"},
        {"role": "assistant", "content": "The context.py file has ContextManager class with multiple strategies. Compaction triggers when tokens >= usable_context. It summarizes old messages into a single summary message."},
        {"role": "tool", "content": "File context.py: 994 lines, contains ContextManager, Message, MessagePart classes"},
        {"role": "user", "content": "What about the sliding window strategy?"},
        {"role": "assistant", "content": "The _sliding_window method keeps recent messages up to max_tokens. It iterates backwards and adds messages until token limit is reached."},
    ]

    content_patterns = [
        "Let me check the codebase for that function using grep.",
        "I found it in {} lines of code. The implementation does X.",
        "The file has been modified. Here's what changed: {}",
        "Let me read the imports to understand the dependencies.",
        "The function returns a dict with performance metrics.",
        "You can configure this in config.yaml under the {} section.",
        "The model supports multiple providers: OpenAI, Anthropic, Ollama.",
        "Let me write a test for this functionality.",
        "The error was caused by a missing import in line {}.",
        "I've updated the system prompt with new instructions.",
    ]

    patterns = [
        "nanocode/core.py",
        "nanocode/context.py",
        "nanocode/storage/cache.py",
        "nanocode/llm/base.py",
        "nanocode/tools/builtin/snapshot.py",
    ]

    messages = base_messages.copy()

    for i in range(count - len(base_messages)):
        pattern_idx = i % len(content_patterns)
        content = content_patterns[pattern_idx].format(patterns[i % len(patterns)])
        messages.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": content * 3,
        })

    return messages[:count]


def evaluate_with_compaction(strategy: ContextStrategy, message_count: int, context_limit: int = 10000) -> dict:
    """Evaluate strategy when compaction is triggered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        messages = create_long_conversation(message_count)

        manager = ContextManager(
            max_tokens=context_limit,
            strategy=strategy,
            model="claude-3-5-sonnet",
            preserve_last_n=3,
        )
        manager.set_system_prompt("You are a helpful coding assistant." * 20)

        for msg in messages:
            manager.add_message(msg["role"], msg["content"])

        total_input = sum(TokenCounter.count_tokens(m["content"]) for m in messages)

        result = manager.prepare_messages()
        usage = manager.get_token_usage()

        output_msgs = [m for m in result if m.get("role") not in ("system",)]
        system_msgs = [m for m in result if m.get("role") == "system"]

        has_summary = any("summary" in m.get("content", "").lower() or "topic" in m.get("content", "").lower() for m in system_msgs)

        return {
            "strategy": strategy.value,
            "input_messages": message_count,
            "input_tokens": total_input,
            "output_messages": len(output_msgs),
            "output_system_msgs": len(system_msgs),
            "usage_percent": round(usage["usage_percent"], 1),
            "compaction_triggered": has_summary,
            "retention_pct": round(len(output_msgs) / message_count * 100, 1),
        }


def run_compaction_benchmark():
    """Run benchmark that forces compaction."""
    results = {
        "strategies": [],
        "compaction_comparison": [],
    }

    message_counts = [50, 100, 200]

    strategies_to_test = [
        ContextStrategy.SLIDING_WINDOW,
        ContextStrategy.SUMMARY,
        ContextStrategy.COMPACTION,
        ContextStrategy.TOPIC_ID,
    ]

    for msg_count in message_counts:
        print(f"\n=== Testing with {msg_count} messages (context limit: 10000) ===")

        for strategy in strategies_to_test:
            print(f"  {strategy.value}...", end=" ")
            result = evaluate_with_compaction(strategy, msg_count)
            print(f"output:{result['output_messages']} retention:{result['retention_pct']}% compaction:{result['compaction_triggered']}")
            results["strategies"].append(result)

        results["compaction_comparison"].append({
            "message_count": msg_count,
            "strategies": {s.value: evaluate_with_compaction(s, msg_count) for s in strategies_to_test}
        })

    return results


def test_topic_id_compaction_detail():
    """Detailed test of topic-ID compaction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        messages = create_long_conversation(100)
        total_tokens = sum(TokenCounter.count_tokens(m["content"]) for m in messages)

        print(f"\n=== Topic-ID Detail ===")
        print(f"  Input: 100 messages, {total_tokens} tokens")

        topic_ids = []
        for i, msg in enumerate(messages[:50]):
            topic_id = cache.put(f"Message {i}: {msg['content'][:100]}", msg["role"])
            if i < 5 or i % 10 == 0:
                topic_ids.append(topic_id)

        print(f"  Topics stored: {cache.stats['topic_count']}")
        print(f"  Cache size: {len(list(cache.storage_dir.glob('*.json')))} files")

        summary = "[Previous conversation]\n"
        for tid in topic_ids[:10]:
            content = cache.get_content(tid)
            summary += f"- {tid}: {content[:50]}...\n"

        summary_tokens = TokenCounter.count_tokens(summary)
        print(f"  Summary tokens: {summary_tokens}")
        print(f"  Original tokens: {total_tokens}")
        print(f"  Compression: {round((1 - summary_tokens/total_tokens) * 100, 1)}%")

        return {
            "topics_stored": cache.stats["topic_count"],
            "summary_tokens": summary_tokens,
            "compression_pct": round((1 - summary_tokens/total_tokens) * 100, 1),
        }


def main():
    print("=" * 60)
    print("COMPACTION BENCHMARK (triggers actual compaction)")
    print("=" * 60)

    results = run_compaction_benchmark()

    topic_detail = test_topic_id_compaction_detail()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for conv in results["compaction_comparison"]:
        msg_count = conv["message_count"]
        print(f"\n{msg_count} messages:")
        for name, data in conv["strategies"].items():
            compaction_flag = "YES" if data["compaction_triggered"] else "no"
            print(f"  {name:20} retained:{data['retention_pct']:5.1f}% compaction:{compaction_flag}")

    output_file = "/home/dclavijo/my_code/nanocode/compaction-benchmark.json"
    with open(output_file, "w") as f:
        json.dump({**results, "topic_detail": topic_detail}, f, indent=2)
    print(f"\nSaved to: {output_file}")


if __name__ == "__main__":
    main()