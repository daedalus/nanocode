"""Tests for patch functionality."""

import pytest
import tempfile
import os
from pathlib import Path
from nanocode.patch import (
    parse_patch,
    apply_patch,
    derive_new_contents,
    generate_unified_diff,
    PatchType,
    ParseError,
)


def test_parse_add_file():
    """Test parsing an add file patch."""
    patch = """*** Begin Patch
*** Add File: /tmp/test_file.py
+def hello():
+    print("Hello, World!")
*** End Patch"""

    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert hunks[0].type == PatchType.ADD
    assert hunks[0].path == "/tmp/test_file.py"
    assert "def hello():" in hunks[0].contents


def test_parse_delete_file():
    """Test parsing a delete file patch."""
    patch = """*** Begin Patch
*** Delete File: /tmp/test_file.py
*** End Patch"""

    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert hunks[0].type == PatchType.DELETE
    assert hunks[0].path == "/tmp/test_file.py"


def test_parse_update_file():
    """Test parsing an update file patch."""
    patch = """*** Begin Patch
*** Update File: /tmp/test_file.py
@@ old_function
-def old_function():
-    pass
+def new_function():
+    return True
*** End Patch"""

    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert hunks[0].type == PatchType.UPDATE
    assert hunks[0].path == "/tmp/test_file.py"
    assert hunks[0].chunks[0].old_lines == ["def old_function():", "    pass"]
    assert hunks[0].chunks[0].new_lines == ["def new_function():", "    return True"]


def test_parse_invalid_patch():
    """Test parsing an invalid patch raises error."""
    with pytest.raises(ParseError):
        parse_patch("invalid patch content")


def test_parse_patch_missing_markers():
    """Test parsing patch without markers raises error."""
    with pytest.raises(ParseError):
        parse_patch("*** Add File: test.txt\n+content")


def test_derive_new_contents():
    """Test deriving new contents from chunks."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("line 1\nline 2\nline 3\n")
        temp_path = f.name

    try:
        from nanocode.patch import UpdateFileChunk

        chunks = [
            UpdateFileChunk(
                old_lines=["line 2"],
                new_lines=["modified line 2"],
                change_context="line 1",
                is_end_of_file=False,
            )
        ]

        diff, content = derive_new_contents(temp_path, chunks)
        assert "modified line 2" in content
    finally:
        os.unlink(temp_path)


def test_generate_unified_diff():
    """Test generating unified diff."""
    old = "line 1\nline 2\nline 3\n"
    new = "line 1\nmodified line 2\nline 3\n"

    diff = generate_unified_diff(old, new)
    assert "-line 2" in diff
    assert "+modified line 2" in diff


@pytest.mark.asyncio
async def test_apply_patch_add():
    """Test applying an add file patch."""

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "new_file.py")
        patch = f"""*** Begin Patch
*** Add File: {test_file}
+def hello():
+    print("Hello")
*** End Patch"""

        result = await apply_patch(patch)
        assert test_file in result.added
        assert os.path.exists(test_file)
        content = Path(test_file).read_text()
        assert "def hello():" in content


@pytest.mark.asyncio
async def test_apply_patch_update():
    """Test applying an update file patch."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def old():\n    pass\n")
        temp_path = f.name

    try:
        patch = f"""*** Begin Patch
*** Update File: {temp_path}
@@
-def old():
-    pass
+def new():
+    return True
*** End Patch"""

        result = await apply_patch(patch)
        assert temp_path in result.modified
        content = Path(temp_path).read_text()
        assert "def new():" in content
        assert "return True" in content
    finally:
        os.unlink(temp_path)


@pytest.mark.asyncio
async def test_apply_patch_delete():
    """Test applying a delete file patch."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("content\n")
        temp_path = f.name

    patch = f"""*** Begin Patch
*** Delete File: {temp_path}
*** End Patch"""

    result = await apply_patch(patch)
    assert temp_path in result.deleted
    assert not os.path.exists(temp_path)


def test_strip_heredoc():
    """Test stripping heredoc syntax."""
    from nanocode.patch import strip_heredoc

    input_text = """cat <<'EOF'
content here
more content
EOF"""

    result = strip_heredoc(input_text)
    assert result == "content here\nmore content"


def test_parse_with_move():
    """Test parsing patch with move directive."""
    patch = """*** Begin Patch
