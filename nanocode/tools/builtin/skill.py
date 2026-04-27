"""Skill tool for executing custom commands."""

from nanocode.skills import SkillsManager
from nanocode.tools import Tool, ToolResult


class SkillTool(Tool):
    """Tool for executing custom skills/commands."""

    def __init__(self, skills_manager: SkillsManager):
        super().__init__(
            name="skill",
            description="Load a specialized skill that provides domain-specific instructions. When you recognize that a task matches one of the available skills listed below, use this tool to load the full skill instructions. The skill will inject detailed instructions and workflows into the conversation context. Use name=<skill-name> to load a skill, then FOLLOW its instructions.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the skill to execute (e.g., mcp-builder, skill-creator, python-project-scaffold)",
                    },
                    "input": {
                        "type": "string",
                        "description": "The user's actual request to pass to the skill (e.g., 'build an MCP server for my API').",
                    },
                },
                "required": ["name"],
            },
        )
        self.skills_manager = skills_manager

    def get_schema(self) -> dict:
        """Get schema with dynamically generated skill list."""
        skills = self.skills_manager.list_skills()
        skill_lines = []
        if skills:
            skill_lines.append("")
            skill_lines.append("Available skills:")
            for s in skills:
                skill_lines.append(f"  - {s['name']}: {s['description']}")
        else:
            skill_lines.append("(No skills available)")

        description = (
            "Load a specialized skill that provides domain-specific instructions and workflows.\n"
            "When you recognize that a task matches one of the available skills listed below, use this tool to load the full skill instructions.\n"
            "The skill will inject detailed instructions, workflows, and access to bundled resources into the conversation context.\n"
            "IMPORTANT: After loading a skill, use 'todo(action='write', todos=[...])' to track the workflow steps, then FOLLOW the skill's instructions EXACTLY.\n"
            + "\n".join(skill_lines)
        )

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": self.parameters,
            },
        }

    async def execute(
        self, name: str = None, input: str = None, **kwargs
    ) -> ToolResult:
        """Execute a skill by name."""
        if not name:
            return ToolResult(
                success=False, content=None, error="Skill name is required"
            )

        try:
            skill_info = self.skills_manager.get_skill(name)
            if not skill_info:
                available = [s["name"] for s in self.skills_manager.list_skills()]
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Skill '{name}' not found. Available: {', '.join(available) if available else 'none'}",
                )

            context = {
                "input": input or "",
                "kwargs": kwargs,
            }

            result = await self.skills_manager.execute_skill(name, {"input": input}, context)

            skill_content = result.get("content", "")
            wrapped = f"→ Skill \"{name}\"\n\n{skill_content}"

            return ToolResult(success=True, content=wrapped, metadata={"skill_name": name})
        except Exception as e:
            return ToolResult(success=False, content=None, error=str(e))


class ListSkillsTool(Tool):
    """DEPRECATED: Use SkillTool directly instead."""

    def __init__(self, skills_manager: SkillsManager):
        super().__init__(
            name="list_skills",
            description="[DEPRECATED] Do NOT use this tool. Use 'skill' directly. "
            "When you want to use a skill, call: skill(name='<skill-name>', input='<your-request>')",
            parameters={"type": "object", "properties": {}},
        )
        self.skills_manager = skills_manager

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=False,
            content=None,
            error="list_skills is deprecated. Use 'skill' tool directly with name='<skill-name>' and input='<your-request>'",
        )


def register_skill_tools(registry, skills_manager: SkillsManager):
    """Register skill-related tools."""
    registry.register(SkillTool(skills_manager))
    registry.register(ListSkillsTool(skills_manager))
