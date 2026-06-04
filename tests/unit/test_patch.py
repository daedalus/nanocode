"""Tests for patch system - code editing utilities."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestPatchTypes:
    """Test PatchType enum."""

    def test_patch_types(self):
        """Test PatchType has required values."""
        from nanocode.patch import PatchType

        assert PatchType.ADD.value == "add"
        assert PatchType.DELETE.value == "delete"
        assert PatchType.UPDATE.value == "update"


class TestHunk:
    """Test Hunk dataclass."""

    def test_add_hunk(self):
        """Test creating an ADD hunk."""
        from nanocode.patch import Hunk, PatchType

        hunk = Hunk(type=PatchType.ADD, path="/tmp/file.py", contents="print('hello')")
        assert hunk.type == PatchType.ADD
        assert hunk.path == "/tmp/file.py"
        assert hunk.contents == "print('hello')"

    def test_update_hunk(self):
        """Test creating an UPDATE hunk."""
        from nanocode.patch import Hunk, PatchType, UpdateFileChunk

        chunk = UpdateFileChunk(
            old_lines=["old line"],
            new_lines=["new line"],
        )
        hunk = Hunk(
            type=PatchType.UPDATE,
            path="/tmp/file.py",
            chunks=[chunk],
            move_path="/tmp/moved.py",
        )
        assert hunk.type == PatchType.UPDATE
        assert hunk.move_path == "/tmp/moved.py"
        assert len(hunk.chunks) == 1


class TestStripHeredoc:
    """Test strip_heredoc."""

    def test_no_heredoc(self):
        """Test strip_heredoc passes through non-heredoc."""
        from nanocode.patch import strip_heredoc

        assert strip_heredoc("simple text") == "simple text"

    def test_with_heredoc(self):
        """Test strip_heredoc removes heredoc wrapper."""
        from nanocode.patch import strip_heredoc

        text = "cat <<'EOF'\ncontent\nhere\nEOF"
        result = strip_heredoc(text)
        assert "cat <<'EOF'" not in result
        assert "content" in result
        assert "here" in result


class TestParsePatchHeader:
    """Test parse_patch_header."""

    def test_add_file(self):
        """Test parsing ADD file header."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["*** Add File: /tmp/test.py ***"], 0)
        assert result is not None
        path, move_path, next_idx = result
        assert path == "/tmp/test.py"
        assert move_path is None
        assert next_idx == 1

    def test_add_file_no_trailing_stars(self):
        """Test parsing ADD header without trailing stars."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["*** Add File: /tmp/test.py"], 0)
        assert result is not None
        path, _, _ = result
        assert path == "/tmp/test.py"

    def test_add_file_empty_path(self):
        """Test parsing ADD header with empty path."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["*** Add File: ***"], 0)
        assert result is None

    def test_delete_file(self):
        """Test parsing DELETE file header."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["*** Delete File: /tmp/test.py ***"], 0)
        assert result is not None
        path, _, _ = result
        assert path == "/tmp/test.py"

    def test_update_file(self):
        """Test parsing UPDATE file header."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["*** Update File: /tmp/test.py ***"], 0)
        assert result is not None
        path, move_path, next_idx = result
        assert path == "/tmp/test.py"
        assert move_path is None
        assert next_idx == 1

    def test_update_file_with_move(self):
        """Test parsing UPDATE with move."""
        from nanocode.patch import parse_patch_header

        lines = [
            "*** Update File: /tmp/test.py ***",
            "*** Move to: /tmp/moved.py ***",
        ]
        result = parse_patch_header(lines, 0)
        assert result is not None
        path, move_path, next_idx = result
        assert path == "/tmp/test.py"
        assert move_path == "/tmp/moved.py"
        assert next_idx == 2

    def test_update_file_empty_path(self):
        """Test parsing UPDATE with empty path."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["*** Update File: ***"], 0)
        assert result is None

    def test_no_header(self):
        """Test parsing line that is not a header."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["regular line"], 0)
        assert result is None

    def test_out_of_bounds(self):
        """Test parsing when start index is beyond lines."""
        from nanocode.patch import parse_patch_header

        result = parse_patch_header(["line"], 5)
        assert result is None


