"""Patch system for code editing utilities."""

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class PatchType(Enum):
    ADD = "add"
    DELETE = "delete"
    UPDATE = "update"


@dataclass
class UpdateFileChunk:
    """A chunk of file updates."""

    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)
    change_context: str | None = None
    is_end_of_file: bool = False


@dataclass
class Hunk:
    """A patch hunk representing a single file change."""

    type: PatchType
    path: str
    contents: str | None = None
    chunks: list[UpdateFileChunk] = field(default_factory=list)
    move_path: str | None = None


@dataclass
class AffectedPaths:
    """Tracks affected files from a patch."""

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


class PatchError(Exception):
    """Base exception for patch errors."""

    pass


class ParseError(PatchError):
    """Patch parsing error."""

    pass


class IoError(PatchError):
    """File I/O error during patch application."""

    pass


class ComputeReplacementsError(PatchError):
    """Error computing replacements."""

    pass


def strip_heredoc(text: str) -> str:
    """Strip heredoc syntax from input."""
    match = re.match(r'(?:cat\s+)?<<[\'"]?(\w+)[\'"]?\s*\n([\s\S]*?)\n\1\s*$', text)
    if match:
        return match.group(2)
    return text


def parse_patch_header(
    lines: list[str], start_idx: int
) -> tuple[str, str | None, int] | None:
    """Parse a patch header line."""
    if start_idx >= len(lines):
        return None

    line = lines[start_idx]

    if line.startswith("*** Add File:"):
        file_path = line[len("*** Add File:") :].strip()
        return (file_path, None, start_idx + 1) if file_path else None

    if line.startswith("*** Delete File:"):
        file_path = line[len("*** Delete File:") :].strip()
        return (file_path, None, start_idx + 1) if file_path else None

    if line.startswith("*** Update File:"):
        file_path = line[len("*** Update File:") :].strip()
        if not file_path:
            return None

        move_path = None
        next_idx = start_idx + 1

        if next_idx < len(lines) and lines[next_idx].startswith("*** Move to:"):
            move_path = lines[next_idx][len("*** Move to:") :].strip()
            next_idx += 1

        return (file_path, move_path, next_idx)

    return None


def parse_update_file_chunks(
    lines: list[str], start_idx: int
) -> tuple[list[UpdateFileChunk], int]:
    """Parse update file chunks from patch."""
    chunks: list[UpdateFileChunk] = []
    i = start_idx

    while i < len(lines) and not lines[i].startswith("***"):
        if lines[i].startswith("@@"):
            context_line = lines[i][2:].strip()
            i += 1

            old_lines: list[str] = []
            new_lines: list[str] = []
            is_end_of_file = False

            while (
                i < len(lines)
                and not lines[i].startswith("@@")
                and not lines[i].startswith("***")
            ):
                change_line = lines[i]

                if change_line == "*** End of File":
                    is_end_of_file = True
                    i += 1
                    break

                if change_line.startswith(" "):
                    content = change_line[1:]
                    old_lines.append(content)
                    new_lines.append(content)
                elif change_line.startswith("-"):
                    old_lines.append(change_line[1:])
                elif change_line.startswith("+"):
                    new_lines.append(change_line[1:])

                i += 1

            chunks.append(
                UpdateFileChunk(
                    old_lines=old_lines,
                    new_lines=new_lines,
                    change_context=context_line or None,
                    is_end_of_file=is_end_of_file,
                )
            )
        else:
            i += 1

    return chunks, i


def parse_add_file_content(lines: list[str], start_idx: int) -> tuple[str, int]:
    """Parse add file content."""
    content = ""
    i = start_idx

    while i < len(lines) and not lines[i].startswith("***"):
        if lines[i].startswith("+"):
            content += lines[i][1:] + "\n"
        i += 1

    if content.endswith("\n"):
        content = content[:-1]

    return content, i


