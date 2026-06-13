"""Tests for Phase 3 features: plan follow-up."""

import pytest
from unittest.mock import AsyncMock, patch

from nanocode.plan_followup import (
    HANDOVER_PROMPT,
    PlanFollowupResult,
    TodoItem,
    build_implementation_prompt,
    format_todos,
    generate_handover,
    handle_plan_followup,
)


class TestFormatTodos:
    """Tests for todo formatting."""

    def test_format_todos_empty(self):
        assert format_todos([]) == ""

    def test_format_todos_single_pending(self):
        todos = [TodoItem(content="Implement feature", status="pending")]
        result = format_todos(todos)
        assert "- [ ] Implement feature" in result

    def test_format_todos_completed(self):
        todos = [TodoItem(content="Done task", status="completed")]
        result = format_todos(todos)
        assert "- [x] Done task" in result

    def test_format_todos_in_progress(self):
        todos = [TodoItem(content="Working on it", status="in_progress")]
        result = format_todos(todos)
        assert "- [~] Working on it" in result

    def test_format_todos_cancelled(self):
        todos = [TodoItem(content="Cancelled task", status="cancelled")]
        result = format_todos(todos)
        assert "- [-] Cancelled task" in result

    def test_format_todos_mixed(self):
        todos = [
            TodoItem(content="Task 1", status="completed"),
            TodoItem(content="Task 2", status="pending"),
            TodoItem(content="Task 3", status="in_progress"),
        ]
        result = format_todos(todos)
        assert "- [x] Task 1" in result
        assert "- [ ] Task 2" in result
        assert "- [~] Task 3" in result

    def test_format_todos_multiple(self):
        todos = [
            TodoItem(content="First", status="pending"),
            TodoItem(content="Second", status="completed"),
        ]
        result = format_todos(todos)
        lines = result.strip().split("\n")
        assert len(lines) == 2


class TestBuildImplementationPrompt:
    """Tests for implementation prompt building."""

    def test_build_prompt_plan_only(self):
        result = build_implementation_prompt("Build feature X")
        assert "Build feature X" in result
        assert "Implement the following plan" in result

    def test_build_prompt_with_handover(self):
        result = build_implementation_prompt(
            "Build feature X",
            handover="## Discoveries\n\nFound important pattern",
        )
        assert "Build feature X" in result
        assert "Handover from Planning Session" in result
        assert "Found important pattern" in result

    def test_build_prompt_with_todos(self):
        todos = [TodoItem(content="Step 1", status="pending")]
        result = build_implementation_prompt("Build feature X", todo_items=todos)
        assert "Build feature X" in result
        assert "Todo List" in result
        assert "Step 1" in result

    def test_build_prompt_all_parts(self):
        todos = [TodoItem(content="Step 1", status="pending")]
        result = build_implementation_prompt(
            "Build feature X",
            handover="Handover content",
            todo_items=todos,
        )
        assert "Build feature X" in result
        assert "Handover content" in result
        assert "Step 1" in result

    def test_build_prompt_no_empty_sections(self):
        result = build_implementation_prompt("Plan", handover="", todo_items=None)
        assert "Handover" not in result
        assert "Todo" not in result


class TestHandoverPrompt:
    """Tests for handover prompt content."""

    def test_handover_prompt_has_template(self):
        assert "Discoveries" in HANDOVER_PROMPT
        assert "Relevant Files" in HANDOVER_PROMPT
        assert "Implementation Notes" in HANDOVER_PROMPT

    def test_handover_prompt_instructions(self):
        assert "do NOT repeat" in HANDOVER_PROMPT
        assert "concise" in HANDOVER_PROMPT.lower()


class TestGenerateHandover:
    """Tests for handover generation."""

    @pytest.mark.asyncio
    async def test_generate_handover_returns_string(self):
        messages = [
            {"role": "user", "content": "Implement feature X"},
            {"role": "assistant", "content": "I'll explore the codebase first"},
        ]

        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm_instance = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = "## Discoveries\n\nFound pattern Y"
            mock_llm_instance.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = (mock_llm_instance, {})

            result = await generate_handover(messages)

            assert isinstance(result, str)
            assert "Discoveries" in result

    @pytest.mark.asyncio
    async def test_generate_handover_with_todos(self):
        messages = [{"role": "user", "content": "Plan"}]
        todos = [TodoItem(content="Step 1", status="pending")]

        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm_instance = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = "Handover text"
            mock_llm_instance.chat = AsyncMock(return_value=mock_response)
            mock_llm.return_value = (mock_llm_instance, {})

            result = await generate_handover(messages, todo_items=todos)

            assert "Handover text" in result
            assert "Todo List" in result
            assert "Step 1" in result

    @pytest.mark.asyncio
    async def test_generate_handover_returns_empty_on_error(self):
        messages = [{"role": "user", "content": "Plan"}]

        with patch("nanocode.llm.create_llm_from_model_id") as mock_llm:
            mock_llm.side_effect = Exception("LLM unavailable")

            result = await generate_handover(messages)

            assert result == ""


class TestHandlePlanFollowup:
    """Tests for plan follow-up handler."""

    @pytest.mark.asyncio
    async def test_handle_returns_result(self):
        messages = [{"role": "user", "content": "Plan"}]

        with patch("nanocode.plan_followup.generate_handover") as mock_handover:
            mock_handover.return_value = "Handover content"

            result = await handle_plan_followup("Build feature X", messages)

            assert isinstance(result, PlanFollowupResult)
            assert result.action == "continue"
            assert "Build feature X" in result.prompt
            assert result.handover == "Handover content"

    @pytest.mark.asyncio
    async def test_handle_includes_todos(self):
        messages = [{"role": "user", "content": "Plan"}]
        todos = [TodoItem(content="Step 1", status="pending")]

        with patch("nanocode.plan_followup.generate_handover") as mock_handover:
            mock_handover.return_value = "Handover"

            result = await handle_plan_followup(
                "Plan", messages, todo_items=todos
            )

            assert "Step 1" in result.prompt

    @pytest.mark.asyncio
    async def test_handle_with_model_info(self):
        messages = [{"role": "user", "content": "Plan"}]
        model_info = {"provider": "openai", "model": "gpt-4o"}

        with patch("nanocode.plan_followup.generate_handover") as mock_handover:
            mock_handover.return_value = ""

            result = await handle_plan_followup(
                "Plan", messages, model_info=model_info
            )

            assert result.action == "continue"


class TestPlanFollowupResult:
    """Tests for PlanFollowupResult dataclass."""

    def test_result_fields(self):
        result = PlanFollowupResult(
            action="continue",
            prompt="Implement plan",
            handover="Handover text",
        )
        assert result.action == "continue"
        assert result.prompt == "Implement plan"
        assert result.handover == "Handover text"

    def test_result_defaults(self):
        result = PlanFollowupResult(action="cancelled")
        assert result.prompt == ""
        assert result.handover == ""
