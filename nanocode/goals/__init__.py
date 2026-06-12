"""Goal/Stop Conditions - Independent judge model evaluation.

Based on MiMo-Code's goal system:
- Per-session stop-condition goals
- Independent judge model evaluates if condition is satisfied
- Prevents premature "optimistic stops"
- Configurable re-entry limits
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GoalStatus(StrEnum):
    """Goal status."""

    ACTIVE = "active"
    SATISFIED = "satisfied"
    IMPOSSIBLE = "impossible"
    CLEARED = "cleared"


@dataclass
class Verdict:
    """Judge verdict on goal completion."""

    ok: bool
    reason: str
    impossible: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "impossible": self.impossible,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Verdict":
        return cls(
            ok=data.get("ok", False),
            reason=data.get("reason", ""),
            impossible=data.get("impossible", False),
        )


@dataclass
class Goal:
    """A session-level stop-condition goal."""

    condition: str
    session_id: str
    status: GoalStatus = GoalStatus.ACTIVE
    react_count: int = 0
    last_verdict: Verdict | None = None
    created_at: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict:
        return {
            "condition": self.condition,
            "session_id": self.session_id,
            "status": self.status.value,
            "react_count": self.react_count,
            "last_verdict": self.last_verdict.to_dict() if self.last_verdict else None,
            "created_at": self.created_at,
        }


# Judge system prompt from MiMo-Code
JUDGE_SYSTEM = """You are evaluating a stop-condition hook in an AI coding assistant. Read the conversation transcript carefully, then judge whether the user-provided condition is satisfied.

Your response must be a JSON object with one of these shapes:
- {"ok": true, "reason": "<quote evidence from the transcript that satisfies the condition>"}
- {"ok": false, "reason": "<quote what is missing or what blocks the condition>"}
- {"ok": false, "impossible": true, "reason": "<explain why the condition can never be satisfied>"}

Always include a "reason" field, quoting specific text from the transcript whenever possible. If the transcript does not contain clear evidence that the condition is satisfied, return {"ok": false, "reason": "insufficient evidence in transcript"}.

Only use {"ok": false, "impossible": true} when the condition is genuinely unachievable in this session — for example: the condition is self-contradictory, it depends on a resource or capability that is unavailable, or the assistant has explicitly tried, exhausted reasonable approaches, and stated it cannot be done. Apply your own judgment when deciding this — the assistant claiming the goal is impossible is evidence, not proof; independently confirm the condition is genuinely unachievable rather than deferring to the assistant's self-assessment. Do not use it just because the goal has not been reached yet or because progress is slow. When in doubt, return {"ok": false} without "impossible"."""


def _judge_user_prompt(condition: str) -> str:
    """Create the user prompt for the judge."""
    return f"""Based on the conversation transcript above, has the following stopping condition been satisfied? Answer based on transcript evidence only.

Condition: {condition}"""


