"""Context Chips System.

Manages what context to include in prompts (env, git, skills, project rules, etc.).
Similar to openwarp's context_chips system but in Python.

Provides modular context selection for building dynamic prompts.
"""

from nanocode.context_chips.chips import (
    ChipType,
    ContextChip,
    create_chip,
)
from nanocode.context_chips.fetcher import (
    ContextFetcher,
    fetch_codebase_context,
    fetch_current_time,
    fetch_env_context,
    fetch_git_context,
    fetch_project_rules,
    fetch_skills_context,
)
from nanocode.context_chips.manager import (
    ContextChipManager,
    get_chip_manager,
)

__all__ = [
    "ContextChip",
    "ChipType",
    "create_chip",
    "ContextFetcher",
    "fetch_env_context",
    "fetch_git_context",
    "fetch_skills_context",
    "fetch_project_rules",
    "fetch_codebase_context",
    "fetch_current_time",
    "ContextChipManager",
    "get_chip_manager",
]
