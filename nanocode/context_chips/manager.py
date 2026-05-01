"""Context Chip Manager.

Orchestrates context chips and integrates with the prompt system.
Similar to openwarp's current_prompt.rs but in Python.
"""

import logging

from nanocode.context_chips.chips import ChipType, ContextChip, create_chip
from nanocode.context_chips.fetcher import ContextFetcher

logger = logging.getLogger(__name__)


class ContextChipManager:
    """Manages context chips and builds context for prompts.

    Similar to openwarp's context chip system.
    Allows enabling/disabling chips and fetching context dynamically.
    """

    def __init__(self, cwd: str | None = None):
        """Initialize the context chip manager.

        Args:
            cwd: Working directory
        """
        self.cwd = cwd
        self.fetcher = ContextFetcher(cwd)
        self.chips: dict[str, ContextChip] = {}
        self._init_default_chips()

    def _init_default_chips(self):
        """Initialize default chips."""
        self.chips = {
            "env": create_chip(
                ChipType.ENV,
                name="Environment Variables",
                priority=10,
                enabled=True,
            ),
            "git": create_chip(
                ChipType.GIT,
                name="Git Repository",
                priority=20,
                enabled=True,
            ),
            "skills": create_chip(
                ChipType.SKILLS,
                name="Skills",
                priority=30,
                enabled=True,
            ),
            "project_rules": create_chip(
                ChipType.PROJECT_RULES,
                name="Project Rules",
                priority=40,
                enabled=True,
            ),
            "codebase": create_chip(
                ChipType.CODEBASE,
                name="Codebase Structure",
                priority=50,
                enabled=False,  # Disabled by default (can be expensive)
            ),
            "current_time": create_chip(
                ChipType.CURRENT_TIME,
                name="Current Time",
                priority=5,
                enabled=True,
            ),
        }

    def enable_chip(self, chip_type: str):
        """Enable a context chip.

        Args:
            chip_type: Type of chip to enable
        """
        if chip_type in self.chips:
            self.chips[chip_type].enabled = True
            logger.debug(f"Enabled chip: {chip_type}")

    def disable_chip(self, chip_type: str):
        """Disable a context chip.

        Args:
            chip_type: Type of chip to disable
        """
        if chip_type in self.chips:
            self.chips[chip_type].enabled = False
            logger.debug(f"Disabled chip: {chip_type}")

    def is_enabled(self, chip_type: str) -> bool:
        """Check if a chip is enabled.

        Args:
            chip_type: Type of chip

        Returns:
            True if enabled
        """
        if chip_type in self.chips:
            return self.chips[chip_type].enabled
        # For unknown chip types, return False
        return False

    def set_enabled_chips(self, enabled: list[str]):
        """Set which chips are enabled (disables others).

        Args:
            enabled: List of chip types to enable
        """
        for chip_type in self.chips:
            self.chips[chip_type].enabled = chip_type in enabled

    def get_enabled_chips(self) -> list[str]:
        """Get list of enabled chip types.

        Returns:
            List of enabled chip type strings
        """
        return [ct for ct, chip in self.chips.items() if chip.enabled]

    def fetch_context(self, chip_type: str | None = None) -> dict[str, str]:
        """Fetch context from chips.

        Args:
            chip_type: Specific chip to fetch (None = all enabled)

        Returns:
            Dictionary mapping chip type to context string
        """
        if chip_type:
            # Fetch single chip
            context = self.fetcher.fetch_by_type(chip_type)
            return {chip_type: context}

        # Fetch all enabled chips (sorted by priority)
        enabled = [(ct, chip) for ct, chip in self.chips.items() if chip.enabled]
        enabled.sort(key=lambda x: x[1].priority)

        chip_types = [ct for ct, _ in enabled]
        return self.fetcher.fetch_all(chip_types)

    def build_context_section(self) -> str:
        """Build the context section for prompts.

        Returns:
            Formatted context string for inclusion in prompts
        """
        lines = ["\n## Additional Context"]

        contexts = self.fetch_context()

        # Order matters - sort by chip priority
        enabled = [(ct, self.chips[ct]) for ct in contexts if ct in self.chips]
        enabled.sort(key=lambda x: x[1].priority)

        for chip_type, chip in enabled:
            context = contexts.get(chip_type, "")
            if context:
                lines.append(f"\n### {chip.name}")
                lines.append(context)

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Export configuration to dictionary.

        Returns:
            Dictionary with chip configurations
        """
        return {ct: chip.to_dict() for ct, chip in self.chips.items()}

    def from_dict(self, data: dict):
        """Import configuration from dictionary.

        Args:
            data: Dictionary with chip configurations
        """
        for chip_type, chip_data in data.items():
            if chip_type in self.chips:
                chip = self.chips[chip_type]
                chip.enabled = chip_data.get("enabled", chip.enabled)
                chip.priority = chip_data.get("priority", chip.priority)


def get_chip_manager() -> ContextChipManager:
    """Get a shared context chip manager instance.

    Returns:
        ContextChipManager instance
    """
    return ContextChipManager()