def parse_patch(patch_text: str) -> list[Hunk]:
    """Parse a patch text into hunks."""
    cleaned = strip_heredoc(patch_text.strip())
    lines = cleaned.split("\n")
    hunks: list[Hunk] = []

    begin_marker = "*** Begin Patch"
    end_marker = "*** End Patch"

    try:
        begin_idx = next(
            i for i, line in enumerate(lines) if line.strip() == begin_marker
        )
        end_idx = next(i for i, line in enumerate(lines) if line.strip() == end_marker)
    except StopIteration:
        raise ParseError("Invalid patch format: missing Begin/End markers")

    if begin_idx >= end_idx:
        raise ParseError("Invalid patch format: Begin marker after End marker")

    i = begin_idx + 1

    while i < end_idx:
        header = parse_patch_header(lines, i)
        if not header:
            i += 1
            continue

        file_path, move_path, next_idx = header

        if lines[i].startswith("*** Add File:"):
            content, i = parse_add_file_content(lines, next_idx)
            hunks.append(Hunk(type=PatchType.ADD, path=file_path, contents=content))
        elif lines[i].startswith("*** Delete File:"):
            hunks.append(Hunk(type=PatchType.DELETE, path=file_path))
            i = next_idx
        elif lines[i].startswith("*** Update File:"):
            chunks, i = parse_update_file_chunks(lines, next_idx)
            hunks.append(
                Hunk(
                    type=PatchType.UPDATE,
                    path=file_path,
                    chunks=chunks,
                    move_path=move_path,
                )
            )
        else:
            i += 1

    return hunks


def normalize_unicode(text: str) -> str:
    """Normalize Unicode punctuation to ASCII equivalents."""
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def seek_sequence(
    lines: list[str],
    pattern: list[str],
    start_index: int,
    eof: bool = False,
) -> int:
    """Find a sequence of lines in the file."""
    if not pattern:
        return -1

    # Exact match
    result = _try_match(lines, pattern, start_index, lambda a, b: a == b, eof)
    if result != -1:
        return result

    # Rstrip (trim trailing whitespace)
    result = _try_match(
        lines, pattern, start_index, lambda a, b: a.rstrip() == b.rstrip(), eof
    )
    if result != -1:
        return result

    # Trim (both ends)
    result = _try_match(
        lines, pattern, start_index, lambda a, b: a.strip() == b.strip(), eof
    )
    if result != -1:
        return result

    # Normalized (Unicode punctuation to ASCII)
    result = _try_match(
        lines,
        pattern,
        start_index,
        lambda a, b: normalize_unicode(a.strip()) == normalize_unicode(b.strip()),
        eof,
    )
    return result


def _try_match(
    lines: list[str],
    pattern: list[str],
    start_index: int,
    compare: callable,
    eof: bool,
) -> int:
    """Try to match pattern with comparison function."""
    if eof:
        from_end = len(lines) - len(pattern)
        if from_end >= start_index:
            matches = True
            for j in range(len(pattern)):
                if not compare(lines[from_end + j], pattern[j]):
                    matches = False
                    break
            if matches:
                return from_end

    for i in range(start_index, len(lines) - len(pattern) + 1):
        matches = True
        for j in range(len(pattern)):
            if not compare(lines[i + j], pattern[j]):
                matches = False
                break
        if matches:
            return i

    return -1


def compute_replacements(
    original_lines: list[str],
    chunks: list[UpdateFileChunk],
) -> list[tuple[int, int, list[str]]]:
    """Compute replacements for file updates."""
    replacements: list[tuple[int, int, list[str]]] = []
    line_index = 0

    for chunk in chunks:
        if chunk.change_context:
            context_idx = seek_sequence(
                original_lines, [chunk.change_context], line_index
            )
            if context_idx == -1:
                raise ComputeReplacementsError(
                    f"Failed to find context '{chunk.change_context}'"
                )
            line_index = context_idx + 1

        if not chunk.old_lines:
            insertion_idx = (
                len(original_lines)
                if not original_lines or original_lines[-1] != ""
                else len(original_lines) - 1
            )
            replacements.append((insertion_idx, 0, chunk.new_lines))
            continue

        pattern = chunk.old_lines
        new_slice = chunk.new_lines
        found = seek_sequence(original_lines, pattern, line_index, chunk.is_end_of_file)

        if found == -1 and pattern and pattern[-1] == "":
            pattern = pattern[:-1]
            if new_slice and new_slice[-1] == "":
                new_slice = new_slice[:-1]
            found = seek_sequence(
                original_lines, pattern, line_index, chunk.is_end_of_file
            )

        if found != -1:
            replacements.append((found, len(pattern), new_slice))
            line_index = found + len(pattern)
        else:
            raise ComputeReplacementsError(
                f"Failed to find expected lines:\n{chr(10).join(chunk.old_lines)}"
            )

    replacements.sort(key=lambda x: x[0])
    return replacements


