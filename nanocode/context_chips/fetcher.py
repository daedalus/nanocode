"""Context fetchers for different chip types.

Gathers context from various sources (env, git, skills, etc.).
Similar to openwarp's directory_fetcher.rs and related modules.
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def fetch_env_context(max_vars: int = 20) -> str:
    """Fetch environment variable context.

    Returns formatted environment variables that might be relevant.
    Only includes safe/non-sensitive variables.

    Args:
        max_vars: Maximum number of variables to include

    Returns:
        Formatted string of environment context
    """
    safe_prefixes = (
        "PATH", "HOME", "USER", "SHELL", "LANG", "TERM",
        "PYTHON", "NODE", "JAVA", "GO", "RUST",
        "CONDA", "VIRTUAL_ENV", "VENV",
    )

    env_lines = []
    count = 0

    for key, value in sorted(os.environ.items()):
        if count >= max_vars:
            break

        # Only include safe variables
        is_safe = any(key.startswith(prefix) for prefix in safe_prefixes)
        is_safe = is_safe or key.startswith("nanocode")

        if is_safe:
            # Truncate very long values
            display_value = value[:100] + "..." if len(value) > 100 else value
            env_lines.append(f"  {key}={display_value}")
            count += 1

    if not env_lines:
        return "  (no relevant environment variables)"

    return "\n".join(env_lines)


def fetch_git_context(cwd: str | None = None) -> str:
    """Fetch git repository context.

    Returns formatted git status, branch, and recent commits.

    Args:
        cwd: Working directory (defaults to current)

    Returns:
        Formatted string of git context
    """
    cwd = cwd or os.getcwd()
    lines = []

    try:
        # Get current branch
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            lines.append(f"  Branch: {branch or '(detached HEAD)'}")

        # Get status summary
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            status_lines = result.stdout.strip().split("\n")
            status_lines = [line for line in status_lines if line.strip()]
            if status_lines:
                lines.append(f"  Modified files: {len(status_lines)}")
                for line in status_lines[:5]:
                    lines.append(f"    {line}")
                if len(status_lines) > 5:
                    lines.append(f"    ... and {len(status_lines) - 5} more")
            else:
                lines.append("  Working tree clean")

        # Get recent commits
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            commits = result.stdout.strip()
            if commits:
                lines.append("  Recent commits:")
                for line in commits.split("\n")[:5]:
                    lines.append(f"    {line}")

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"Failed to fetch git context: {e}")
        return "  (not a git repository or git not available)"

    if not lines:
        return "  (not a git repository)"

    return "\n".join(lines)


def fetch_skills_context(skills_manager=None) -> str:
    """Fetch skills context.

    Returns formatted list of available skills.

    Args:
        skills_manager: Skills manager instance (optional)

    Returns:
        Formatted string of skills context
    """
    lines = []

    try:
        # Try to get skills from manager or import
        if skills_manager is None:
            from nanocode.skills import create_skills_manager
            skills_manager = create_skills_manager()

        if skills_manager and hasattr(skills_manager, "skills"):
            skills = skills_manager.skills
            if skills:
                for name, skill in sorted(skills.items()):
                    desc = getattr(skill, "description", "") or ""
                    if len(desc) > 80:
                        desc = desc[:80] + "..."
                    lines.append(f"  - {name}: {desc}")
            else:
                lines.append("  (no skills installed)")
        else:
            lines.append("  (skills system not initialized)")

    except Exception as e:
        logger.debug(f"Failed to fetch skills context: {e}")
        lines.append("  (skills system not available)")

    return "\n".join(lines) if lines else "  (none)"


def fetch_project_rules(cwd: str | Path | None = None) -> str:
    """Fetch project rules from AGENTS.md, .cursorrules, etc.

    Args:
        cwd: Working directory (defaults to current)

    Returns:
        Formatted string of project rules
    """
    cwd = Path(cwd) if cwd else Path(os.getcwd())
    lines = []

    rule_files = [
        "AGENTS.md",
        ".cursorrules",
        ".github/copilot-instructions.md",
        "CLAUDE.md",
        "CODEBUDDY.md",
    ]

    for rule_file in rule_files:
        file_path = cwd / rule_file
        if file_path.exists():
            try:
                content = file_path.read_text()[:500]  # Limit size
                lines.append(f"\n### From {rule_file}:\n{content}")
                if len(content) >= 500:
                    lines.append("...")
            except Exception as e:
                logger.debug(f"Failed to read {rule_file}: {e}")

    if not lines:
        return "  (no project rules found)"

    return "\n".join(lines)


def fetch_codebase_context(cwd: str | Path | None = None, max_files: int = 10) -> str:
    """Fetch codebase structure context.

    Returns a summary of the codebase structure.

    Args:
        cwd: Working directory (defaults to current)
        max_files: Maximum number of files to list

    Returns:
        Formatted string of codebase context
    """
    cwd = Path(cwd) if cwd else Path(os.getcwd())
    lines = []

    try:
        # List important files/dirs
        important_patterns = [
            "*.py", "*.js", "*.ts", "*.go", "*.rs",
            "package.json", "pyproject.toml", "Cargo.toml",
            "README*", "Makefile", "Dockerfile",
        ]

        found_files = set()
        for pattern in important_patterns:
            if "*" in pattern:
                for f in cwd.glob(pattern):
                    if f.is_file() and f.name not in found_files:
                        found_files.add(f.name)
                        lines.append(f"  {f.name}")
                        if len(found_files) >= max_files:
                            break
            else:
                f = cwd / pattern
                if f.exists() and pattern not in found_files:
                    found_files.add(pattern)
                    lines.append(f"  {pattern}")

        # Check for common directories
        for d in ["src", "lib", "app", "tests", "docs"]:
            if (cwd / d).is_dir():
                lines.append(f"  [{d}/]")

    except Exception as e:
        logger.debug(f"Failed to fetch codebase context: {e}")
        return "  (error reading codebase structure)"

    if not lines:
        return "  (empty or unknown codebase structure)"

    return "\n".join(lines[:max_files])


def fetch_current_time() -> str:
    """Fetch current time context.

    Returns formatted current date/time.
    """
    from datetime import datetime

    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")


class ContextFetcher:
    """Main context fetcher that coordinates all chip types.

    Similar to openwarp's current_prompt.rs but in Python.
    """

    def __init__(self, cwd: str | None = None):
        """Initialize the context fetcher.

        Args:
            cwd: Working directory
        """
        self.cwd = cwd or os.getcwd()

    def fetch_all(self, enabled_chips: list[str] | None = None) -> dict[str, str]:
        """Fetch context from all enabled chips.

        Args:
            enabled_chips: List of chip types to fetch (defaults to all)

        Returns:
            Dictionary mapping chip type to context string
        """
        result = {}

        chip_fetchers = {
            "env": lambda: fetch_env_context(),
            "git": lambda: fetch_git_context(self.cwd),
            "skills": lambda: fetch_skills_context(),
            "project_rules": lambda: fetch_project_rules(self.cwd),
            "codebase": lambda: fetch_codebase_context(self.cwd),
            "current_time": lambda: fetch_current_time(),
        }

        # Default: all chips enabled
        if enabled_chips is None:
            enabled_chips = list(chip_fetchers.keys())

        for chip_type in enabled_chips:
            if chip_type in chip_fetchers:
                try:
                    result[chip_type] = chip_fetchers[chip_type]()
                except Exception as e:
                    logger.warning(f"Failed to fetch {chip_type} context: {e}")
                    result[chip_type] = f"(error fetching {chip_type} context)"

        return result

    def fetch_by_type(self, chip_type: str) -> str:
        """Fetch context for a specific chip type.

        Args:
            chip_type: Type of chip to fetch

        Returns:
            Context string
        """
        fetchers = {
            "env": fetch_env_context,
            "git": lambda: fetch_git_context(self.cwd),
            "skills": fetch_skills_context,
            "project_rules": lambda: fetch_project_rules(self.cwd),
            "codebase": lambda: fetch_codebase_context(self.cwd),
            "current_time": fetch_current_time,
        }

        if chip_type in fetchers:
            return fetchers[chip_type]()

        return f"(unknown chip type: {chip_type})"
