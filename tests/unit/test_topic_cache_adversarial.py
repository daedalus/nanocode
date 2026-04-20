"""Adversarial tests - try to break the topic-ID system."""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nanocode"))

from nanocode.storage.topic_cache import TopicCache, Topic


def test_collision_same_content():
    """VERIFIED: Same content produces same ID (expected)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        content = "Identical content"
        id1 = cache.put(content, "fact")
        id2 = cache.put(content, "fact")

        assert id1 == id2, "Same content should produce same ID"
        assert cache.stats["topic_count"] == 1, "No duplicate topics"


def test_collision_different_content_same_hash():
    """ADVERSARIAL: Try to find hash collision."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir, hash_length=8)

        found_collision = False
        id1 = cache.put("Content A", "fact")

        for i in range(1000):
            id2 = cache.put(f"Content B {i}", "fact")
            if id1 == id2:
                found_collision = True
                print(f"  COLLISION FOUND: {id1} with 'Content B {i}'")
                break

        if not found_collision:
            print(f"  No collision in 1000 attempts (expected)")


def test_empty_content():
    """ADVERSARIAL: Empty content handling."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        id1 = cache.put("", "fact")
        content = cache.get_content(id1)

        print(f"  Empty content ID: {id1}, content: '{content}'")


def test_very_long_content():
    """ADVERSARIAL: Very long content (1MB)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        long_content = "x" * 1_000_000
        id1 = cache.put(long_content, "fact")

        print(f"  1MB content ID: {id1}")
        print(f"  File size: {cache._get_filepath(id1).stat().st_size} bytes")


def test_special_characters():
    """ADVERSARIAL: Special characters in content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        test_cases = [
            'null bytes \x00 in text',
            'newlines\n\n\n',
            'tabs\t\t\t',
            'quotes "and" \'',
            'backslashes\\\\',
            'unicode: 日本語中文',
            'emoji: 😀🎉🔥',
            'control chars\r\n',
            'binary: \x01\x02\x03',
        ]

        for content in test_cases:
            try:
                id1 = cache.put(content, "fact")
                retrieved = cache.get_content(id1)
                if retrieved != content:
                    print(f"  MISMATCH: {repr(content)[:30]} -> {repr(retrieved)[:30]}")
                else:
                    print(f"  OK: {repr(content)[:20]}")
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")


def test_concurrent_writes():
    """ADVERSARIAL: Concurrent writes to cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)
        errors = []
        count = [0]

        def writer(n):
            try:
                for i in range(50):
                    id1 = cache.put(f"Thread {n} item {i}", "fact")
                    count[0] += 1
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            print(f"  ERRORS: {len(errors)}")
            for e in errors[:3]:
                print(f"    {e}")
        else:
            print(f"  10 threads x 50 writes = {count[0]} topics, no errors")


def test_malformed_json_file():
    """ADVERSARIAL: Corrupt JSON file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        good_id = cache.put("Good content", "fact")
        bad_file = cache._get_filepath(good_id)

        with open(bad_file, "w") as f:
            f.write('{"id": broken json')

        try:
            result = cache.get(good_id)
            if result is None:
                print(f"  CORRECT: Returns None for corrupt JSON")
            else:
                print(f"  ERROR: Returned {result}")
        except json.JSONDecodeError as e:
            print(f"  JSON ERROR: {e}")


def test_file_permission_denied():
    """ADVERSARIAL: Permission denied on file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        id1 = cache.put("Test content", "fact")
        filepath = cache._get_filepath(id1)

        os.chmod(filepath, 0o000)

        try:
            result = cache.get(id1)
            print(f"  Result with no permissions: {result}")
        except PermissionError:
            print(f"  PermissionError (expected on some systems)")
        finally:
            os.chmod(filepath, 0o644)


def test_race_condition():
    """ADVERSARIAL: Read while writing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)
        results = []
        stop = threading.Event()

        def writer():
            for i in range(100):
                cache.put(f"Write {i}", "fact")
                if stop.is_set():
                    break

        def reader():
            while not stop.is_set():
                content = cache.get_content("topic_01234567")
                results.append(content)

        w = threading.Thread(target=writer)
        r = threading.Thread(target=reader)

        w.start()
        r.start()
        w.join()
        stop.set()
        r.join()

        print(f"  {len(results)} reads during write")


def test_dos_disk_full():
    """ADVERSARIAL: Fill disk (limited test)."""
    import subprocess

    try:
        result = subprocess.run(
            ["df", "-B1", "--output=avail", "."],
            capture_output=True,
            text=True,
            timeout=5
        )
        available = int(result.stdout.strip().split("\n")[-1])
        print(f"  Available: {available} bytes")
    except Exception as e:
        print(f"  Could not check disk: {e}")


def test_topic_id_format():
    """ADVERSARIAL: Invalid topic ID formats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        invalid_ids = [
            "topic_",
            "topic_1",
            "topic_abc",
            "topic_123456789",
            "TOPIC_12345678",
            "topic_gggggggg",
            "",
            "not_a_topic_id",
        ]

        for invalid in invalid_ids:
            if cache.has(invalid):
                print(f"  Has returned True for invalid: {invalid}")


def test_sql_injection_in_content():
    """ADVERSARIAL: SQL-like content (not actually SQL here, but good practice)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        sql_content = "'; DROP TABLE users; --"
        id1 = cache.put(sql_content, "fact")

        retrieved = cache.get_content(id1)
        if retrieved == sql_content:
            print(f"  SQL content stored correctly (no SQL here)")
        else:
            print(f"  Content modified: {repr(retrieved)}")


def test_memory_exhaustion():
    """ADVERSARIAL: Rapid creation (memory stress)."""
    import gc

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        ids = []
        for i in range(1000):
            ids.append(cache.put(f"Memory test {i}", "fact"))

        print(f"  Created 1000 topics")

        del ids
        gc.collect()

        print(f"  After gc: {cache.stats['topic_count']} topics in cache")


def test_duplicate_ids():
    """ADVERSARIAL: Same content, different types."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TopicCache(tmpdir)

        content = "Same content"
        id1 = cache.put(content, "fact")
        id2 = cache.put(content, "persona")
        id3 = cache.put(content, "place")

        print(f"  Same content with diff types:")
        print(f"    fact: {id1}")
        print(f"    persona: {id2}")
        print(f"    place: {id3}")

        assert id1 == id2 == id3, "Same content = same ID regardless of type"


if __name__ == "__main__":
    tests = [
        ("Same content collision", test_collision_same_content),
        ("Different content same hash", test_collision_different_content_same_hash),
        ("Empty content", test_empty_content),
        ("Very long content", test_very_long_content),
        ("Special characters", test_special_characters),
        ("Concurrent writes", test_concurrent_writes),
        ("Malformed JSON", test_malformed_json_file),
        ("Permission denied", test_file_permission_denied),
        ("Read during write", test_race_condition),
        ("Disk full check", test_dos_disk_full),
        ("Invalid ID format", test_topic_id_format),
        ("SQL-like content", test_sql_injection_in_content),
        ("Memory exhaustion", test_memory_exhaustion),
        ("Same content diff type", test_duplicate_ids),
    ]

    for name, test in tests:
        print(f"\n[Testing] {name}")
        try:
            test()
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print("ADVERSARIAL TESTING COMPLETE")
    print(f"{'='*60}")