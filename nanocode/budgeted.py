"""Section-aware budgeted reads for markdown files.

Ported from MiMo-Code's session/budgeted-read.ts.
Allocates token budgets across markdown sections, truncating within sections
when the budget is exceeded.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Section:
    """A markdown section with header, optional italic line, body, and index lines."""

    header: str
    italic: str
    body: list[str]
    index_lines: list[str]


@dataclass
class BudgetedReadResult:
    """Result of a budgeted read operation."""

    text: str
    truncated: bool
    total_tokens: int


def count_tokens(text: str) -> int:
    """Estimate token count (same algorithm as TokenCounter)."""
    if not text:
        return 0
    char_count = len(text)
    tokens = char_count // 4
    tokens += len(text.split())
    tokens = tokens // 2
    return max(1, tokens)


def parse_sections(text: str) -> tuple[list[str], list[Section]]:
    """Parse markdown into preamble and sections.

    Returns (preamble_lines, sections).
    """
    preamble: list[str] = []
    sections: list[Section] = []
    current: Section | None = None
    italic_seen = False

    for line in text.split("\n"):
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = Section(header=line, italic="", body=[], index_lines=[])
            italic_seen = False
            continue

        if current:
            if not italic_seen and line.startswith("_") and line.endswith("_"):
                current.italic = line
                italic_seen = True
                continue
            if line.strip().startswith("- See ") and ".md (" in line:
                current.index_lines.append(line)
            current.body.append(line)
        else:
            preamble.append(line)

    if current:
        sections.append(current)

    return preamble, sections


def read_budgeted(file_path: str, budget_tokens: int) -> BudgetedReadResult | None:
    """Read a file with a token budget. Truncates if exceeds budget.

    Args:
        file_path: Path to the file
        budget_tokens: Maximum tokens to return

    Returns:
        BudgetedReadResult or None if file doesn't exist
    """
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return None

    total_tokens = count_tokens(text)
    if total_tokens <= budget_tokens:
        return BudgetedReadResult(text=text, truncated=False, total_tokens=total_tokens)

    ratio = budget_tokens / total_tokens
    truncated_text = text[: int(len(text) * ratio * 0.95)]
    last_newline = truncated_text.rfind("\n")
    clean = truncated_text[:last_newline] if last_newline > 0 else truncated_text

    hint = (
        f"\n\nWarning: Truncated at ~{budget_tokens} tokens. "
        f"{file_path} is ~{total_tokens} tokens total. "
        f"Read('{file_path}', offset={len(clean)}) for the rest."
    )
    return BudgetedReadResult(
        text=clean + hint, truncated=True, total_tokens=total_tokens
    )


def read_budgeted_section_aware(
    file_path: str, budget_tokens: int
) -> BudgetedReadResult | None:
    """Read a file with section-aware budget allocation.

    Parses markdown sections and allocates budget across them.
    When budget is too small, returns header-only skeleton.

    Args:
        file_path: Path to the file
        budget_tokens: Maximum tokens to return

    Returns:
        BudgetedReadResult or None if file doesn't exist
    """
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return None

    total_tokens = count_tokens(text)
    if total_tokens <= budget_tokens:
        return BudgetedReadResult(text=text, truncated=False, total_tokens=total_tokens)

    preamble, sections = parse_sections(text)

    header_only_tokens = count_tokens(
        "\n".join(
            preamble
            + [s.header for s in sections]
            + [s.italic for s in sections if s.italic]
            + [line for s in sections for line in s.index_lines]
        )
    )

    if header_only_tokens >= budget_tokens:
        skeleton_lines = preamble.copy()
        for s in sections:
            skeleton_lines.append(s.header)
            if s.italic:
                skeleton_lines.append(s.italic)
            skeleton_lines.extend(s.index_lines)
            skeleton_lines.append("")

        hint = (
            f"\n\nWarning: File extremely large ({total_tokens} tokens vs budget {budget_tokens}). "
            f"Only structure shown.\n   Read('{file_path}') for full content."
        )
        return BudgetedReadResult(
            text="\n".join(skeleton_lines) + hint, truncated=True, total_tokens=total_tokens
        )

    out: list[str] = list(preamble)
    used = count_tokens("\n".join(out))

    for sec in sections:
        sec_overhead = "\n".join(
            [sec.header, sec.italic] + sec.index_lines
        )
        used += count_tokens(sec_overhead)
        out.append(sec.header)
        if sec.italic:
            out.append(sec.italic)
        out.extend(sec.index_lines)

        full_body = "\n".join(line for line in sec.body if line not in sec.index_lines)
        body_tokens = count_tokens(full_body)

        if used + body_tokens <= budget_tokens:
            out.append(full_body)
            used += body_tokens
        else:
            remaining = budget_tokens - used
            if remaining > 50:
                cut_len = int(len(full_body) * (remaining / body_tokens) * 0.95)
                out.append(full_body[:cut_len])
                used += remaining

        out.append("")

    hint = (
        f"\n\nWarning: Truncated at ~{budget_tokens} tokens. "
        f"{file_path} is ~{total_tokens} tokens total. "
        f"Read('{file_path}') for full content."
    )
    return BudgetedReadResult(
        text="\n".join(out) + hint, truncated=True, total_tokens=total_tokens
    )
