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
    """Strip markdown fences and normalize whitespace on edit strings."""
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
    """Replace lines [start_line, end_line) in original with new_str."""
    start_char = sum(len(ln) for ln in file_lines_with_newlines[:start_line])
    end_char = start_char + sum(len(ln) for ln in file_lines_with_newlines[start_line:end_line])
    return original[:start_char] + new_str + original[end_char:]


def _tier1_exact_match(original: str, old_str: str, new_str: str, sanitized: bool) -> dict | None:
    occurrences = original.count(old_str)
    if occurrences == 1:
        result = {
            "ok": True,
            "new_content": original.replace(old_str, new_str, 1),
            "match_tier": "exact",
        }
        if sanitized:
            result["sanitized"] = True
        return result
    return None


def _tier2_line_exact_match(
    original: str, file_lines: list[str], lines_with_nl: list[str],
    old_lines: list[str], new_str: str, sanitized: bool
) -> dict | None:
    window_len = len(old_lines)
    if window_len > len(file_lines):
        return None

    line_matches: list[int] = []
    for i in range(len(file_lines) - window_len + 1):
        if file_lines[i:i + window_len] == old_lines:
            line_matches.append(i)

    if len(line_matches) == 1:
        start_idx = line_matches[0]
        result = {
            "ok": True,
            "new_content": replace_line_range(original, lines_with_nl, start_idx, start_idx + window_len, new_str),
            "match_tier": "line_exact",
        }
        if sanitized:
            result["sanitized"] = True
        return result
    return None


def _score_fuzzy_window(file_lines: list[str], old_lines: list[str]) -> tuple[list[tuple[int, float]], list[tuple[int, float]], float]:
    """Score all sliding windows for fuzzy match. Returns (candidates, near_matches, best_ratio)."""
    candidates: list[tuple[int, float]] = []
    all_near_matches: list[tuple[int, float]] = []
    best_ratio = 0.0
    window_len = len(old_lines)

    normalized_old = [line.strip() for line in old_lines]
    normalized_old_block = "\n".join(normalized_old)

    for i in range(len(file_lines) - window_len + 1):
        window = file_lines[i:i + window_len]
        normalized_window = [line.strip() for line in window]
        normalized_window_block = "\n".join(normalized_window)
        ratio = difflib.SequenceMatcher(None, normalized_old_block, normalized_window_block).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
        if ratio >= 0.75:
            candidates.append((i, ratio))
        if ratio > 0.5:
            all_near_matches.append((i, ratio))

    return candidates, all_near_matches, best_ratio


def _build_nearest_candidates(file_lines: list[str], old_lines: list[str], all_near_matches: list[tuple[int, float]]) -> list[dict]:
    sorted_matches = sorted(all_near_matches, key=lambda x: -x[1])
    result = []
    seen = set()
    for idx, _rat in sorted_matches:
        block_text = "\n".join(file_lines[idx:idx + len(old_lines)])
        key = (idx, idx + len(old_lines))
        if key not in seen:
            seen.add(key)
            result.append({
                "start_line": idx + 1,
                "end_line": idx + len(old_lines),
                "text": block_text,
            })
        if len(result) >= 3:
            break
    return result


def _tier3_fuzzy_match(
    original: str, file_lines: list[str], lines_with_nl: list[str],
    old_lines: list[str], new_str: str, sanitized: bool
) -> dict | None:
    window_len = len(old_lines)
    if window_len > len(file_lines):
        return None

    candidates, all_near_matches, best_ratio = _score_fuzzy_window(file_lines, old_lines)

    if len(candidates) == 1:
        start_idx = candidates[0][0]
        result = {
            "ok": True,
            "new_content": replace_line_range(original, lines_with_nl, start_idx, start_idx + window_len, new_str),
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
            result = {
                "ok": True,
                "new_content": replace_line_range(original, lines_with_nl, start_idx, start_idx + window_len, new_str),
                "match_tier": "fuzzy",
                "fuzzy_ratio": round(max_ratio, 3),
            }
            if sanitized:
                result["sanitized"] = True
            return result

        return _ambiguous_result(top_candidates, window_len, best_ratio, file_lines, old_lines, all_near_matches)

    return None


def _ambiguous_result(
    top_candidates: list[tuple[int, float]], window_len: int, max_ratio: float,
    file_lines: list[str], old_lines: list[str], all_near_matches: list[tuple[int, float]]
) -> dict:
    lines_detail = "\n".join(
        f"  Candidate {j+1}: lines {start+1}-{start+window_len}"
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
        "nearest_candidates": _build_nearest_candidates(file_lines, old_lines, all_near_matches),
    }


def _empty_old_lines_result() -> dict:
    return {
        "ok": False,
        "error": "old_str not found in file. Best fuzzy match ratio: 0.000 (threshold: 0.75). Tried exact, line-exact, and fuzzy matching.",
        "match_tier": None,
    }


def _no_match_result(best_ratio: float, file_lines: list[str], old_lines: list[str], all_near_matches: list[tuple[int, float]]) -> dict:
    return {
        "ok": False,
        "error": (
            f"old_str not found in file. Best fuzzy match ratio: {best_ratio:.3f} "
            f"(threshold: 0.75). Tried exact, line-exact, and fuzzy matching."
        ),
        "match_tier": None,
        "best_fuzzy_ratio": round(best_ratio, 3),
        "nearest_candidates": _build_nearest_candidates(file_lines, old_lines, all_near_matches),
    }


def propose_edit(original: str, old_str: str, new_str: str) -> dict:
    """4-tier edit matching."""
    old_str, new_str, sanitized = sanitize_edit_strings(old_str, new_str)

    # Tier 1: Exact string match
    result = _tier1_exact_match(original, old_str, new_str, sanitized)
    if result is not None:
        return result

    lines_with_nl = original.splitlines(keepends=True)
    file_lines = original.splitlines()
    old_lines = old_str.splitlines()

    if not old_lines:
        return _empty_old_lines_result()

    # Tier 2: Line-by-line exact match
    result = _tier2_line_exact_match(original, file_lines, lines_with_nl, old_lines, new_str, sanitized)
    if result is not None:
        return result

    # Tier 3: Whitespace-agnostic fuzzy matching
    result = _tier3_fuzzy_match(original, file_lines, lines_with_nl, old_lines, new_str, sanitized)
    if result is not None:
        return result

    # Tier 4: All tiers failed
    candidates, all_near_matches, best_ratio = _score_fuzzy_window(file_lines, old_lines)
    return _no_match_result(best_ratio, file_lines, old_lines, all_near_matches)
