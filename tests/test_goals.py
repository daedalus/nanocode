"""Tests for the Goal/Stop Conditions system."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanocode.goals import (
    GoalManager,
    Goal,
    Verdict,
    GoalStatus,
    get_goal_manager,
    reset_goal_manager,
)


class TestVerdict:
    """Tests for Verdict dataclass."""

    def test_verdict_creation(self):
        """Test creating a verdict."""
        verdict = Verdict(ok=True, reason="test passed")
        assert verdict.ok is True
        assert verdict.reason == "test passed"
        assert verdict.impossible is False

    def test_verdict_impossible(self):
        """Test creating an impossible verdict."""
        verdict = Verdict(ok=False, reason="cannot be done", impossible=True)
        assert verdict.ok is False
        assert verdict.impossible is True

    def test_verdict_to_dict(self):
        """Test converting verdict to dict."""
        verdict = Verdict(ok=True, reason="done")
        d = verdict.to_dict()
        assert d["ok"] is True
        assert d["reason"] == "done"
        assert d["impossible"] is False

    def test_verdict_from_dict(self):
        """Test creating verdict from dict."""
        verdict = Verdict.from_dict({"ok": True, "reason": "test"})
        assert verdict.ok is True
        assert verdict.reason == "test"


class TestGoal:
    """Tests for Goal dataclass."""

    def test_goal_creation(self):
        """Test creating a goal."""
        goal = Goal(
            condition="all tests pass",
            session_id="session-123",
        )
        assert goal.condition == "all tests pass"
        assert goal.session_id == "session-123"
        assert goal.status == GoalStatus.ACTIVE
        assert goal.react_count == 0

    def test_goal_to_dict(self):
        """Test converting goal to dict."""
        goal = Goal(condition="done", session_id="s1")
        d = goal.to_dict()
        assert d["condition"] == "done"
        assert d["session_id"] == "s1"
        assert d["status"] == "active"


class TestGoalManager:
    """Tests for GoalManager."""

    def test_init(self):
        """Test manager initialization."""
        manager = GoalManager()
        assert manager.max_react == 5
        assert len(manager._goals) == 0

    def test_set_goal(self):
        """Test setting a goal."""
        manager = GoalManager()
        goal = manager.set_goal("session-1", "implement feature")

        assert goal.condition == "implement feature"
        assert goal.session_id == "session-1"
        assert goal.status == GoalStatus.ACTIVE
        assert manager.has_active_goal("session-1")

    def test_get_goal(self):
        """Test getting a goal."""
        manager = GoalManager()
        manager.set_goal("session-1", "test condition")

        goal = manager.get_goal("session-1")
        assert goal is not None
        assert goal.condition == "test condition"

    def test_get_nonexistent_goal(self):
        """Test getting a nonexistent goal."""
        manager = GoalManager()
        goal = manager.get_goal("nonexistent")
        assert goal is None

    def test_clear_goal(self):
        """Test clearing a goal."""
        manager = GoalManager()
        manager.set_goal("session-1", "test")

        result = manager.clear_goal("session-1")
        assert result is True
        assert not manager.has_active_goal("session-1")

    def test_clear_nonexistent_goal(self):
        """Test clearing a nonexistent goal."""
        manager = GoalManager()
        result = manager.clear_goal("nonexistent")
        assert result is False

    def test_bump_react(self):
        """Test incrementing re-entry counter."""
        manager = GoalManager()
        manager.set_goal("session-1", "test")

        count = manager.bump_react("session-1")
        assert count == 1

        count = manager.bump_react("session-1")
        assert count == 2

    def test_bump_react_nonexistent(self):
        """Test bumping nonexistent goal returns 0."""
        manager = GoalManager()
        count = manager.bump_react("nonexistent")
        assert count == 0

    def test_should_allow_stop_no_goal(self):
        """Test allow stop when no goal."""
        manager = GoalManager()
        allowed, reason = manager.should_allow_stop("session-1")
        assert allowed is True
        assert "no active goal" in reason

    def test_should_allow_stop_max_react(self):
        """Test allow stop when max re-entries exceeded."""
        manager = GoalManager(max_react=3)
        manager.set_goal("session-1", "test")

        # Bump to max
        for _ in range(3):
            manager.bump_react("session-1")

        allowed, reason = manager.should_allow_stop("session-1")
        assert allowed is True
        assert "max re-entries" in reason

    def test_should_allow_stop_satisfied_verdict(self):
        """Test allow stop when judge says OK."""
        manager = GoalManager()
        goal = manager.set_goal("session-1", "test")
        goal.last_verdict = Verdict(ok=True, reason="done")

        allowed, reason = manager.should_allow_stop("session-1")
        assert allowed is True
        assert "satisfied" in reason

    def test_should_allow_stop_impossible_verdict(self):
        """Test allow stop when judge says impossible."""
        manager = GoalManager()
        goal = manager.set_goal("session-1", "test")
        goal.last_verdict = Verdict(ok=False, reason="cannot", impossible=True)

        allowed, reason = manager.should_allow_stop("session-1")
        assert allowed is True
        assert "impossible" in reason

    def test_should_not_allow_stop_active(self):
        """Test don't allow stop when goal is active and not satisfied."""
        manager = GoalManager()
        manager.set_goal("session-1", "test")

        allowed, reason = manager.should_allow_stop("session-1")
        assert allowed is False
        assert "not yet satisfied" in reason

    @pytest.mark.asyncio
    async def test_evaluate_no_llm(self):
        """Test evaluation without LLM returns error."""
        manager = GoalManager(llm=None)
        manager.set_goal("session-1", "test")

        verdict = await manager.evaluate("session-1", [])
        assert verdict.ok is False
        assert "no LLM" in verdict.reason

    @pytest.mark.asyncio
    async def test_evaluate_with_llm(self):
        """Test evaluation with mock LLM."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"ok": true, "reason": "all tests pass"}'
        mock_llm.chat = AsyncMock(return_value=mock_response)

        manager = GoalManager(llm=mock_llm)
        manager.set_goal("session-1", "all tests pass")

        messages = [
            {"role": "user", "content": "run tests"},
            {"role": "assistant", "content": "running tests..."},
            {"role": "assistant", "content": "all tests passed"},
        ]

        verdict = await manager.evaluate("session-1", messages)
        assert verdict.ok is True
        assert "tests pass" in verdict.reason

    def test_parse_verdict_json(self):
        """Test parsing JSON verdict."""
        manager = GoalManager()
        verdict = manager._parse_verdict('{"ok": true, "reason": "done"}')
        assert verdict.ok is True

    def test_parse_verdict_with_text(self):
        """Test parsing verdict embedded in text."""
        manager = GoalManager()
        verdict = manager._parse_verdict('Here is my verdict: {"ok": false, "reason": "not done"}')
        assert verdict.ok is False

    def test_parse_verdict_invalid(self):
        """Test parsing invalid verdict defaults to not ok."""
        manager = GoalManager()
        verdict = manager._parse_verdict("this is not json")
        assert verdict.ok is False

    def test_get_stats(self):
        """Test getting statistics."""
        manager = GoalManager()
        manager.set_goal("s1", "test1")
        manager.set_goal("s2", "test2")
        manager._goals["s1"].status = GoalStatus.SATISFIED

        stats = manager.get_stats()
        assert stats["total_goals"] == 2
        assert stats["active"] == 1
        assert stats["satisfied"] == 1


class TestGlobalManager:
    """Tests for global manager."""

    def test_get_goal_manager_singleton(self):
        """Test global manager is singleton."""
        reset_goal_manager()
        m1 = get_goal_manager()
        m2 = get_goal_manager()
        assert m1 is m2

    def test_reset_goal_manager(self):
        """Test resetting global manager."""
        m1 = get_goal_manager()
        reset_goal_manager()
        m2 = get_goal_manager()
        assert m1 is not m2
