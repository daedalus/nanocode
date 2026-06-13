"""Tests for Phase 4 features: max mode, goals, scheduler, config injector."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanocode.llm.max_mode import (
    CompletionResult,
    MaxModeConfig,
    MaxModeResult,
    judge_responses,
    max_mode_completion,
    run_single_completion,
)
from nanocode.goal_manager import (
    Goal,
    GoalEvaluation,
    GoalManager,
    get_goal_manager,
)
from nanocode.scheduler import Scheduler, ScheduledTask, get_scheduler
from nanocode.config_injector import (
    InjectionResult,
    build_modes_section,
    build_rules_section,
    inject_config,
    migrate_modes,
    migrate_permissions,
    migrate_rules,
)


class TestMaxMode:
    """Tests for Max Mode."""

    def test_config_defaults(self):
        config = MaxModeConfig()
        assert config.enabled is False
        assert config.n == 3
        assert config.timeout == 60.0

    def test_config_custom(self):
        config = MaxModeConfig(enabled=True, n=5, timeout=30.0)
        assert config.enabled is True
        assert config.n == 5
        assert config.timeout == 30.0

    def test_completion_result_fields(self):
        result = CompletionResult(content="Hello", model="gpt-4o", tokens=10, latency=0.5)
        assert result.content == "Hello"
        assert result.model == "gpt-4o"
        assert result.error is None

    def test_completion_result_error(self):
        result = CompletionResult(content="", model="gpt-4o", error="timeout")
        assert result.error == "timeout"

    def test_max_mode_result_fields(self):
        best = CompletionResult(content="Best answer", model="gpt-4o")
        result = MaxModeResult(best=best, judge_reasoning="More complete")
        assert result.best.content == "Best answer"
        assert result.judge_reasoning == "More complete"

    @pytest.mark.asyncio
    async def test_run_single_completion_success(self):
        mock_llm = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = "Test response"
        mock_llm.chat = AsyncMock(return_value=mock_response)
        mock_llm.model = "test-model"

        messages = [{"role": "user", "content": "Hello"}]
        result = await run_single_completion(mock_llm, messages)

        assert result.content == "Test response"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_run_single_completion_error(self):
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("API error"))
        mock_llm.model = "test-model"

        messages = [{"role": "user", "content": "Hello"}]
        result = await run_single_completion(mock_llm, messages)

        assert result.error == "API error"

    @pytest.mark.asyncio
    async def test_judge_responses_selects_best(self):
        responses = [
            CompletionResult(content="Short answer", model="m1"),
            CompletionResult(content="Complete and detailed answer", model="m2"),
        ]

        mock_judge = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = '{"best_index": 1, "reasoning": "More detailed"}'
        mock_judge.chat = AsyncMock(return_value=mock_response)

        index, reasoning = await judge_responses(mock_judge, responses)

        assert index == 1
        assert "detailed" in reasoning.lower()

    @pytest.mark.asyncio
    async def test_judge_responses_fallback_on_error(self):
        responses = [
            CompletionResult(content="", model="m1", error="timeout"),
            CompletionResult(content="Valid answer", model="m2"),
        ]

        mock_judge = AsyncMock()
        mock_judge.chat = AsyncMock(side_effect=Exception("Judge failed"))

        index, reasoning = await judge_responses(mock_judge, responses)

        assert index == 0
        assert len(reasoning) > 0

    @pytest.mark.asyncio
    async def test_max_mode_disabled_returns_single(self):
        mock_llm = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = "Single response"
        mock_llm.chat = AsyncMock(return_value=mock_response)
        mock_llm.model = "test-model"

        messages = [{"role": "user", "content": "Hello"}]
        config = MaxModeConfig(enabled=False)

        result = await max_mode_completion(mock_llm, messages, config)

        assert result.best.content == "Single response"
        assert len(result.all_results) == 1


class TestGoals:
    """Tests for Goal Manager."""

    def test_goal_creation(self):
        goal = Goal(text="Complete the feature", created_at=1.0)
        assert goal.text == "Complete the feature"
        assert goal.created_at == 1.0

    def test_goal_manager_set_goal(self):
        manager = GoalManager()
        goal = manager.set_goal("Implement tests")

        assert manager.has_goal()
        assert manager.get_goal().text == "Implement tests"

    def test_goal_manager_clear_goal(self):
        manager = GoalManager()
        manager.set_goal("Task")
        manager.clear_goal()

        assert not manager.has_goal()
        assert manager.get_goal() is None

    def test_goal_manager_history(self):
        manager = GoalManager()
        manager.set_goal("Task")

        evaluation = GoalEvaluation(
            achieved=True,
            reasoning="Done",
            goal=manager.get_goal(),
        )
        manager._history.append(evaluation)

        assert len(manager.get_history()) == 1
        assert manager.should_stop()

    def test_goal_manager_should_stop_false(self):
        manager = GoalManager()
        assert not manager.should_stop()

    @pytest.mark.asyncio
    async def test_goal_evaluate_achieved(self):
        manager = GoalManager()
        manager.set_goal("Write tests")

        mock_llm = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = '{"achieved": true, "reasoning": "All tests written"}'
        mock_llm.chat = AsyncMock(return_value=mock_response)

        conversation = [{"role": "user", "content": "Write tests"}, {"role": "assistant", "content": "Tests written"}]
        result = await manager.evaluate(conversation, mock_llm)

        assert result.achieved is True
        assert "tests" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_goal_evaluate_not_achieved(self):
        manager = GoalManager()
        manager.set_goal("Deploy to production")

        mock_llm = AsyncMock()
        mock_response = AsyncMock()
        mock_response.content = '{"achieved": false, "reasoning": "Not yet deployed"}'
        mock_llm.chat = AsyncMock(return_value=mock_response)

        conversation = [{"role": "user", "content": "Deploy"}]
        result = await manager.evaluate(conversation, mock_llm)

        assert result.achieved is False

    def test_get_goal_manager_singleton(self):
        manager1 = get_goal_manager()
        manager2 = get_goal_manager()
        assert manager1 is manager2


class TestScheduler:
    """Tests for Scheduler."""

    def test_register_task(self):
        scheduler = Scheduler()

        async def callback():
            pass

        task = scheduler.register("test", 60.0, callback)
        assert task.id == "test"
        assert task.interval == 60.0
        assert task.scope == "instance"

    def test_unregister_task(self):
        scheduler = Scheduler()

        async def callback():
            pass

        scheduler.register("test", 60.0, callback)
        assert scheduler.unregister("test")
        assert scheduler.get_task("test") is None

    def test_list_tasks(self):
        scheduler = Scheduler()

        async def callback():
            pass

        scheduler.register("task1", 60.0, callback)
        scheduler.register("task2", 120.0, callback, scope="global")

        all_tasks = scheduler.list_tasks()
        assert len(all_tasks) == 2

        instance_tasks = scheduler.list_tasks(scope="instance")
        assert len(instance_tasks) == 1

    def test_clear_tasks(self):
        scheduler = Scheduler()

        async def callback():
            pass

        scheduler.register("task1", 60.0, callback)
        scheduler.register("task2", 120.0, callback)
        scheduler.clear()

        assert len(scheduler.list_tasks()) == 0

    @pytest.mark.asyncio
    async def test_run_now(self):
        scheduler = Scheduler()
        called = False

        async def callback():
            nonlocal called
            called = True

        scheduler.register("test", 60.0, callback)
        result = await scheduler.run_now("test")

        assert result is True
        assert called is True

    @pytest.mark.asyncio
    async def test_start_stop(self):
        scheduler = Scheduler()
        await scheduler.start()
        assert scheduler._running is True

        await scheduler.stop()
        assert scheduler._running is False

    def test_get_scheduler_singleton(self):
        scheduler1 = get_scheduler()
        scheduler2 = get_scheduler()
        assert scheduler1 is scheduler2


class TestConfigInjector:
    """Tests for Config Injector."""

    def test_migrate_rules_empty_dir(self, tmp_path):
        rules, warnings = migrate_rules(tmp_path)
        assert rules == []
        assert warnings == []

    def test_migrate_rules_with_files(self, tmp_path):
        rules_dir = tmp_path / ".nanocode" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "rule1.md").write_text("# Rule 1\n\nThis is rule 1")
        (rules_dir / "rule2.md").write_text("# Rule 2\n\nThis is rule 2")

        rules, warnings = migrate_rules(tmp_path, include_global=False)

        assert len(rules) == 2
        assert any("Rule 1" in r for r in rules)

    def test_migrate_modes_empty_dir(self, tmp_path):
        agents, warnings = migrate_modes(tmp_path)
        assert agents == {}
        assert warnings == []

    def test_migrate_modes_with_files(self, tmp_path):
        modes_dir = tmp_path / ".nanocode" / "modes"
        modes_dir.mkdir(parents=True)
        (modes_dir / "debug.md").write_text("# Debug Mode\n\nDebug instructions")

        agents, warnings = migrate_modes(tmp_path, include_global=False)

        assert "debug" in agents
        assert "Debug instructions" in agents["debug"]["prompt"]

    def test_migrate_permissions_yaml(self, tmp_path):
        perms_dir = tmp_path / ".nanocode" / "permissions"
        perms_dir.mkdir(parents=True)
        (perms_dir / "read.yaml").write_text("read:\n  allow:\n    - '*.py'")

        permissions, warnings = migrate_permissions(tmp_path, include_global=False)

        assert "read" in permissions

    def test_inject_config(self, tmp_path):
        rules_dir = tmp_path / ".nanocode" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "rule.md").write_text("Test rule")

        result = inject_config(tmp_path, include_global=False)

        assert len(result.rules) == 1
        assert "Test rule" in result.rules[0]

    def test_build_rules_section(self):
        rules = ["Rule 1 content", "Rule 2 content"]
        result = build_rules_section(rules)

        assert "Project Rules" in result
        assert "Rule 1 content" in result
        assert "Rule 2 content" in result

    def test_build_rules_section_empty(self):
        result = build_rules_section([])
        assert result == ""

    def test_build_modes_section(self):
        agents = {
            "debug": {"description": "Debug mode"},
            "review": {"description": "Review mode"},
        }
        result = build_modes_section(agents)

        assert "Custom Modes" in result
        assert "debug" in result
        assert "review" in result

    def test_build_modes_section_empty(self):
        result = build_modes_section({})
        assert result == ""
