#!/usr/bin/env python3
"""Run context strategy benchmark."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/dclavijo/my_code/nanocode")

from nanocode.context import ContextManager, ContextStrategy, TokenCounter
from nanocode.storage.topic_cache import TopicCache


def create_test_messages(count: int) -> list[dict]:
    """Create realistic test messages."""
    messages = [
        {"role": "user", "content": "Read the file /home/dclavijo/my_code/nanocode/README.md"},
        {"role": "assistant", "content": "I read the file. It's a CLI coding agent with multi-provider LLM support."},
        {"role": "tool", "content": "File has 150 lines of documentation."},
        {"role": "user", "content": "What tools does it have?"},
        {"role": "assistant", "content": "It has bash, read, write, edit, glob, grep, and more tools."},
    ]

    for i in range(count - 5):
        messages.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Message {i} with some content to simulate a real conversation flow." * (1 + i % 3),
        })

    return messages[:count]


def evaluate_strategy(strategy: ContextStrategy, messages: list[dict], max_tokens: int = 8000) -> dict:
    """Evaluate a single strategy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ContextManager(
            max_tokens=max_tokens,
            strategy=strategy,
            model="claude-3-5-sonnet",
        )
        manager.set_system_prompt("You are a coding assistant.")

        for msg in messages:
            manager.add_message(msg["role"], msg["content"])

        result = manager.prepare_messages()
        usage = manager.get_token_usage()

        return {
            "strategy": strategy.value,
            "input_tokens": usage["current_tokens"],
            "max_tokens": usage["max_tokens"],
            "usage_percent": round(usage["usage_percent"], 1),
            "message_count": len([m for m in result if m.get("role") not in ("system",)]),
            "output_count": len(result),
        }


def run_benchmark() -> dict:
    """Run full benchmark."""
    strategies = [
        ContextStrategy.SLIDING_WINDOW,
        ContextStrategy.SUMMARY,
        ContextStrategy.IMPORTANCE,
        ContextStrategy.COMPACTION,
        ContextStrategy.TOPIC_ID,
    ]

    lengths = [5, 20, 50]
    results = {"strategies": [], "conversations": []}

    for length in lengths:
        messages = create_test_messages(length)
        conv_result = {"length": length, "results": {}}

        for strategy in strategies:
            print(f"  Testing {strategy.value} with {length} messages...")
            eval_result = evaluate_strategy(strategy, messages)
            conv_result["results"][strategy.value] = eval_result
            results["strategies"].append(eval_result)

        results["conversations"].append(conv_result)

    return results


def test_topic_cache() -> dict:
    """Test topic cache functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        id1 = cache.put("Test content for eval", "fact")
        retrieved = cache.get_content(id1)
        has_fake = cache.has("topic_deadbeef")

        return {
            "topic_store_works": retrieved == "Test content for eval",
            "hallucination_prevention": has_fake is False,
        }


def main():
    print("=" * 60)
    print("Context Strategy Benchmark")
    print("=" * 60)

    results = run_benchmark()

    print("\n" + "=" * 60)
    print("Topic Cache Tests")
    print("=" * 60)
    cache_results = test_topic_cache()
    for k, v in cache_results.items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    for conv in results["conversations"]:
        print(f"\n{conv['length']} messages:")
        for name, data in conv["results"].items():
            print(f"  {name:20} tokens:{data['input_tokens']:5} usage:{data['usage_percent']:5.1f}% msgs:{data['message_count']}")

    output_file = "/home/dclavijo/my_code/nanocode/topic-id-compaction-benchmark.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to: {output_file}")

    return results


if __name__ == "__main__":
    main()