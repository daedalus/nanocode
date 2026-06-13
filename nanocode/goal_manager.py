"""Goal/Stop Condition - Set stopping conditions for autonomous loops.

Ported from MiMo-Code's session/goal.ts.
Prevents premature optimistic stops during autonomous work.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


JUDGE_PROMPT = """You are evaluating whether a goal has been achieved in a conversation.

The user set this goal:
---

{goal}
---

Here is the conversation so far:
---

{conversation}
---

Determine if the goal has been COMPLETELY achieved. Consider:
1. Has the user's explicit request been fulfilled?
2. Are there any incomplete steps or missing deliverables?
3. Would a reasonable person consider this work done?

Respond with ONLY a JSON object:
{{"achieved": true/false, "reasoning": "<brief explanation>"}}

Be strict - only mark as achieved if the goal is genuinely complete."""


@dataclass
class Goal:
    """A stopping condition for the agent."""

    text: str
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GoalEvaluation:
    """Result of evaluating a goal."""

    achieved: bool
    reasoning: str
    goal: Goal


class GoalManager:
    """Manages stopping conditions for autonomous loops."""

    def __init__(self):
        self._goal: Goal | None = None
        self._history: list[GoalEvaluation] = []

    def set_goal(self, text: str, metadata: dict[str, Any] | None = None) -> Goal:
        """Set a stopping condition.

        Args:
            text: The goal/stopping condition description
            metadata: Optional metadata

        Returns:
            The created Goal
        """
        import time

        self._goal = Goal(
            text=text,
            created_at=time.time(),
            metadata=metadata or {},
        )
        logger.info(f"Goal set: {text[:100]}...")
        return self._goal

    def get_goal(self) -> Goal | None:
        """Get the current goal."""
        return self._goal

    def clear_goal(self) -> None:
        """Clear the current goal."""
        self._goal = None

    def has_goal(self) -> bool:
        """Check if a goal is set."""
        return self._goal is not None

    async def evaluate(self, conversation: list[dict[str, Any]], judge_llm: Any | None = None) -> GoalEvaluation:
        """Evaluate whether the current goal has been achieved.

        Args:
            conversation: Conversation messages
            judge_llm: LLM instance for evaluation

        Returns:
            GoalEvaluation with achieved status and reasoning
        """
        if not self._goal:
            return GoalEvaluation(
                achieved=True,
                reasoning="No goal set",
                goal=Goal(text=""),
            )

        if judge_llm is None:
            logger.warning("No judge LLM provided, assuming goal not achieved")
            return GoalEvaluation(
                achieved=False,
                reasoning="No judge model available for evaluation",
                goal=self._goal,
            )

        from nanocode.llm import Message

        formatted_conv = "\n".join(
            f"{m.get('role', 'unknown')}: {m.get('content', '')}"
            for m in conversation
            if m.get("content")
        )

        prompt = JUDGE_PROMPT.format(
            goal=self._goal.text,
            conversation=formatted_conv[-2000:],
        )

        try:
            response = await judge_llm.chat([Message("user", prompt)])
            result_text = response.content.strip()

            import json

            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text[:-3]

            result = json.loads(result_text)
            achieved = result.get("achieved", False)
            reasoning = result.get("reasoning", "")

            evaluation = GoalEvaluation(
                achieved=achieved,
                reasoning=reasoning,
                goal=self._goal,
            )

            self._history.append(evaluation)
            return evaluation

        except Exception as e:
            logger.warning(f"Goal evaluation failed: {e}")
            return GoalEvaluation(
                achieved=False,
                reasoning=f"Evaluation failed: {e}",
                goal=self._goal,
            )

    def get_history(self) -> list[GoalEvaluation]:
        """Get evaluation history."""
        return list(self._history)

    def should_stop(self) -> bool:
        """Check if the agent should stop based on goal evaluation history.

        Returns:
            True if the most recent evaluation found the goal achieved
        """
        if not self._history:
            return False
        return self._history[-1].achieved


_goal_manager: GoalManager | None = None


def get_goal_manager() -> GoalManager:
    """Get or create the global goal manager."""
    global _goal_manager
    if _goal_manager is None:
        _goal_manager = GoalManager()
    return _goal_manager