class TestParsePatch:
    """Test parse_patch."""

    def test_missing_markers(self):
        """Test parse_patch raises on missing markers."""
        from nanocode.patch import parse_patch, ParseError

        with pytest.raises(ParseError, match="missing Begin/End markers"):
            parse_patch("no markers here")

    def test_begin_after_end(self):
        """Test parse_patch raises when Begin after End."""
        from nanocode.patch import parse_patch, ParseError

        text = "*** End Patch ***\n*** Begin Patch ***"
        with pytest.raises(ParseError, match="Begin marker after End"):
            parse_patch(text)

    def test_parse_add_patch(self):
        """Test parsing an ADD patch."""
        from nanocode.patch import parse_patch, PatchType

        text = "*** Begin Patch ***\n*** Add File: /tmp/test.py ***\n+print('hello')\n*** End Patch ***"
        hunks = parse_patch(text)
        assert len(hunks) == 1
        assert hunks[0].type == PatchType.ADD
        assert hunks[0].path == "/tmp/test.py"
        assert "print('hello')" in hunks[0].contents

    def test_parse_delete_patch(self):
        """Test parsing a DELETE patch."""
        from nanocode.patch import parse_patch, PatchType

        text = "*** Begin Patch ***\n*** Delete File: /tmp/test.py ***\n*** End Patch ***"
        hunks = parse_patch(text)
        assert len(hunks) == 1
        assert hunks[0].type == PatchType.DELETE
        assert hunks[0].path == "/tmp/test.py"

    def test_parse_update_patch(self):
        """Test parsing an UPDATE patch."""
        from nanocode.patch import parse_patch, PatchType

        text = (
            "*** Begin Patch ***\n"
            "*** Update File: /tmp/test.py ***\n"
            "@@ context @@\n"
            "-old line\n"
            "+new line\n"
            "*** End Patch ***"
        )
        hunks = parse_patch(text)
        assert len(hunks) == 1
        assert hunks[0].type == PatchType.UPDATE
        assert len(hunks[0].chunks) == 1
        assert hunks[0].chunks[0].old_lines == ["old line"]
        assert hunks[0].chunks[0].new_lines == ["new line"]

class TestNormalizeUnicode:
    """Test normalize_unicode."""

    def test_normalize_quotes(self):
        """Test normalize_unicode converts fancy quotes."""
        from nanocode.patch import normalize_unicode

        result = normalize_unicode("\u2018hello\u2019")
        assert result == "'hello'"

    def test_normalize_dashes(self):
        """Test normalize_unicode converts em dashes."""
        from nanocode.patch import normalize_unicode

        result = normalize_unicode("foo\u2014bar")
        assert result == "foo-bar"


class TestSeekSequence:
    """Test seek_sequence."""

    def test_exact_match(self):
        """Test seek_sequence finds exact match."""
        from nanocode.patch import seek_sequence

        lines = ["a", "b", "c", "d"]
        result = seek_sequence(lines, ["b", "c"], 0)
        assert result == 1

    def test_no_match(self):
        """Test seek_sequence returns -1 for no match."""
        from nanocode.patch import seek_sequence

        lines = ["a", "b", "c"]
        result = seek_sequence(lines, ["x", "y"], 0)
        assert result == -1

    def test_empty_pattern(self):
        """Test seek_sequence returns -1 for empty pattern."""
        from nanocode.patch import seek_sequence

        result = seek_sequence(["a", "b"], [], 0)
        assert result == -1

    def test_eof_match(self):
        """Test seek_sequence matches at end of file."""
        from nanocode.patch import seek_sequence

        lines = ["a", "b", "c", "new"]
        result = seek_sequence(lines, ["c", "new"], 0, eof=True)
        assert result >= 0

    def test_rstrip_match(self):
        """Test seek_sequence matches with trailing whitespace."""
        from nanocode.patch import seek_sequence

        lines = ["a  ", "b  ", "c"]
        result = seek_sequence(lines, ["a", "b"], 0)
        assert result == 0

    def test_trim_match(self):
        """Test seek_sequence matches with leading/trailing spaces."""
        from nanocode.patch import seek_sequence

        lines = ["  a  ", "  b  ", "c"]
        result = seek_sequence(lines, ["a", "b"], 0)
        assert result == 0


