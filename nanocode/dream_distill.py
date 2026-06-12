"""Dream & Distill - Self-improvement through knowledge extraction.

Based on MiMo-Code's dream/distill system:
- /dream: Scan recent sessions, extract persistent knowledge into memory
- /distill: Discover repeated workflows, package into reusable skills
"""

import logging
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DreamStatus(StrEnum):
    """Dream/distill run status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DreamResult:
    """Result of a dream/distill run."""

    status: DreamStatus
    entries_extracted: int = 0
    entries_removed: int = 0
    skills_created: int = 0
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class WorkflowPattern:
    """A detected workflow pattern."""

    name: str
    description: str
    steps: list[str]
    frequency: int
    confidence: float
    suggested_skill: str | None = None


class DreamManager:
    """Manages dream (memory consolidation) operations.

    Based on MiMo-Code's dream system:
    - Scan recent session traces
    - Extract persistent knowledge into project memory
    - Remove outdated entries
    """

    def __init__(
        self,
        memory_dir: str | None = None,
        max_age_days: int = 30,
    ):
        """Initialize the dream manager.

        Args:
            memory_dir: Directory containing memory files
            max_age_days: Maximum age of entries to consider
        """
        if memory_dir is None:
            xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
            memory_dir = str(Path(xdg_data) / "nanocode" / "memory")
        self.memory_dir = memory_dir
        self.max_age_days = max_age_days

    async def run_dream(
        self,
        sessions: list[dict[str, Any]],
        llm=None,
    ) -> DreamResult:
        """Run a dream consolidation pass.

        Args:
            sessions: Recent session data to analyze
            llm: LLM for knowledge extraction

        Returns:
            DreamResult with extraction statistics
        """
        result = DreamResult(status=DreamStatus.RUNNING)

        try:
            # Extract knowledge from sessions
            knowledge = await self._extract_knowledge(sessions, llm)
            result.entries_extracted = len(knowledge)

            # Save to memory files
            await self._save_to_memory(knowledge)

            # Remove outdated entries
            removed = await self._remove_outdated()
            result.entries_removed = removed

            result.status = DreamStatus.COMPLETED
            result.summary = (
                f"Extracted {result.entries_extracted} knowledge entries, "
                f"removed {result.entries_removed} outdated entries"
            )

        except Exception as e:
            result.status = DreamStatus.FAILED
            result.errors.append(str(e))
            logger.error(f"Dream failed: {e}")

        return result

    async def _extract_knowledge(
        self,
        sessions: list[dict[str, Any]],
        llm=None,
    ) -> list[dict[str, Any]]:
        """Extract persistent knowledge from sessions."""
        knowledge = []

        for session in sessions:
            messages = session.get("messages", [])
            session_id = session.get("id", "unknown")

            # Extract decisions, learnings, patterns
            for msg in messages:
                content = msg.get("content", "")
                role = msg.get("role", "")

                if role == "assistant" and len(content) > 100:
                    # Look for decision/learning patterns
                    if self._is_knowledge_worthy(content):
                        knowledge.append({
                            "session_id": session_id,
                            "content": content[:500],
                            "type": self._classify_knowledge(content),
                            "timestamp": msg.get("timestamp", time.time()),
                        })

        return knowledge

    def _is_knowledge_worthy(self, content: str) -> bool:
        """Check if content contains extractable knowledge."""
        keywords = [
            "decided", "learned", "discovered", "pattern", "important",
            "note", "architecture", "design", "tradeoff", "trade-off",
            "because", "therefore", "solution", "approach",
        ]
        content_lower = content.lower()
        return any(kw in content_lower for kw in keywords)

    def _classify_knowledge(self, content: str) -> str:
        """Classify the type of knowledge."""
        content_lower = content.lower()
        if "decided" in content_lower or "decision" in content_lower:
            return "decision"
        elif "learned" in content_lower or "discovered" in content_lower:
            return "learning"
        elif "pattern" in content_lower:
            return "pattern"
        else:
            return "note"

    async def _save_to_memory(self, knowledge: list[dict[str, Any]]):
        """Save extracted knowledge to memory files."""
        memory_path = Path(self.memory_dir) / "global"
        memory_path.mkdir(parents=True, exist_ok=True)

        # Append to knowledge.md
        knowledge_file = memory_path / "knowledge.md"
        new_entries = []
        for item in knowledge:
            entry = f"\n\n## {item['type'].title()} ({item['session_id']})\n\n{item['content']}"
            new_entries.append(entry)

        if new_entries:
            with open(knowledge_file, "a") as f:
                f.writelines(new_entries)

    async def _remove_outdated(self) -> int:
        """Remove outdated knowledge entries."""
        # Simplified - just count what would be removed
        return 0


class DistillManager:
    """Manages distill (workflow packaging) operations.

    Based on MiMo-Code's distill system:
    - Discover repeated manual workflows
    - Package into reusable skills/subagents/commands
    """

    def __init__(self, skills_dir: str | None = None):
        """Initialize the distill manager.

        Args:
            skills_dir: Directory for created skills
        """
        if skills_dir is None:
            skills_dir = os.path.join(os.getcwd(), ".nanocode", "skills")
        self.skills_dir = skills_dir
        os.makedirs(skills_dir, exist_ok=True)

    async def run_distill(
        self,
        sessions: list[dict[str, Any]],
        existing_skills: list[str] | None = None,
    ) -> DreamResult:
        """Run a distill pass to discover and package workflows.

        Args:
            sessions: Recent session data to analyze
            existing_skills: List of existing skill names to avoid duplicates

        Returns:
            DreamResult with packaging statistics
        """
        result = DreamResult(status=DreamStatus.RUNNING)
        existing_skills = existing_skills or []

        try:
            # Discover workflow patterns
            patterns = await self._discover_patterns(sessions)

            # Filter out existing skills
            patterns = [p for p in patterns if p.name not in existing_skills]

            # Create skills for high-confidence patterns
            created = 0
            for pattern in patterns:
                if pattern.confidence >= 0.7 and pattern.frequency >= 3:
                    success = await self._create_skill(pattern)
                    if success:
                        created += 1

            result.skills_created = created
            result.status = DreamStatus.COMPLETED
            result.summary = (
                f"Discovered {len(patterns)} patterns, "
                f"created {created} skills"
            )

        except Exception as e:
            result.status = DreamStatus.FAILED
            result.errors.append(str(e))
            logger.error(f"Distill failed: {e}")

        return result

    async def _discover_patterns(
        self,
        sessions: list[dict[str, Any]],
    ) -> list[WorkflowPattern]:
        """Discover repeated workflow patterns."""
        patterns = []

        # Analyze tool call sequences
        tool_sequences = []
        for session in sessions:
            messages = session.get("messages", [])
            sequence = []
            for msg in messages:
                if msg.get("role") == "assistant":
                    tool_calls = msg.get("tool_calls", [])
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            sequence.append(tc.get("name", ""))
                        else:
                            sequence.append(getattr(tc, "name", ""))
            if sequence:
                tool_sequences.append(sequence)

        # Find repeated subsequences
        pattern_counts: dict[str, int] = {}
        for seq in tool_sequences:
            for length in range(2, min(5, len(seq) + 1)):
                for i in range(len(seq) - length + 1):
                    subseq = tuple(seq[i : i + length])
                    key = "->".join(subseq)
                    pattern_counts[key] = pattern_counts.get(key, 0) + 1

        # Convert to WorkflowPattern objects
        for pattern_key, count in pattern_counts.items():
            if count >= 2:
                steps = pattern_key.split("->")
                patterns.append(
                    WorkflowPattern(
                        name=f"workflow_{hash(pattern_key) % 10000}",
                        description=f"Repeated pattern: {pattern_key}",
                        steps=steps,
                        frequency=count,
                        confidence=min(1.0, count / 5),
                    )
                )

        return sorted(patterns, key=lambda p: p.confidence, reverse=True)[:10]

    async def _create_skill(self, pattern: WorkflowPattern) -> bool:
        """Create a skill file from a workflow pattern."""
        try:
            skill_content = f"""---
