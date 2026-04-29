"""Skill tool for executing custom commands."""

from typing import Optional, TYPE_CHECKING
from nanocode.skills import SkillsManager
from nanocode.tools import Tool, ToolResult

# TYPE_CHECKING imports to avoid circular dependencies
if TYPE_CHECKING:
    from nanocode.agents import AgentInfo


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

    def get_schema(self, agent_info: Optional["AgentInfo"] = None) -> dict:
        """Get schema with dynamically generated skill list."""
        skills = self.skills_manager.list_skills(agent_info)
        skill_lines = []
        if skills:
            skill_lines.append("")
            skill_lines.append("Available skills:")
            for s in skills:
                desc = s['description'] or ""
                # Safety: truncate to 500 chars to prevent full body leak
                if len(desc) > 500:
                    desc = desc[:500] + "..."
                skill_lines.append(f"  - {s['name']}: {desc}")
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
                # Check if it's a permission issue
                agent_name = kwargs.get("_agent_name")
                if agent_name:
                    from nanocode.agents import get_agent_registry, PermissionAction, evaluate_permission
                    registry = get_agent_registry()
                    agent_info = registry.get(agent_name)
                    if agent_info:
                        # Check if skill exists but is denied by permissions
                        all_skills = self.skills_manager.list_skills()
                        skill_exists = any(s["name"] == name for s in all_skills)
                        if skill_exists:
                            # Skill exists, check permissions
                            action = evaluate_permission("skill", name, agent_info.permission)
                            if action == PermissionAction.DENY:
                                return ToolResult(
                                    success=False,
                                    content=None,
                                    error=f"Permission denied: skill '{name}' is not available for agent '{agent_name}'",
                                )
                
                available = [s["name"] for s in self.skills_manager.list_skills()]
                return ToolResult(
                    success=False,
                    content=None,
                    error=f"Skill '{name}' not found. Available: {', '.join(available) if available else 'none'}",
                )

            # Extract agent and session info from kwargs if present
            agent_name = kwargs.get("_agent_name")
            session_id = kwargs.get("_session_id")
            
            # Create agent info if we have agent name
            agent_info = None
            if agent_name:
                from nanocode.agents import get_agent_registry
                registry = get_agent_registry()
                agent_info = registry.get(agent_name)
                # If agent not found, create a basic one
                if agent_info is None:
                    from nanocode.agents import AgentInfo, AgentMode
                    agent_info = AgentInfo(
                        name=agent_name,
                        description=f"Agent {agent_name}",
                        mode=AgentMode.PRIMARY,
                        permission=[],  # Empty permissions
                    )

            context = {
                "input": input or "",
                "kwargs": kwargs,
                "agent_name": agent_name,
                "session_id": session_id,
                "agent_info": agent_info,
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