class TestComputeReplacements:
    """Test compute_replacements."""

    def test_simple_replace(self):
        """Test compute_replacements with old/new lines."""
        from nanocode.patch import compute_replacements, UpdateFileChunk

        original = ["a", "b", "c"]
        chunk = UpdateFileChunk(old_lines=["b"], new_lines=["x", "y"])
        replacements = compute_replacements(original, [chunk])
        assert len(replacements) == 1
        start, length, new_lines = replacements[0]
        assert start == 1
        assert length == 1
        assert new_lines == ["x", "y"]

    def test_insertion(self):
        """Test compute_replacements with insertion (no old_lines)."""
        from nanocode.patch import compute_replacements, UpdateFileChunk

        original = ["a", "b"]
        chunk = UpdateFileChunk(old_lines=[], new_lines=["new"])
        replacements = compute_replacements(original, [chunk])
        assert len(replacements) == 1
        start, length, new_lines = replacements[0]
        assert start == 2
        assert length == 0
        assert new_lines == ["new"]

    def test_trailing_empty_line(self):
        """Test compute_replacements handles trailing empty line in pattern."""
        from nanocode.patch import compute_replacements, UpdateFileChunk

        original = ["a", "b", "c"]
        chunk = UpdateFileChunk(old_lines=["b", ""], new_lines=["x", ""])
        replacements = compute_replacements(original, [chunk])
        assert len(replacements) == 1

    def test_not_found_raises(self):
        """Test compute_replacements raises when pattern not found."""
        from nanocode.patch import compute_replacements, UpdateFileChunk, ComputeReplacementsError

        original = ["a", "b"]
        chunk = UpdateFileChunk(old_lines=["not found"], new_lines=["x"])
        with pytest.raises(ComputeReplacementsError, match="Failed to find expected lines"):
            compute_replacements(original, [chunk])

    def test_context_match(self):
        """Test compute_replacements uses context to locate chunk."""
        from nanocode.patch import compute_replacements, UpdateFileChunk

        original = ["a", "b", "c", "d"]
        chunk = UpdateFileChunk(
            old_lines=["c"],
            new_lines=["x"],
            change_context="b",
        )
        replacements = compute_replacements(original, [chunk])
        assert len(replacements) == 1
        assert replacements[0][0] == 2  # should find "c" after context "b"


class TestApplyReplacements:
    """Test apply_replacements."""

    def test_simple_replace(self):
        """Test apply_replacements replaces lines."""
        from nanocode.patch import apply_replacements

        lines = ["a", "old", "c"]
        replacements = [(1, 1, ["new"])]
        result = apply_replacements(lines, replacements)
        assert result == ["a", "new", "c"]

    def test_multiple_replacements(self):
        """Test apply_replacements handles multiple changes."""
        from nanocode.patch import apply_replacements

        lines = ["a", "old1", "old2", "d"]
        replacements = [(1, 1, ["new1"]), (2, 1, ["new2"])]
        result = apply_replacements(lines, replacements)
        assert result == ["a", "new1", "new2", "d"]


class TestGenerateUnifiedDiff:
    """Test generate_unified_diff."""

    def test_no_changes(self):
        """Test generate_unified_diff returns empty for identical content."""
        from nanocode.patch import generate_unified_diff

        result = generate_unified_diff("same", "same")
        assert result == ""

    def test_with_changes(self):
        """Test generate_unified_diff shows changes."""
        from nanocode.patch import generate_unified_diff

        result = generate_unified_diff("old line\n", "new line\n")
        assert "-old line" in result
        assert "+new line" in result