*** Update File: /tmp/old.py
*** Move to: /tmp/new.py
@@ main
-old code
+new code
*** End Patch"""

    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert hunks[0].move_path == "/tmp/new.py"


def test_parse_empty_patch():
    """Test parsing empty patch returns empty hunks."""
    hunks = parse_patch("*** Begin Patch\n*** End Patch")
    assert len(hunks) == 0


def test_parse_malformed_header():
    """Test parsing malformed header is skipped gracefully."""
    patch = """*** Begin Patch
*** Unknown Header
*** Add File: /tmp/test.txt
+valid content
*** End Patch"""
    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert hunks[0].type == PatchType.ADD


def test_parse_reversed_markers():
    """Test parsing reversed markers raises error."""
    with pytest.raises(ParseError):
        parse_patch("*** End Patch\n*** Begin Patch\n*** End Patch")


def test_parse_trailing_content():
    """Test parsing content after end marker."""
    patch = """*** Begin Patch
*** Add File: /tmp/test.txt
+content
*** End Patch
*** Add File: /tmp/extra.txt
+extra"""

    hunks = parse_patch(patch)
    assert len(hunks) == 1


def test_parse_path_traversal_attempt():
    """Test that path traversal in patch is allowed (user responsibility)."""
    patch = """*** Begin Patch
*** Add File: ../../../etc/passwd
+malicious
*** End Patch"""

    hunks = parse_patch(patch)
    assert hunks[0].path == "../../../etc/passwd"


def test_parse_multiple_operations():
    """Test parsing patch with multiple operations."""
    patch = """*** Begin Patch
*** Add File: /tmp/new1.txt
+content1
*** Add File: /tmp/new2.txt
+content2
*** Delete File: /tmp/delete_me.txt
*** Update File: /tmp/modify.txt
@@
-old
+new
*** End Patch"""

    hunks = parse_patch(patch)
    assert len(hunks) == 4
    assert hunks[0].type == PatchType.ADD
    assert hunks[1].type == PatchType.ADD
    assert hunks[2].type == PatchType.DELETE
    assert hunks[3].type == PatchType.UPDATE


def test_parse_special_characters_in_content():
    """Test parsing content with special characters."""
    patch = """*** Begin Patch
*** Add File: /tmp/test.py
+#!/usr/bin/env python
+import os
+print("Hello\tWorld")
+print("Line1\\nLine2")
*** End Patch"""

    hunks = parse_patch(patch)
    assert "Hello\tWorld" in hunks[0].contents
    assert "Line1\\nLine2" in hunks[0].contents


def test_parse_empty_lines():
    """Test parsing patch with empty lines."""
    patch = """*** Begin Patch
*** Add File: /tmp/empty.txt
+

*** End Patch"""

    hunks = parse_patch(patch)
    assert hunks[0].contents == ""


def test_parse_unicode_content():
    """Test parsing patch with Unicode content."""
    patch = """*** Begin Patch
*** Add File: /tmp/unicode.txt
+Hello 世界
+Это тест
+🎉
*** End Patch"""

    hunks = parse_patch(patch)
    assert "世界" in hunks[0].contents
    assert "Это тест" in hunks[0].contents
    assert "🎉" in hunks[0].contents


def test_parse_leading_whitespace_in_content():
    """Test parsing content with leading plus sign and whitespace."""
    patch = """*** Begin Patch
*** Add File: /tmp/test.txt
+ content
*** End Patch"""

    hunks = parse_patch(patch)
    assert hunks[0].contents == " content"


def test_parse_only_minus_lines():
    """Test parsing update with only deletion lines."""
    patch = """*** Begin Patch
*** Update File: /tmp/test.txt
@@
-only deletion
*** End Patch"""

    hunks = parse_patch(patch)
    assert hunks[0].chunks[0].old_lines == ["only deletion"]
    assert hunks[0].chunks[0].new_lines == []


def test_parse_only_plus_lines():
    """Test parsing update with only addition lines."""
    patch = """*** Begin Patch
*** Update File: /tmp/test.txt
@@
+only addition
*** End Patch"""

    hunks = parse_patch(patch)
    assert hunks[0].chunks[0].old_lines == []
    assert hunks[0].chunks[0].new_lines == ["only addition"]


@pytest.mark.asyncio
async def test_apply_patch_to_nonexistent_directory():
    """Test applying patch creates parent directories."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "nested", "dir", "new.py")
        patch = f"""*** Begin Patch
*** Add File: {test_file}
+def test():
+    pass
*** End Patch"""

        result = await apply_patch(patch)
        assert test_file in result.added
        assert os.path.exists(test_file)


@pytest.mark.asyncio
async def test_apply_patch_empty_content():
    """Test applying patch with empty file content."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "empty.py")
        patch = f"""*** Begin Patch
