"""Context chip definitions and types.

Defines the chip types and chip data structure for the context system.
Similar to openwarp's context_chip.rs.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ChipType(Enum):
    """Types of context chips available."""

    ENV = "env"
    GIT = "git"
    SKILLS = "skills"
    PROJECT_RULES = "project_rules"
    CODEBASE = "codebase"
    CURRENT_TIME = "current_time"
    DIRECTORY = "directory"
    CUSTOM = "custom"


@dataclass
class ContextChip:
    """A context chip that provides specific context to the prompt.

    Attributes:
        chip_type: The type of chip
        name: Human-readable name
        enabled: Whether this chip is enabled
        priority: Priority order (lower = earlier in prompt)
        content: The actual context content (lazily loaded)
        metadata: Additional metadata about the chip
    """

    chip_type: ChipType
    name: str
    enabled: bool = True
    priority: int = 100
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert chip to dictionary."""
        return {
            "type": self.chip_type.value,
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextChip":
        """Create chip from dictionary."""
        chip_type = ChipType(data.get("type", "custom"))
        return cls(
            chip_type=chip_type,
            name=data.get("name", chip_type.value),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 100),
            content=data.get("content"),
            metadata=data.get("metadata", {}),
        )


def create_chip(
    chip_type: ChipType | str,
    name: str = "",
    enabled: bool = True,
    priority: int = 100,
    content: str | None = None,
    **metadata,
) -> ContextChip:
    """Create a context chip.

    Args:
        chip_type: Type of chip (ChipType enum or string)
        name: Human-readable name (defaults to chip_type value)
        enabled: Whether the chip is enabled
        priority: Priority order
        content: Optional pre-loaded content
        **metadata: Additional metadata

    Returns:
        ContextChip instance
    """
    if isinstance(chip_type, str):
        try:
            chip_type = ChipType(chip_type)
        except ValueError:
            chip_type = ChipType.CUSTOM

    return ContextChip(
        chip_type=chip_type,
        name=name or chip_type.value,
        enabled=enabled,
        priority=priority,
        content=content,
        metadata=metadata,
    )
