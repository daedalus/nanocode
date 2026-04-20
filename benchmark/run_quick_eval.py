#!/usr/bin/env python3
"""Run quick evaluation tests."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/dclavijo/my_code/nanocode")

from nanocode.context import ContextManager, ContextStrategy, TokenCounter
from nanocode.storage.topic_cache import TopicCache


def test_context_strategy_enum():
    """Test eval 12: Verify TOPIC_ID enum."""
    assert ContextStrategy.TOPIC_ID is not None
    assert ContextStrategy.TOPIC_ID.value == "topic_id"
    return {"passed": True, "value": ContextStrategy.TOPIC_ID.value}


def test_topic_format():
    """Test eval 19: Verify topic ID format."""
    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)
        ids = set()
        for i in range(100):
            tid = cache.put(f"Content {i}", "fact")
            ids.add(tid)

        all_match = all(tid.startswith("topic_") and len(tid) == 14 for tid in ids)
        hex_format = all("g" not in tid[7:] for tid in ids)

    return {"passed": all_match and hex_format, "ids_checked": len(ids)}


def test_empty_filtering():
    """Test eval 15: Empty content filtering."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        cache.put("", "fact")
        cache.put("   ", "fact")

        topics = cache.list_topics()

    return {"passed": len(topics) == 0, "topics_created": len(topics)}


def test_corrupt_json():
    """Test eval 14: Corrupt JSON handling."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        tid = cache.put("Valid", "fact")
        filepath = cache._get_filepath(tid)

        with open(filepath, "w") as f:
            f.write("{ broken")

        result = cache.get(tid)

    return {"passed": result is None, "result": result}


def test_idempotency():
    """Test eval 13: SHA256 deterministic."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        content = "Same content here"
        id1 = cache.put(content, "fact")
        id2 = cache.put(content, "persona")
        id3 = cache.put(content, "place")

    return {"passed": id1 == id2 == id3, "all_equal": id1 == id2 == id3}


def main():
    tests = [
        ("ContextStrategy.TOPIC_ID enum", test_context_strategy_enum),
        ("ID format (topic_8hex)", test_topic_format),
        ("Empty content filtering", test_empty_filtering),
        ("Corrupt JSON handling", test_corrupt_json),
        ("Idempotent hashing", test_idempotency),
    ]

    results = {"evals": []}

    print("=" * 50)
    print("QUICK EVALUATION TESTS")
    print("=" * 50)

    for name, test in tests:
        try:
            result = test()
            status = "PASS" if result.get("passed") else "FAIL"
            print(f"  {status}: {name}")
            results["evals"].append({
                "name": name,
                "passed": result.get("passed"),
                "detail": result,
            })
        except Exception as e:
            print(f"  ERROR: {name} - {e}")
            results["evals"].append({
                "name": name,
                "passed": False,
                "error": str(e),
            })

    output = "/home/dclavijo/my_code/nanocode/eval-results.json"
    with open(output, "w") as f:
        json.dump(results, f, indent=2)

    passed = sum(1 for e in results["evals"] if e.get("passed"))
    print(f"\n{passed}/{len(tests)} passed")
    print(f"Saved to: {output}")


if __name__ == "__main__":
    main()