*** Add File: {test_file}
*** End Patch"""

        result = await apply_patch(patch)
        assert test_file in result.added
        content = Path(test_file).read_text()
        assert content == ""


@pytest.mark.asyncio
async def test_apply_patch_update_multiple_chunks():
    """Test applying patch with multiple chunks."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("line 1\nline 2\nline 3\nline 4\nline 5\n")
        temp_path = f.name

    try:
        patch = f"""*** Begin Patch
*** Update File: {temp_path}
@@
-line 1
+modified 1
@@
-line 3
+modified 3
*** End Patch"""

        result = await apply_patch(patch)
        assert temp_path in result.modified
        content = Path(temp_path).read_text()
        assert "modified 1" in content
        assert "modified 3" in content
        assert "line 2" in content
    finally:
        os.unlink(temp_path)


@pytest.mark.asyncio
async def test_apply_patch_to_read_only_location():
    """Test applying patch to read-only location fails gracefully."""
    import tempfile
    import stat

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "readonly.txt")
        Path(test_file).write_text("content")

        os.chmod(test_file, stat.S_IRUSR)

        patch = f"""*** Begin Patch
*** Update File: {test_file}
@@
-content
+new content
*** End Patch"""

        with pytest.raises(Exception):
            await apply_patch(patch)


@pytest.mark.asyncio
async def test_apply_patch_delete_nonexistent_file():
    """Test deleting nonexistent file doesn't crash."""
    patch = """*** Begin Patch
*** Delete File: /tmp/nonexistent_file_12345.txt
*** End Patch"""

    result = await apply_patch(patch)
    assert "/tmp/nonexistent_file_12345.txt" in result.deleted


def test_seek_sequence_edge_cases():
    """Test seek_sequence with various edge cases."""
    from nanocode.patch import seek_sequence

    lines = ["a", "b", "c", "d", "e"]

    assert seek_sequence(lines, ["a"], 0) == 0
    assert seek_sequence(lines, ["e"], 0) == 4
    assert seek_sequence(lines, ["c"], 0) == 2
    assert seek_sequence(lines, ["a"], 1) == -1
    assert seek_sequence(lines, ["x"], 0) == -1
    assert seek_sequence(lines, ["a", "b"], 0) == 0
    assert seek_sequence(lines, ["b", "c"], 0) == 1


def test_seek_sequence_with_trailing_whitespace():
    """Test seek_sequence handles trailing whitespace."""
    from nanocode.patch import seek_sequence

    lines = ["content  ", "  spaced"]

    assert seek_sequence(lines, ["content"], 0) != -1
    assert seek_sequence(lines, ["  spaced"], 0) != -1


def test_normalize_unicode_edge_cases():
    """Test Unicode normalization handles edge cases."""
    from nanocode.patch import normalize_unicode

    assert normalize_unicode("hello") == "hello"
    assert normalize_unicode("") == ""
    assert "'" in normalize_unicode("\u2018")
    assert '"' in normalize_unicode("\u201c")
    assert normalize_unicode("\u00a0") == " "


def test_compute_replacements_no_context():
    """Test compute_replacements without context line."""
    from nanocode.patch import compute_replacements, UpdateFileChunk

    lines = ["line1", "line2", "line3"]
    chunks = [
        UpdateFileChunk(
            old_lines=["line2"],
            new_lines=["replaced"],
            change_context=None,
            is_end_of_file=False,
        )
    ]

    replacements = compute_replacements(lines, chunks)
    assert len(replacements) == 1
    assert replacements[0] == (1, 1, ["replaced"])


def test_apply_replacements_order():
    """Test applying replacements in reverse order."""
    from nanocode.patch import apply_replacements

    lines = ["a", "b", "c", "d", "e"]
    replacements = [
        (0, 1, ["x"]),
        (3, 1, ["y"]),
    ]

    result = apply_replacements(lines, replacements)
    assert result == ["x", "b", "c", "y", "e"]


def test_generate_unified_diff_identical():
    """Test diff for identical content is empty."""
    content = "line1\nline2\n"
    diff = generate_unified_diff(content, content)
    assert diff == ""


def test_generate_unified_diff_empty_to_content():
    """Test diff from empty to content."""
    old = ""
    new = "line1\nline2\n"

    diff = generate_unified_diff(old, new)
    assert "+line1" in diff


def test_generate_unified_diff_content_to_empty():
    """Test diff from content to empty."""
    old = "line1\nline2\n"
    new = ""

    diff = generate_unified_diff(old, new)
    assert "-line1" in diff
