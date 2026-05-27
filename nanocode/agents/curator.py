"""Curator — background skill maintenance orchestrator.

The curator periodically reviews agent-created skills and maintains the
collection. It runs inactivity-triggered: when the agent is idle and the
last curator run was longer than ``interval_hours`` ago, ``maybe_run_curator``
spawns a review pass.

Responsibilities:
  - Auto-transition lifecycle states based on derived skill activity
  - Spawn a background LLM review that suggests consolidations
  - Persist curator state in the skills directory
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_INTERVAL_HOURS = 24 * 7
DEFAULT_STALE_AFTER_DAYS = 30
DEFAULT_ARCHIVE_AFTER_DAYS = 90


# ---------------------------------------------------------------------------
# .curator_state — persistent scheduler + status
# ---------------------------------------------------------------------------

def _get_storage_root() -> Path:
    """Get the data directory for nanocode state files."""
    xdg_data = os.environ.get(
        "XDG_DATA_HOME",
        str(Path.home() / ".local" / "share"),
    )
    return Path(xdg_data) / "nanocode"


def _state_file() -> Path:
    return _get_storage_root() / "skills" / ".curator_state"


def _default_state() -> dict[str, Any]:
    return {
        "last_run_at": None,
        "last_run_duration_seconds": None,
        "last_run_summary": None,
        "paused": False,
        "run_count": 0,
    }


def load_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            base = _default_state()
            base.update({k: v for k, v in data.items() if k in base or k.startswith("_")})
            return base
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("Failed to read curator state: %s", e)
    return _default_state()


def save_state(data: dict[str, Any]) -> None:
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".curator_state_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Failed to save curator state: %s", e, exc_info=True)


def set_paused(paused: bool) -> None:
    state = load_state()
    state["paused"] = bool(paused)
    save_state(state)


def is_paused() -> bool:
    return bool(load_state().get("paused"))


# ---------------------------------------------------------------------------
# Config access from agent config
# ---------------------------------------------------------------------------

def _load_config(agent: Any | None = None) -> dict[str, Any]:
    try:
        if agent is not None and hasattr(agent, "config"):
            cfg = agent.config.get("curator", {})
            if isinstance(cfg, dict):
                return cfg
    except Exception:
        pass
    return {}


def is_enabled(agent: Any | None = None) -> bool:
    cfg = _load_config(agent)
    return bool(cfg.get("enabled", True))


def get_interval_hours(agent: Any | None = None) -> int:
    cfg = _load_config(agent)
    try:
        return int(cfg.get("interval_hours", DEFAULT_INTERVAL_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_HOURS


def get_stale_after_days(agent: Any | None = None) -> int:
    cfg = _load_config(agent)
    try:
        return int(cfg.get("stale_after_days", DEFAULT_STALE_AFTER_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_STALE_AFTER_DAYS


def get_archive_after_days(agent: Any | None = None) -> int:
    cfg = _load_config(agent)
    try:
        return int(cfg.get("archive_after_days", DEFAULT_ARCHIVE_AFTER_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_ARCHIVE_AFTER_DAYS


# ---------------------------------------------------------------------------
# Interval check
# ---------------------------------------------------------------------------

def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def should_run_now(agent: Any | None = None, now: datetime | None = None) -> bool:
    """Return True if the curator should run immediately.

    Gates:
      - curator.enabled == True (default True)
      - not paused
      - last_run_at absent OR older than interval_hours

    First-run: seeds ``last_run_at`` to "now" and defers the first real pass
    by one full interval.
    """
    if not is_enabled(agent):
        return False
    if is_paused():
        return False

    state = load_state()
    last = _parse_iso(state.get("last_run_at"))
    if last is None:
        if now is None:
            now = datetime.now(UTC)
        try:
            state["last_run_at"] = now.isoformat()
            state["last_run_summary"] = (
                "deferred first run — curator seeded, will run after one interval"
            )
            save_state(state)
        except Exception:
            pass
        return False

    if now is None:
        now = datetime.now(UTC)
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    interval = timedelta(hours=get_interval_hours(agent))
    return (now - last) >= interval


# ---------------------------------------------------------------------------
# Curator review prompt (for LLM consolidation pass)
# ---------------------------------------------------------------------------

CURATOR_REVIEW_PROMPT = (
    "You are running as a background skill CURATOR. Your job is to review "
    "the skill library below and suggest improvements.\n\n"
    "Hard rules:\n"
    "1. Do NOT delete any skill — only suggest archival.\n"
    "2. Do NOT touch bundled or hub-installed skills.\n\n"
    "Look for:\n"
    "  - Skills that overlap or could be consolidated under an umbrella.\n"
    "  - Skills whose names are too narrow (contain PR numbers, specific "
    "error strings, audit/salvage artifacts).\n"
    "  - Skills that should be archived due to staleness.\n\n"
    "Format your response as structured YAML:\n"
    "```yaml\n"
    "consolidations:\n"
    "  - from: <skill-name>\n"
    "    into: <umbrella-name>\n"
    "    reason: <why merged>\n"
    "archivals:\n"
    "  - name: <skill-name>\n"
    "    reason: <why archive>\n"
    "```"
)


def format_skills_report(skills: list[dict]) -> str:
    """Format the current skill library as a report for the curator."""
    if not skills:
        return "(no skills in library)"

    lines = [f"Skills in library ({len(skills)} total):"]
    for s in sorted(skills, key=lambda x: x.get("name", "")):
        name = s.get("name", "?")
        desc = s.get("description", "")[:80]
        loc = s.get("location", "")
        lines.append(f"  - {name}: {desc}")
        if loc:
            lines.append(f"    location: {loc}")
    return "\n".join(lines)


async def run_curator_pass(agent: Any) -> str | None:
    """Run one curator pass: list skills, call LLM, return summary.

    Returns a human-readable summary string, or ``None`` if nothing changed.
    """
    if not hasattr(agent, "skills_manager") or not agent.skills_manager:
        return "Curator: no skills manager available"

    skills_data = agent.skills_manager.list_skills()
    if not skills_data:
        return "Curator: no skills to review"

    report = format_skills_report(skills_data)
    prompt = CURATOR_REVIEW_PROMPT + "\n\n" + report
    messages = [{"role": "user", "content": prompt}]

    try:
        from nanocode.llm import create_llm

        curator_llm = create_llm(
            provider=getattr(agent.llm, "provider", None) or "opencode",
            model=getattr(agent.llm, "model", "big-pickle"),
            api_key=getattr(agent.llm, "api_key", None),
            base_url=getattr(agent.llm, "base_url", None),
        )
        response = await curator_llm.chat(messages)
    except Exception as e:
        logger.warning("Curator LLM call failed: %s", e)
        return None

    content = response.get("content", "") if isinstance(response, dict) else getattr(response, "content", "")
    if not content:
        return None

    return content


__all__ = [
    "CURATOR_REVIEW_PROMPT",
    "should_run_now",
    "run_curator_pass",
    "load_state",
    "save_state",
    "set_paused",
    "is_paused",
    "format_skills_report",
]