def apply_replacements(
    lines: list[str],
    replacements: list[tuple[int, int, list[str]]],
) -> list[str]:
    """Apply replacements to lines."""
    result = list(lines)

    for start_idx, old_len, new_segment in reversed(replacements):
        del result[start_idx : start_idx + old_len]
        for j, new_line in enumerate(new_segment):
            result.insert(start_idx + j, new_line)

    return result


def derive_new_contents(path: str, chunks: list[UpdateFileChunk]) -> tuple[str, str]:
    """Derive new file contents from chunks."""
    path_obj = Path(path)

    if not path_obj.exists():
        raise IoError(f"File not found: {path}")

    original_content = path_obj.read_text(encoding="utf-8")
    original_lines = original_content.split("\n")

    if original_lines and original_lines[-1] == "":
        original_lines.pop()

    replacements = compute_replacements(original_lines, chunks)
    new_lines = apply_replacements(original_lines, replacements)

    if not new_lines or new_lines[-1] != "":
        new_lines.append("")

    new_content = "\n".join(new_lines)
    unified_diff = generate_unified_diff(original_content, new_content)

    return unified_diff, new_content


def generate_unified_diff(old_content: str, new_content: str) -> str:
    """Generate a unified diff."""
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")

    diff_lines = ["@@ -1 +1 @@"]

    max_len = max(len(old_lines), len(new_lines))
    has_changes = False

    for i in range(max_len):
        old_line = old_lines[i] if i < len(old_lines) else ""
        new_line = new_lines[i] if i < len(new_lines) else ""

        if old_line != new_line:
            if old_line:
                diff_lines.append(f"-{old_line}")
            if new_line:
                diff_lines.append(f"+{new_line}")
            has_changes = True
        elif old_line:
            diff_lines.append(f" {old_line}")

    return "\n".join(diff_lines) if has_changes else ""


async def apply_hunks(hunks: list[Hunk]) -> AffectedPaths:
    """Apply hunks to the filesystem."""
    if not hunks:
        raise PatchError("No files were modified.")

    affected = AffectedPaths()

    for hunk in hunks:
        if hunk.type == PatchType.ADD:
            path_obj = Path(hunk.path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(hunk.contents or "", encoding="utf-8")
            affected.added.append(hunk.path)

        elif hunk.type == PatchType.DELETE:
            path_obj = Path(hunk.path)
            if path_obj.exists():
                path_obj.unlink()
            affected.deleted.append(hunk.path)

        elif hunk.type == PatchType.UPDATE:
            if hunk.move_path:
                unified_diff, new_content = derive_new_contents(hunk.path, hunk.chunks)
                move_path_obj = Path(hunk.move_path)
                move_path_obj.parent.mkdir(parents=True, exist_ok=True)
                move_path_obj.write_text(new_content, encoding="utf-8")
                Path(hunk.path).unlink()
                affected.modified.append(hunk.move_path)
            else:
                unified_diff, new_content = derive_new_contents(hunk.path, hunk.chunks)
                Path(hunk.path).write_text(new_content, encoding="utf-8")
                affected.modified.append(hunk.path)

    return affected


async def apply_patch(patch_text: str) -> AffectedPaths:
    """Apply a patch to the filesystem."""
    hunks = parse_patch(patch_text)
    return await apply_hunks(hunks)


def get_file_hash(path: str) -> str:
    """Get MD5 hash of file contents."""
    path_obj = Path(path)
    if not path_obj.exists():
        return ""
    return hashlib.md5(path_obj.read_bytes()).hexdigest()
