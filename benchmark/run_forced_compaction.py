#!/usr/bin/env python3
"""Run benchmark with FORCED compaction.

Sets max_tokens very low to force compaction to trigger.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/dclavijo/my_code/nanocode")

from nanocode.context import ContextManager, ContextStrategy, TokenCounter
from nanocode.storage.topic_cache import TopicCache


def create_messages(count: int) -> list[dict]:
    """Create test messages."""
    base = [
        {"role": "user", "content": "Read the context.py file"},
        {"role": "assistant", "content": "I read the file. It contains ContextManager class."},
        {"role": "tool", "content": "File has 1000 lines"},
        {"role": "user", "content": "What about sliding window?"},
        {"role": "assistant", "content": "The sliding window strategy keeps recent messages."},
    ]

    messages = base.copy()
    for i in range(count - len(base)):
        messages.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Message {i} with some content here. " * 5,
        })
    return messages[:count]


def force_compaction_test(strategy: ContextStrategy, msg_count: int, max_tokens: int = 500) -> dict:
    """Force compaction by setting very low max_tokens."""
    with tempfile.TemporaryDirectory() as tmpdir:
        messages = create_messages(msg_count)

        if strategy == ContextStrategy.TOPIC_ID:
            cache = TopicCache(tmpdir)
            storage = cache
        else:
            storage = None

        manager = ContextManager(
            max_tokens=max_tokens,
            strategy=strategy,
            preserve_last_n=2,
            model="claude-3-5-sonnet",
            storage=storage,
        )
        manager.set_system_prompt("System prompt here. " * 10)

        for msg in messages:
            manager.add_message(msg["role"], msg["content"])

        original_tokens = TokenCounter.count_tokens("\n".join(m["content"] for m in messages))

        result = manager.prepare_messages()
        usage = manager.get_token_usage()

        output_count = len([m for m in result if m.get("role") not in ("system",)])

        return {
            "strategy": strategy.value,
            "input_msgs": msg_count,
            "output_msgs": output_count,
            "original_tokens": original_tokens,
            "output_tokens": usage["current_tokens"],
            "usage_pct": usage["usage_percent"],
            "compaction": original_tokens > usage["current_tokens"],
        }


def main():
    print("=" * 60)
    print("FORCED COMPACTION (max_tokens=500)")
    print("=" * 60)

    msg_counts = [20, 50, 100]
    strategies = [
        ContextStrategy.SLIDING_WINDOW,
        ContextStrategy.SUMMARY,
        ContextStrategy.COMPACTION,
        ContextStrategy.TOPIC_ID,
    ]

    results = {"forced_compaction": []}

    for msg_count in msg_counts:
        print(f"\n{msg_count} messages (forced compaction):")
        conv_result = {"msg_count": msg_count, "strategies": {}}

        for strategy in strategies:
            r = force_compaction_test(strategy, msg_count, max_tokens=500)
            conv_result["strategies"][strategy.value] = r
            compaction = "COMPACTED" if r["compaction"] else "full"
            print(f"  {strategy.value:20} in:{r['input_msgs']:3}->out:{r['output_msgs']:3} toks:{r['original_tokens']:4}->{r['output_tokens']:4} [{compaction}]")

        results["forced_compaction"].append(conv_result)

    output_file = "/home/dclavijo/my_code/nanocode/forced-compaction-benchmark.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved to: {output_file}")


if __name__ == "__main__":
    main()