"""Skills system - custom commands defined in .agent/skills/."""

import os
import re
import asyncio
from pathlib import Path
from typing import Any, Callable, Optional
from dataclasses import dataclass
import frontmatter


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

    DEFAULT_SKILL_DIRS = [".agent/skills", ".agent/commands"]
    SKILL_FILE_NAME = "skill.md"

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or os.getcwd()
        self.skills: dict[str, Skill] = {}
        self._handlers: dict[str, Callable] = {}

    def discover_skills(self) -> list[Skill]:
        """Discover skills in the configured directories."""
        discovered = []
        
        for skill_dir in self.DEFAULT_SKILL_DIRS:
            full_path = os.path.join(self.base_dir, skill_dir)
            if not os.path.isdir(full_path):
                continue
            
            for root, dirs, files in os.walk(full_path):
                if self.SKILL_FILE_NAME in files:
                    skill_path = os.path.join(root, self.SKILL_FILE_NAME)
                    try:
                        skill = self._parse_skill_file(skill_path)
                        if skill:
                            discovered.append(skill)
                    except Exception as e:
                        pass
        
        return discovered

    def _parse_skill_file(self, path: str) -> Optional[Skill]:
        """Parse a skill.md file."""
        try:
            with open(path, "r") as f:
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
                description = body[:100] if body else ""
            
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
            tools.append({
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
            })
        
        return tools


def create_skills_manager(base_dir: str = None) -> SkillsManager:
    """Create and initialize a skills manager."""
    manager = SkillsManager(base_dir)
    manager.load_skills()
    return manager
