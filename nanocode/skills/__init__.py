"""Skills system - custom commands defined in .nanocode/skills/."""

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

import frontmatter

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A skill definition."""

    name: str
    description: str
    content: str
    location: str


class SkillError(Exception):
    """Base exception for skill errors."""

    pass


class SkillNotFoundError(SkillError):
    """Raised when a skill is not found."""

    pass


class SkillInvalidError(SkillError):
    """Raised when a skill is invalid."""

    pass


class SkillsManager:
    """Manages custom skills/commands."""

    DEFAULT_SKILL_DIRS = [
        ".nanocode/skills",
        ".nanocode/commands",
        ".claude/skills",
        ".opencode/skills",
        ".codex/skills",
        ".gemini/skills",
        ".agents/skills",
        os.path.expanduser("~/.nanocode/skills"),
        os.path.expanduser("~/.claude/skills"),
        os.path.expanduser("~/.config/opencode/skills"),
        os.path.expanduser("~/.codex/skills"),
        os.path.expanduser("~/.gemini/skills"),
        os.path.expanduser("~/.agents/skills"),
    ]
    SKILL_FILE_NAME = "SKILL.md"

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or os.getcwd()
        self.skills: dict[str, Skill] = {}
        self._handlers: dict[str, Callable] = {}

    def discover_skills(self) -> list[Skill]:
        """Discover skills in the configured directories."""
        discovered = []

        default_dirs = [
            ".nanocode/skills",
            ".nanocode/commands",
            ".claude/skills",
            ".opencode/skills",
            ".codex/skills",
            ".gemini/skills",
            ".agents/skills",
        ]
        global_dirs = [
            os.path.expanduser("~/.nanocode/skills"),
            os.path.expanduser("~/.claude/skills"),
            os.path.expanduser("~/.config/opencode/skills"),
            os.path.expanduser("~/.codex/skills"),
            os.path.expanduser("~/.gemini/skills"),
            os.path.expanduser("~/.agents/skills"),
        ]

        search_paths = []

        for d in default_dirs:
            search_paths.append(os.path.join(self.base_dir, d))

        if self.base_dir == os.getcwd():
            for d in global_dirs:
                if os.path.isabs(d):
                    search_paths.append(d)

        to_scan = [p for p in search_paths if os.path.isdir(p)]

        for full_path in to_scan:
            for root, dirs, files in os.walk(full_path):
                if self.SKILL_FILE_NAME in files:
                    skill_path = os.path.join(root, self.SKILL_FILE_NAME)
                    try:
                        skill = self._parse_skill_file(skill_path)
                        if skill:
                            discovered.append(skill)
                    except Exception:
                        pass

        return discovered

    def _parse_skill_file(self, path: str) -> Skill | None:
        """Parse a skill.md file."""
        try:
            with open(path) as f:
                content = f.read()

            try:
                metadata, body = frontmatter.parse(content)
            except Exception:
                return None

            name = metadata.get("name", "")
            description = metadata.get("description", "")

            if not name:
                name = os.path.basename(os.path.dirname(path))
            if not description:
                description = body if body else ""

            return Skill(
                name=name,
                description=description,
                content=body,
                location=path,
            )
        except Exception:
            return None

    def load_skills(self) -> int:
        """Load all discovered skills."""
        self.skills.clear()

        discovered = self.discover_skills()
        for skill in discovered:
            self.skills[skill.name] = skill
            logger.info(f"Skill available: {skill.name} ({skill.location})")

        return len(self.skills)

    def get_skill(self, name: str) -> Skill:
        """Get a skill by name."""
        if name not in self.skills:
            raise SkillNotFoundError(f"Skill '{name}' not found")
        return self.skills[name]

    def list_skills(self) -> list[dict[str, str]]:
        """List all available skills."""
        return [
            {"name": s.name, "description": s.description, "location": s.location}
            for s in self.skills.values()
        ]

    def register_handler(self, name: str, handler: Callable):
        """Register a handler function for a skill."""
        self._handlers[name] = handler

    async def execute_skill(
        self,
        name: str,
        args: dict[str, Any] = None,
        context: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """Execute a skill."""
        skill = self.get_skill(name)
        args = args or {}
        context = context or {}

        if name in self._handlers:
            handler = self._handlers[name]
            if asyncio.iscoroutinefunction(handler):
                return await handler(skill, args, context)
            return handler(skill, args, context)

        return {
            "success": True,
            "skill": skill.name,
            "description": skill.description,
            "content": skill.content,
        }

    def create_tools(self, agent) -> list[dict]:
        """Create tool definitions from skills."""
        tools = []

        for name, skill in self.skills.items():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"skill_{name.replace('-', '_')}",
                        "description": skill.description,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "input": {
                                    "type": "string",
                                    "description": "Input to pass to the skill",
                                }
                            },
                            "required": ["input"],
                        },
                    },
                }
            )

        return tools


def create_skills_manager(base_dir: str = None) -> SkillsManager:
    """Create and initialize a skills manager."""
    manager = SkillsManager(base_dir)
    manager.load_skills()
    return manager


def install_skills(base_dir: str = None, skill_name: str = None):
    """Install built-in skills from package to .nanocode/skills/.

    Args:
        base_dir: Target directory for skills installation. Defaults to current working directory.
        skill_name: Specific skill to install. If None, installs all skills.
    """
    import os
    import shutil

    if base_dir is None:
        base_dir = os.getcwd()

    package_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    skills_src = os.path.join(package_dir, "skills")
    skills_dest = os.path.join(base_dir, ".nanocode", "skills")

    if not os.path.isdir(skills_src):
        print(f"No skills directory found at {skills_src}")
        return False

    os.makedirs(skills_dest, exist_ok=True)

    skills_to_install = [skill_name] if skill_name else []

    if not skill_name:
        try:
            skills_to_install = os.listdir(skills_src)
        except OSError:
            skills_to_install = []

    installed = []
    for item in skills_to_install:
        src_path = os.path.join(skills_src, item)
        if not os.path.isdir(src_path):
            continue

        skill_file = os.path.join(src_path, "SKILL.md")
        if not os.path.isfile(skill_file):
            continue

        dest_path = os.path.join(skills_dest, item)
        if os.path.isdir(dest_path):
            print(f"Updating existing skill: {item}")
            shutil.rmtree(dest_path)
        else:
            print(f"Installing skill: {item}")

        os.makedirs(dest_path)
        shutil.copy2(skill_file, os.path.join(dest_path, "skill.md"))
        installed.append(item)

    if installed:
        print(f"\nInstalled {len(installed)} skill(s): {', '.join(installed)}")
    else:
        print("No skills found to install")

    return True
