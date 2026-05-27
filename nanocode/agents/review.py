"""Background memory/skill review — lightweight post-turn self-improvement.

After every turn, ``AutonomousAgent._spawn_background_review`` fires a
background task that replays the conversation snapshot to the LLM with a
structured review prompt. The LLM evaluates whether memory or skill updates
are warranted and describes them in natural language.

The background review runs:
  - With a restricted tool set (memory + skill management only)
  - In a separate asyncio task so the main thread is never blocked
  - Using the same LLM provider/model as the parent agent
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_REVIEW_PROMPT = (
    "Review the conversation above and consider saving to memory if appropriate.\n\n"
    "Focus on:\n"
    "1. Has the user revealed things about themselves — their persona, desires, "
    "preferences, or personal details worth remembering?\n"
    "2. Has the user expressed expectations about how you should behave, their work "
    "style, or ways they want you to operate?\n\n"
    "If something stands out, describe what to save. "
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)

_SKILL_REVIEW_PROMPT = (
    "Review the conversation above and update the skill library. Be "
    "ACTIVE — most sessions produce at least one skill update, even if "
    "small.\n\n"
    "Signals to look for (any one warrants action):\n"
    "  - User corrected your style, tone, format, or workflow. "
    "Frustration signals like 'stop doing X', 'this is too verbose', "
    "'just give me the answer' are FIRST-CLASS skill signals.\n"
    "  - Non-trivial technique, fix, workaround, or debugging path emerged.\n"
    "  - A skill that was loaded or consulted turned out wrong or outdated.\n\n"
    "Decisions, in order of preference:\n"
    "  1. UPDATE A CURRENTLY-LOADED SKILL with new insights.\n"
    "  2. ADD A SUPPORT FILE under an existing umbrella skill.\n"
    "  3. CREATE A NEW SKILL when nothing existing covers the class.\n\n"
    "If nothing to update, say 'Nothing to save.' and stop."
)

_COMBINED_REVIEW_PROMPT = (
    "Review the conversation above and update two things:\n\n"
    "**Memory**: who the user is. Did the user reveal persona, "
    "desires, preferences, personal details, or expectations about "
    "how you should behave?\n\n"
    "**Skills**: how to do this class of task. Be ACTIVE — most "
    "sessions produce at least one skill update.\n\n"
    "Signals that warrant a skill update:\n"
    "  - User corrected your style, tone, format, or approach.\n"
    "  - Non-trivial technique, fix, workaround, or debugging path emerged.\n"
    "  - A skill that was loaded turned out wrong, missing, or outdated.\n\n"
    "Decisions for skills (pick the earliest that fits):\n"
    "  1. UPDATE A CURRENTLY-LOADED SKILL.\n"
    "  2. UPDATE AN EXISTING SKILL that covers the territory.\n"
    "  3. CREATE A NEW SKILL when nothing existing covers the class.\n\n"
    "If genuinely nothing stands out on either dimension, say "
    "'Nothing to save.' and stop — but don't reach for that as a default."
)


def summarize_background_review_actions(
    review_content: str,
) -> list[str]:
    """Extract human-readable action items from the review LLM's output."""
    if not review_content or "Nothing to save." in review_content:
        return []
    actions: list[str] = []
    lines = review_content.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            actions.append(stripped.lstrip("- *").strip())
        elif any(kw in stripped.lower() for kw in ("save", "create", "update", "add", "archive")):
            actions.append(stripped)
    return actions


async def spawn_background_review(
    agent: Any,
    messages_snapshot: list[dict],
    review_memory: bool = False,
    review_skills: bool = False,
) -> str | None:
    """Run a lightweight background review and return a summary string.

    Calls the LLM once with the conversation snapshot and a structured
    review prompt. Returns a human-readable action summary, or ``None``
    if nothing was worth saving.
    """
    if not review_memory and not review_skills:
        return None

    if review_memory and review_skills:
        prompt = _COMBINED_REVIEW_PROMPT
    elif review_memory:
        prompt = _MEMORY_REVIEW_PROMPT
    else:
        prompt = _SKILL_REVIEW_PROMPT

    messages = list(messages_snapshot)
    messages.append({"role": "user", "content": prompt})

    try:
        review_llm = _create_review_llm(agent)
        response = await review_llm.chat(messages)
    except Exception as e:
        logger.warning("Background review LLM call failed: %s", e)
        return None

    content = response.get("content", "") if isinstance(response, dict) else getattr(response, "content", "")
    if not content or "Nothing to save." in content:
        return None

    actions = summarize_background_review_actions(content)
    if actions:
        return "Self-improvement review: " + " · ".join(dict.fromkeys(actions))
    return None


def _create_review_llm(agent: Any):
    """Create a lightweight LLM instance for background review.

    Inherits the parent agent's provider and model so the review uses
    the same auth and prefix cache.
    """
    from nanocode.llm import create_llm

    provider = getattr(agent, "_review_provider", None) or getattr(agent.llm, "provider", None) or "opencode"
    review_llm = create_llm(
        provider=provider,
        model=getattr(agent.llm, "model", "big-pickle"),
        api_key=getattr(agent.llm, "api_key", None),
        base_url=getattr(agent.llm, "base_url", None),
    )
    return review_llm


__all__ = [
    "_MEMORY_REVIEW_PROMPT",
    "_SKILL_REVIEW_PROMPT",
    "_COMBINED_REVIEW_PROMPT",
    "spawn_background_review",
    "summarize_background_review_actions",
]
