"""Tests for the Dream & Distill system."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanocode.dream_distill import (
    DreamManager,
    DistillManager,
    DreamResult,
    DreamStatus,
    WorkflowPattern,
    get_dream_manager,
    get_distill_manager,
    reset_dream_distill,
)


class TestDreamStatus:
    """Tests for DreamStatus enum."""

    def test_status_exists(self):
        """Test that all statuses are defined."""
        assert DreamStatus.PENDING
        assert DreamStatus.RUNNING
        assert DreamStatus.COMPLETED
        assert DreamStatus.FAILED


class TestWorkflowPattern:
    """Tests for WorkflowPattern dataclass."""

    def test_pattern_creation(self):
        """Test creating a pattern."""
        pattern = WorkflowPattern(
            name="test-pattern",
            description="A test pattern",
            steps=["step1", "step2"],
            frequency=5,
            confidence=0.8,
        )
        assert pattern.name == "test-pattern"
        assert pattern.frequency == 5
        assert pattern.confidence == 0.8

    def test_pattern_with_suggested_skill(self):
        """Test pattern with suggested skill."""
        pattern = WorkflowPattern(
            name="test",
            description="test",
            steps=[],
            frequency=3,
            confidence=0.7,
            suggested_skill="my-skill",
        )
        assert pattern.suggested_skill == "my-skill"


class TestDreamResult:
    """Tests for DreamResult dataclass."""

    def test_result_creation(self):
        """Test creating a result."""
        result = DreamResult(status=DreamStatus.COMPLETED)
        assert result.status == DreamStatus.COMPLETED
        assert result.entries_extracted == 0
        assert result.errors == []

    def test_result_with_errors(self):
        """Test result with errors."""
        result = DreamResult(
            status=DreamStatus.FAILED,
            errors=["Something went wrong"],
        )
        assert result.status == DreamStatus.FAILED
        assert len(result.errors) == 1


class TestDreamManager:
    """Tests for DreamManager."""

    def test_init(self, tmp_path):
        """Test initialization."""
        manager = DreamManager(memory_dir=str(tmp_path))
        assert manager.memory_dir == str(tmp_path)

    @pytest.mark.asyncio
    async def test_run_dream_empty(self, tmp_path):
        """Test running dream with empty sessions."""
        manager = DreamManager(memory_dir=str(tmp_path))
        result = await manager.run_dream([])
        assert result.status == DreamStatus.COMPLETED
        assert result.entries_extracted == 0

    @pytest.mark.asyncio
    async def test_run_dream_with_sessions(self, tmp_path):
        """Test running dream with sessions."""
        manager = DreamManager(memory_dir=str(tmp_path))

        sessions = [
            {
                "id": "session-1",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "I decided to use async/await for better performance.",
                        "timestamp": 1234567890.0,
                    }
                ],
            }
        ]

        result = await manager.run_dream(sessions)
        assert result.status == DreamStatus.COMPLETED

    def test_is_knowledge_worthy(self, tmp_path):
        """Test knowledge worthiness check."""
        manager = DreamManager(memory_dir=str(tmp_path))

        assert manager._is_knowledge_worthy("I decided to use this approach")
        assert manager._is_knowledge_worthy("We learned that async is better")
        assert not manager._is_knowledge_worthy("Just some random text here")

    def test_classify_knowledge(self, tmp_path):
        """Test knowledge classification."""
        manager = DreamManager(memory_dir=str(tmp_path))

        assert manager._classify_knowledge("I decided to do this") == "decision"
        assert manager._classify_knowledge("We learned something") == "learning"
        assert manager._classify_knowledge("This pattern works") == "pattern"
        assert manager._classify_knowledge("Some other text") == "note"


class TestDistillManager:
    """Tests for DistillManager."""

    def test_init(self, tmp_path):
        """Test initialization."""
        manager = DistillManager(skills_dir=str(tmp_path))
        assert manager.skills_dir == str(tmp_path)

    @pytest.mark.asyncio
    async def test_run_distill_empty(self, tmp_path):
        """Test running distill with empty sessions."""
        manager = DistillManager(skills_dir=str(tmp_path))
        result = await manager.run_distill([])
        assert result.status == DreamStatus.COMPLETED
        assert result.skills_created == 0

    @pytest.mark.asyncio
    async def test_run_distill_with_patterns(self, tmp_path):
        """Test running distill with detectable patterns."""
        manager = DistillManager(skills_dir=str(tmp_path))

        # Create sessions with repeated tool patterns
        sessions = [
            {
                "id": f"session-{i}",
                "messages": [
                    {
                        "role": "assistant",
                        "content": "Working...",
                        "tool_calls": [
                            {"name": "read"},
                            {"name": "grep"},
                            {"name": "edit"},
                        ],
                    }
                ],
            }
            for i in range(5)
        ]

        result = await manager.run_distill(sessions)
        assert result.status == DreamStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_create_skill(self, tmp_path):
        """Test creating a skill from pattern."""
        manager = DistillManager(skills_dir=str(tmp_path))

        pattern = WorkflowPattern(
            name="test-workflow",
            description="A test workflow",
            steps=["read", "grep", "edit"],
            frequency=5,
            confidence=0.9,
        )

        success = await manager._create_skill(pattern)
        assert success is True

        # Check skill was created
        skill_path = tmp_path / "test-workflow.md"
        assert skill_path.exists()


class TestGlobalInstances:
    """Tests for global instances."""

    def test_get_dream_manager_singleton(self):
        """Test global manager is singleton."""
        reset_dream_distill()
        m1 = get_dream_manager()
        m2 = get_dream_manager()
        assert m1 is m2

    def test_get_distill_manager_singleton(self):
        """Test global manager is singleton."""
        reset_dream_distill()
        m1 = get_distill_manager()
        m2 = get_distill_manager()
        assert m1 is m2

    def test_reset_dream_distill(self):
        """Test resetting global instances."""
        m1 = get_dream_manager()
        d1 = get_distill_manager()
        reset_dream_distill()
        m2 = get_dream_manager()
        d2 = get_distill_manager()
        assert m1 is not m2
        assert d1 is not d2