class TestDeriveNewContents:
    """Test derive_new_contents."""

    def test_file_not_found(self):
        """Test derive_new_contents raises on missing file."""
        from nanocode.patch import derive_new_contents, IoError

        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(IoError, match="File not found"):
                derive_new_contents("/nonexistent/file.py", [])

    def test_success(self):
        """Test derive_new_contents computes diff and new content."""
        from nanocode.patch import derive_new_contents, UpdateFileChunk

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("old line\n")
            f.flush()
            path = f.name

        try:
            chunk = UpdateFileChunk(old_lines=["old line"], new_lines=["new line"])
            unified_diff, new_content = derive_new_contents(path, [chunk])
            assert "new line" in new_content
            assert "-old line" in unified_diff or unified_diff == ""
        finally:
            Path(path).unlink(missing_ok=True)


class TestApplyHunks:
    """Test apply_hunks."""

    @pytest.mark.asyncio
    async def test_no_hunks_raises(self):
        """Test apply_hunks raises on empty hunks."""
        from nanocode.patch import apply_hunks, PatchError

        with pytest.raises(PatchError, match="No files were modified"):
            await apply_hunks([])

    @pytest.mark.asyncio
    async def test_add_hunk(self):
        """Test apply_hunks creates a file."""
        from nanocode.patch import apply_hunks, Hunk, PatchType

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "new_file.py")
            hunk = Hunk(type=PatchType.ADD, path=path, contents="print('hello')")
            result = await apply_hunks([hunk])
            assert path in result.added
            assert Path(path).read_text() == "print('hello')"

    @pytest.mark.asyncio
    async def test_delete_hunk(self):
        """Test apply_hunks deletes a file."""
        from nanocode.patch import apply_hunks, Hunk, PatchType

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "to_delete.py"
            path.write_text("content")
            hunk = Hunk(type=PatchType.DELETE, path=str(path))
            result = await apply_hunks([hunk])
            assert str(path) in result.deleted
            assert not path.exists()

    @pytest.mark.asyncio
    async def test_update_hunk(self):
        """Test apply_hunks updates a file."""
        from nanocode.patch import apply_hunks, Hunk, PatchType, UpdateFileChunk

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "to_update.py"
            path.write_text("old line\n")
            chunk = UpdateFileChunk(old_lines=["old line"], new_lines=["new line"])
            hunk = Hunk(type=PatchType.UPDATE, path=str(path), chunks=[chunk])
            result = await apply_hunks([hunk])
            assert str(path) in result.modified
            assert path.read_text() == "new line\n"

    @pytest.mark.asyncio
    async def test_update_hunk_with_move(self):
        """Test apply_hunks moves a file on update."""
        from nanocode.patch import apply_hunks, Hunk, PatchType, UpdateFileChunk

        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.py"
            dst = Path(tmpdir) / "dest.py"
            src.write_text("old line\n")
            chunk = UpdateFileChunk(old_lines=["old line"], new_lines=["new line"])
            hunk = Hunk(
                type=PatchType.UPDATE,
                path=str(src),
                chunks=[chunk],
                move_path=str(dst),
            )
            result = await apply_hunks([hunk])
            assert str(dst) in result.modified
            assert dst.read_text() == "new line\n"
            assert not src.exists()


class TestApplyPatch:
    """Test apply_patch."""

    @pytest.mark.asyncio
    async def test_apply_patch_add(self):
        """Test apply_patch with ADD patch."""
        from nanocode.patch import apply_patch

        with tempfile.TemporaryDirectory() as tmpdir:
            path = f"{tmpdir}/new.py"
            text = (
                "*** Begin Patch ***\n"
                f"*** Add File: {path} ***\n"
                "+print('hello')\n"
                "*** End Patch ***"
            )
            result = await apply_patch(text)
            assert path in result.added


class TestGetFileHash:
    """Test get_file_hash."""

    def test_file_not_found(self):
        """Test get_file_hash returns empty for missing file."""
        from nanocode.patch import get_file_hash

        with patch("pathlib.Path.exists", return_value=False):
            assert get_file_hash("/nonexistent") == ""

    def test_file_hash(self):
        """Test get_file_hash computes MD5."""
        from nanocode.patch import get_file_hash

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("content")
            f.flush()
            path = f.name

        try:
            hash_val = get_file_hash(path)
            assert len(hash_val) == 32  # MD5 hex
            assert isinstance(hash_val, str)
        finally:
            Path(path).unlink(missing_ok=True)
