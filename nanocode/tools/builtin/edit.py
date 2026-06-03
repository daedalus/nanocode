"""4-tier edit matching engine for file edits.

Ported from Aura-IDE (fs_write.py) with adaptations for nanocode.

Tiers:
  1. Exact string match (fast path)
  2. Line-by-line exact match
  3. Whitespace-agnostic fuzzy matching (difflib.SequenceMatcher, threshold 0.75)
  4. Failure with nearest candidates
"""

import difflib
import re


def sanitize_edit_strings(old_str: str, new_str: str) -> tuple[str, str, bool]:
    """Strip markdown fences and normalize whitespace on edit strings.

    Args:
        old_str: The text to find.
        new_str: The replacement text.

    Returns:
        (sanitized_old, sanitized_new, was_sanitized)
    """
    sanitized = False

    old = old_str.strip()
    new = new_str.strip()

    if old != old_str:
        sanitized = True
    if new != new_str:
        sanitized = True

    lines = old.split("\n")
    if len(lines) >= 2:
        first = lines[0]
        last = lines[-1]
        open_match = re.match(r"^(\s*)(`{3,})(?:\s*\w*)?\s*$", first)
        close_match = re.match(r"^(\s*)(`{3,})\s*$", last)
        if open_match and close_match and open_match.group(2) == close_match.group(2):
            old = "\n".join(lines[1:-1])
            sanitized = True

    old = old.rstrip("\n")

    return old, new, sanitized


def replace_line_range(
    original: str, file_lines_with_newlines: list[str], start_line: int, end_line: int, new_str: str
) -> str:
    """Replace lines [start_line, end_line) in original with new_str.

    start_line and end_line are 0-indexed (exclusive end).
    file_lines_with_newlines must come from original.splitlines(keepends=True).
    """
    start_char = sum(len(ln) for ln in file_lines_with_newlines[:start_line])
    end_char = start_char + sum(len(ln) for ln in file_lines_with_newlines[start_line:end_line])
    return original[:start_char] + new_str + original[end_char:]


def propose_edit(original: str, old_str: str, new_str: str) -> dict:
    """4-tier edit matching.

    Args:
        original: Full file content.
        old_str: Text to find and replace.
        new_str: Replacement text.

    Returns:
        Dict with keys: ok, new_content (on success),
        or ok=False with error details and nearest_candidates on failure.
        match_tier: "exact", "line_exact", "fuzzy", or None on failure.
    """
    old_str, new_str, sanitized = sanitize_edit_strings(old_str, new_str)

    # ---- Tier 1: Exact string match ----
    occurrences = original.count(old_str)
    if occurrences == 1:
        proposed = original.replace(old_str, new_str, 1)
        result = {
            "ok": True,
            "new_content": proposed,
            "match_tier": "exact",
        }
        if sanitized:
            result["sanitized"] = True
        return result

    lines_with_nl = original.splitlines(keepends=True)
    file_lines = original.splitlines()
    old_lines = old_str.splitlines()

    if not old_lines:
        return {
            "ok": False,
            "error": "old_str not found in file. Best fuzzy match ratio: 0.000 (threshold: 0.75). Tried exact, line-exact, and fuzzy matching.",
            "match_tier": None,
        }

    # ---- Tier 2: Line-by-line exact match ----
    line_matches: list[int] = []
    window_len = len(old_lines)
    if window_len <= len(file_lines):
        for i in range(len(file_lines) - window_len + 1):
            if file_lines[i:i + window_len] == old_lines:
                line_matches.append(i)

    if len(line_matches) == 1:
        start_idx = line_matches[0]
        proposed = replace_line_range(original, lines_with_nl, start_idx, start_idx + window_len, new_str)
        result = {
            "ok": True,
            "new_content": proposed,
            "match_tier": "line_exact",
        }
        if sanitized:
            result["sanitized"] = True
        return result

    # ---- Tier 3: Whitespace-agnostic fuzzy matching ----
    candidates: list[tuple[int, float]] = []
    best_ratio = 0.0
    all_near_matches: list[tuple[int, float]] = []

    if len(old_lines) <= len(file_lines):
        normalized_old = [line.strip() for line in old_lines]
        normalized_old_block = "\n".join(normalized_old)

        for i in range(len(file_lines) - len(old_lines) + 1):
            window = file_lines[i:i + len(old_lines)]
            normalized_window = [line.strip() for line in window]
            normalized_window_block = "\n".join(normalized_window)
            ratio = difflib.SequenceMatcher(
                None, normalized_old_block, normalized_window_block
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
            if ratio >= 0.75:
                candidates.append((i, ratio))
            if ratio > 0.5:
                all_near_matches.append((i, ratio))

    def _build_nearest_candidates() -> list[dict]:
        sorted_matches = sorted(all_near_matches, key=lambda x: -x[1])
        result = []
        seen = set()
        for idx, rat in sorted_matches:
            block_text = "\n".join(file_lines[idx:idx + window_len])
            key = (idx, idx + window_len)
            if key not in seen:
                seen.add(key)
                result.append({
                    "start_line": idx + 1,
                    "end_line": idx + window_len,
                    "text": block_text,
                })
            if len(result) >= 3:
                break
        return result

    if len(candidates) == 1:
        start_idx = candidates[0][0]
        proposed = replace_line_range(
            original, lines_with_nl, start_idx, start_idx + len(old_lines), new_str
        )
        result = {
            "ok": True,
            "new_content": proposed,
            "match_tier": "fuzzy",
            "fuzzy_ratio": round(candidates[0][1], 3),
        }
        if sanitized:
            result["sanitized"] = True
        return result

    if len(candidates) > 1:
        max_ratio = max(r for _, r in candidates)
        top_candidates = [(i, r) for i, r in candidates if max_ratio - r < 0.001]
        if len(top_candidates) == 1:
            start_idx = top_candidates[0][0]
            proposed = replace_line_range(
                original, lines_with_nl, start_idx, start_idx + len(old_lines), new_str
            )
            result = {
                "ok": True,
                "new_content": proposed,
                "match_tier": "fuzzy",
                "fuzzy_ratio": round(max_ratio, 3),
            }
            if sanitized:
                result["sanitized"] = True
            return result

        line_count = len(old_lines)
        lines_detail = "\n".join(
            f"  Candidate {j+1}: lines {start+1}-{start+line_count}"
            for j, (start, _) in enumerate(top_candidates)
        )
        return {
            "ok": False,
            "error": (
                f"ambiguous: old_str matches {len(top_candidates)} blocks "
                f"in the file (best ratio: {max_ratio:.3f}).\n"
                f"{lines_detail}\n"
                f"Add more surrounding context lines to disambiguate."
            ),
            "match_tier": None,
            "best_fuzzy_ratio": round(max_ratio, 3),
            "nearest_candidates": _build_nearest_candidates(),
        }

    # ---- All tiers failed ----
    return {
        "ok": False,
        "error": (
            f"old_str not found in file. Best fuzzy match ratio: {best_ratio:.3f} "
            f"(threshold: 0.75). Tried exact, line-exact, and fuzzy matching."
        ),
        "match_tier": None,
        "best_fuzzy_ratio": round(best_ratio, 3),
        "nearest_candidates": _build_nearest_candidates(),
    }