class GoalManager:
    """Manages session-level stop-condition goals with judge evaluation.

    Based on MiMo-Code's goal system.
    """

    def __init__(self, llm=None, max_react: int = 5):
        """Initialize the goal manager.

        Args:
            llm: LLM instance for judge evaluation
            max_react: Maximum re-entry count before allowing stop
        """
        self.llm = llm
        self.max_react = max_react
        self._goals: dict[str, Goal] = {}  # session_id -> Goal

    def set_goal(self, session_id: str, condition: str) -> Goal:
        """Set a stop-condition goal for a session.

        Args:
            session_id: Session identifier
            condition: Stop condition to evaluate

        Returns:
            Created goal
        """
        goal = Goal(
            condition=condition,
            session_id=session_id,
        )
        self._goals[session_id] = goal
        logger.info(f"Goal set for session {session_id}: {condition}")
        return goal

    def get_goal(self, session_id: str) -> Goal | None:
        """Get the active goal for a session."""
        return self._goals.get(session_id)

    def clear_goal(self, session_id: str) -> bool:
        """Clear the goal for a session.

        Returns:
            True if a goal was cleared
        """
        if session_id in self._goals:
            goal = self._goals.pop(session_id)
            goal.status = GoalStatus.CLEARED
            logger.info(f"Goal cleared for session {session_id}")
            return True
        return False

    def has_active_goal(self, session_id: str) -> bool:
        """Check if a session has an active goal."""
        goal = self._goals.get(session_id)
        return goal is not None and goal.status == GoalStatus.ACTIVE

    def bump_react(self, session_id: str) -> int:
        """Increment the re-entry counter.

        Returns:
            New count
        """
        goal = self._goals.get(session_id)
        if not goal:
            return 0
        goal.react_count += 1
        return goal.react_count

    def should_allow_stop(self, session_id: str) -> tuple[bool, str]:
        """Check if the agent should be allowed to stop.

        Returns:
            Tuple of (allowed, reason)
        """
        goal = self._goals.get(session_id)

        # No goal - allow stop
        if not goal:
            return True, "no active goal"

        # Goal already satisfied or impossible - allow stop
        if goal.status in [GoalStatus.SATISFIED, GoalStatus.IMPOSSIBLE]:
            return True, f"goal status: {goal.status.value}"

        # Max re-entries exceeded - allow stop
        if goal.react_count >= self.max_react:
            return True, f"max re-entries ({self.max_react}) exceeded"

        # Last verdict says OK - allow stop
        if goal.last_verdict and goal.last_verdict.ok:
            return True, "judge satisfied"

        # Last verdict says impossible - allow stop
        if goal.last_verdict and goal.last_verdict.impossible:
            return True, "judge determined impossible"

        # Otherwise - don't allow stop
        return False, "goal not yet satisfied"

    async def evaluate(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> Verdict:
        """Evaluate the goal condition against conversation transcript.

        Args:
            session_id: Session identifier
            messages: Conversation messages to evaluate

        Returns:
            Judge verdict
        """
        goal = self._goals.get(session_id)
        if not goal:
            return Verdict(ok=True, reason="no active goal")

        if not self.llm:
            logger.warning("No LLM available for judge evaluation")
            return Verdict(ok=False, reason="no LLM available for evaluation")

        # Build judge prompt
        transcript = self._format_transcript(messages)
        judge_prompt = f"{transcript}\n\n{_judge_user_prompt(goal.condition)}"

        try:
            from nanocode.llm import Message

            response = await self.llm.chat(
                [
                    Message("system", JUDGE_SYSTEM),
                    Message("user", judge_prompt),
                ],
                temperature=0,
            )

            # Parse verdict
            verdict = self._parse_verdict(response.content)
            goal.last_verdict = verdict

            # Update status based on verdict
            if verdict.ok:
                goal.status = GoalStatus.SATISFIED
                logger.info(f"Goal satisfied for session {session_id}: {verdict.reason}")
            elif verdict.impossible:
                goal.status = GoalStatus.IMPOSSIBLE
                logger.info(f"Goal impossible for session {session_id}: {verdict.reason}")

            return verdict

        except Exception as e:
            logger.error(f"Judge evaluation failed: {e}")
            # Fail open - don't block the agent
            return Verdict(ok=False, reason=f"judge error: {e}")

    def _format_transcript(self, messages: list[dict[str, Any]]) -> str:
        """Format conversation messages for the judge."""
        lines = ["Conversation Transcript:", "=" * 40]

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, list):
                # Handle multi-part content
                content_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            content_parts.append(part.get("text", ""))
                        elif part.get("type") == "tool_use":
                            content_parts.append(f"[Tool call: {part.get('name', 'unknown')}]")
                        elif part.get("type") == "tool_result":
                            content_parts.append("[Tool result]")
                    else:
                        content_parts.append(str(part))
                content = " ".join(content_parts)

            # Truncate very long content
            if len(content) > 2000:
                content = content[:2000] + f"... [{len(content)} chars total]"

            lines.append(f"\n{role.upper()}: {content}")

        return "\n".join(lines)

    def _parse_verdict(self, response: str) -> Verdict:
        """Parse judge response into a Verdict."""
        try:
            # Try to parse as JSON
            data = json.loads(response)
            return Verdict.from_dict(data)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from response
        import re
        json_match = re.search(r'\{[^{}]*"ok"\s*:\s*(true|false)[^{}]*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return Verdict.from_dict(data)
            except json.JSONDecodeError:
                pass

        # Default to not satisfied
        return Verdict(ok=False, reason=f"could not parse judge response: {response[:200]}")

    def get_stats(self) -> dict:
        """Get goal system statistics."""
        active = sum(1 for g in self._goals.values() if g.status == GoalStatus.ACTIVE)
        satisfied = sum(1 for g in self._goals.values() if g.status == GoalStatus.SATISFIED)
        impossible = sum(1 for g in self._goals.values() if g.status == GoalStatus.IMPOSSIBLE)

        return {
            "total_goals": len(self._goals),
            "active": active,
            "satisfied": satisfied,
            "impossible": impossible,
            "max_react": self.max_react,
        }


# Global instance
_goal_manager: GoalManager | None = None


def get_goal_manager(llm=None, max_react: int = 5) -> GoalManager:
    """Get or create the global goal manager."""
    global _goal_manager
    if _goal_manager is None:
        _goal_manager = GoalManager(llm=llm, max_react=max_react)
    elif llm and not _goal_manager.llm:
        _goal_manager.llm = llm
    return _goal_manager


def reset_goal_manager():
    """Reset the global goal manager."""
    global _goal_manager
    _goal_manager = None