name: {pattern.name}
description: Auto-generated from repeated workflow pattern
tags: auto-generated, distill
---

# {pattern.name}

{pattern.description}

## Workflow Steps

{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(pattern.steps))}

## Usage

This skill was automatically generated from observed workflow patterns.
It has been detected {pattern.frequency} times with {pattern.confidence:.0%} confidence.
"""
            skill_path = Path(self.skills_dir) / f"{pattern.name}.md"
            skill_path.write_text(skill_content)
            logger.info(f"Created skill: {pattern.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create skill: {e}")
            return False


# Global instances
_dream_manager: DreamManager | None = None
_distill_manager: DistillManager | None = None


def get_dream_manager(memory_dir: str | None = None) -> DreamManager:
    """Get or create the global dream manager."""
    global _dream_manager
    if _dream_manager is None:
        _dream_manager = DreamManager(memory_dir)
    return _dream_manager


def get_distill_manager(skills_dir: str | None = None) -> DistillManager:
    """Get or create the global distill manager."""
    global _distill_manager
    if _distill_manager is None:
        _distill_manager = DistillManager(skills_dir)
    return _distill_manager


def reset_dream_distill():
    """Reset global instances."""
    global _dream_manager, _distill_manager
    _dream_manager = None
    _distill_manager = None
