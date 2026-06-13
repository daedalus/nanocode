"""Plan Follow-up - Mode transition after plan completes.

Ported from kilo's kilocode/plan-followup.ts.
Handles the transition from plan mode to implementation mode with handover summaries.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


HANDOVER_PROMPT = """You are summarizing a planning session to hand off to an implementation session.

The plan itself will be provided separately — do NOT repeat it. Instead, focus on information discovered during planning that would help the implementing agent but is NOT already in the plan text.

Produce a concise summary using this template:
---

## Discoveries

[Key findings from code exploration — architecture patterns, gotchas, edge cases, relevant existing code that the plan references but doesn't fully explain]

## Relevant Files

[Structured list of files/directories that were read or discussed, with brief notes on what's relevant in each]

## Implementation Notes

[Any important context: conventions to follow, potential pitfalls, dependencies between steps, things the implementing agent should watch out for]
---

If there is nothing useful to add beyond what the plan already says, respond with an empty string.
Keep the summary concise — focus on high-entropy information that would save the implementing agent time."""


@dataclass
class TodoItem:
    """A todo item for formatting."""

    content: str
    status: str = "pending"


def format_todos(todos: list[TodoItem]) -> str:
    """Format todo list for inclusion in handover.

    Args:
        todos: List of TodoItem objects

    Returns:
        Formatted todo string
    """
    if not todos:
        return ""

    icons = {
        "completed": "[x]",
        "in_progress": "[~]",
        "cancelled": "[-]",
    }

    lines = []
    for t in todos:
        icon = icons.get(t.status, "[ ]")
        lines.append(f"- {icon} {t.content}")

    return "\n".join(lines)


async def generate_handover(
    messages: list[dict[str, Any]],
    model_info: dict[str, str] | None = None,
    todo_items: list[TodoItem] | None = None,
) -> str:
    """Generate a handover summary from planning session messages.

    Args:
        messages: Planning session messages
        model_info: Optional model info dict with provider/model keys
        todo_items: Optional todo list to include

    Returns:
        Handover summary string
    """
    try:
        from nanocode.llm import create_llm_from_model_id

        model_id = "default"
        if model_info:
            provider = model_info.get("provider", "")
            model = model_info.get("model", "")
            if provider and model:
                model_id = f"{provider}/{model}"

        llm, _ = await create_llm_from_model_id(model_id)

        conversation = "\n".join(
            f"{m.get('role', 'unknown')}: {m.get('content', '')}"
            for m in messages
            if m.get("content")
        )

        prompt = f"{conversation}\n\n{HANDOVER_PROMPT}"

        from nanocode.llm import Message

        response = await llm.chat([Message("user", prompt)])
        result = response.content.strip()

        if todo_items:
            todo_str = format_todos(todo_items)
            if todo_str:
                result += f"\n\n## Todo List\n\n{todo_str}"

        return result

    except Exception as e:
        logger.warning(f"Failed to generate handover: {e}")
        return ""


def build_implementation_prompt(
    plan: str,
    handover: str = "",
    todo_items: list[TodoItem] | None = None,
) -> str:
    """Build the implementation prompt from plan and handover.

    Args:
        plan: The plan text
        handover: Optional handover summary
        todo_items: Optional todo list

    Returns:
        Implementation prompt string
    """
    sections = [f"Implement the following plan:\n\n{plan}"]

    if handover:
        sections.append(f"## Handover from Planning Session\n\n{handover}")

    if todo_items:
        todo_str = format_todos(todo_items)
        if todo_str:
            sections.append(f"## Todo List\n\n{todo_str}")

    return "\n\n".join(sections)


@dataclass
class PlanFollowupResult:
    """Result of plan follow-up decision."""

    action: str  # "continue", "new_session", or "cancelled"
    prompt: str = ""
    handover: str = ""


async def handle_plan_followup(
    plan: str,
    messages: list[dict[str, Any]],
    model_info: dict[str, str] | None = None,
    todo_items: list[TodoItem] | None = None,
) -> PlanFollowupResult:
    """Handle plan follow-up - ask user whether to continue or start new session.

    Args:
        plan: The plan text from the planning session
        messages: Planning session messages
        model_info: Optional model info
        todo_items: Optional todo list

    Returns:
        PlanFollowupResult with action and prompt
    """
    handover = await generate_handover(messages, model_info, todo_items)

    prompt = build_implementation_prompt(plan, handover, todo_items)

    return PlanFollowupResult(
        action="continue",
        prompt=prompt,
        handover=handover,
    )
