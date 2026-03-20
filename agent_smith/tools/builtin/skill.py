"""Skill tool for executing custom commands."""

from nanocode.tools import Tool, ToolResult
from nanocode.skills import SkillsManager


class SkillTool(Tool):
    """Tool for executing custom skills/commands."""

    def __init__(self, skills_manager: SkillsManager):
        super().__init__(
            name="skill",
            description="Execute a custom skill/command defined in .agent/skills/",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the skill to execute",
                    },
                    "input": {
                        "type": "string",
                        "description": "Input to pass to the skill",
                    },
                },
                "required": ["name"],
            },
        )
        self.skills_manager = skills_manager

    async def execute(self, name: str = None, input: str = None, **kwargs) -> ToolResult:
        """Execute a skill by name."""
        if not name:
            return ToolResult(success=False, content=None, error="Skill name is required")

        try:
            skill = self.skills_manager.get_skill(name)

            context = {
                "input": input or "",
                "kwargs": kwargs,
            }

            result = await self.skills_manager.execute_skill(name, {"input": input}, context)

            return ToolResult(success=True, content=result)
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class ListSkillsTool(Tool):
    """Tool for listing available skills."""

    def __init__(self, skills_manager: SkillsManager):
        super().__init__(
            name="list_skills",
            description="List all available custom skills/commands",
            parameters={
                "type": "object",
                "properties": {},
            },
        )
        self.skills_manager = skills_manager

    async def execute(self, **kwargs) -> ToolResult:
        """List all available skills."""
        try:
            skills = self.skills_manager.list_skills()
            if not skills:
                return ToolResult(
                    success=True,
                    content="No skills found. Create .agent/skills/<skill-name>/skill.md to define a skill.",
                )

            lines = ["Available skills:"]
            for s in skills:
                lines.append(f"  - {s['name']}: {s['description']}")

            return ToolResult(success=True, content="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


def register_skill_tools(registry, skills_manager: SkillsManager):
    """Register skill-related tools."""
    registry.register(SkillTool(skills_manager))
    registry.register(ListSkillsTool(skills_manager))
