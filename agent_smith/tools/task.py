"""Task tool for launching subagents."""

from typing import Optional
import uuid
from dataclasses import dataclass, field

from agent_smith.tools import Tool, ToolResult
from agent_smith.agents import (
    AgentRegistry,
    AgentInfo,
    AgentMode,
    PermissionAction,
)
from agent_smith.agents.permission import PermissionHandler


TASK_DESCRIPTION = """Launch a new agent to handle complex, multistep tasks autonomously.

Available agent types and the tools they have access to:
{agents}

When using the Task tool, you must specify a subagent_type parameter to select which agent type to use.

When to use the Task tool:
- When you are instructed to execute custom slash commands. Use the Task tool with the slash command invocation as the entire prompt.

When NOT to use the Task tool:
- If you want to read a specific file path, use the Read or Glob tool instead
- If you are searching for a specific class definition like "class Foo", use the Glob tool instead
- If you are searching for code within a specific file or set of 2-3 files, use the Read tool instead
- Other tasks that are not related to the agent descriptions above


Usage notes:
1. Launch multiple agents concurrently whenever possible, to maximize performance
2. When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result. The output includes a task_id you can reuse later to continue the same subagent session.
3. Each agent invocation starts with a fresh context unless you provide task_id to resume
4. The agent's outputs should generally be trusted
5. Clearly tell the agent whether you expect it to write code or just to do research
"""


@dataclass
class SubAgentSession:
    """Represents a subagent session."""

    id: str
    agent: AgentInfo
    messages: list = field(default_factory=list)
    parent_session_id: Optional[str] = None
    completed: bool = False


class TaskTool(Tool):
    """Tool for launching subagents to handle tasks."""

    def __init__(
        self,
        agent_registry: AgentRegistry,
        permission_handler: PermissionHandler,
    ):
        self.agent_registry = agent_registry
        self.permission_handler = permission_handler
        self.sessions: dict[str, SubAgentSession] = {}

        description = self._build_description()

        super().__init__(
            name="task",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "A short (3-5 words) description of the task",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The task for the agent to perform",
                    },
                    "subagent_type": {
                        "type": "string",
                        "description": "The type of specialized agent to use for this task",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Optional task ID to resume a previous task session",
                    },
                },
                "required": ["description", "prompt", "subagent_type"],
            },
        )

    def _get_accessible_agents(self, caller: Optional[AgentInfo] = None) -> list[AgentInfo]:
        """Get agents accessible to the caller based on permissions."""
        all_agents = [a for a in self.agent_registry.list() if a.mode != AgentMode.PRIMARY]

        if caller is None:
            return all_agents

        accessible = []
        for agent in all_agents:
            action = self._evaluate_task_permission(caller, agent.name)
            if action != PermissionAction.DENY:
                accessible.append(agent)
        return accessible

    def _evaluate_task_permission(self, caller: AgentInfo, subagent_name: str) -> PermissionAction:
        """Evaluate if caller can invoke a specific subagent."""
        for rule in caller.permission:
            if rule.permission == "task":
                if self._match_pattern(rule.pattern, subagent_name):
                    return rule.action
        return PermissionAction.ASK

    def _match_pattern(self, pattern: str, value: str) -> bool:
        """Match a pattern against a value using wildcards."""
        import fnmatch

        if pattern == "*":
            return True
        return fnmatch.fnmatch(value, pattern)

    def _build_description(self, caller: Optional[AgentInfo] = None) -> str:
        """Build the tool description with available agents."""
        accessible_agents = self._get_accessible_agents(caller)

        agent_list = []
        for a in accessible_agents:
            desc = a.description or "This subagent should only be called manually by the user."
            agent_list.append(f"- {a.name}: {desc}")

        agents_text = "\n".join(agent_list)
        return TASK_DESCRIPTION.replace("{agents}", agents_text)

    def update_description(self, caller: Optional[AgentInfo] = None):
        """Update the tool description based on caller's permissions."""
        self.description = self._build_description(caller)

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the task tool to launch a subagent."""
        description = kwargs.get("description", "")
        prompt = kwargs.get("prompt", "")
        subagent_type = kwargs.get("subagent_type", "")
        task_id = kwargs.get("task_id")

        subagent = self.agent_registry.get(subagent_type)
        if not subagent:
            return ToolResult(
                success=False,
                content=None,
                error=f"Unknown agent type: {subagent_type} is not a valid agent type",
            )

        session_id = task_id if task_id and task_id in self.sessions else str(uuid.uuid4())

        if session_id not in self.sessions:
            session = SubAgentSession(
                id=session_id,
                agent=subagent,
            )
            self.sessions[session_id] = session
            return ToolResult(
                success=True,
                content=f"task_id: {session_id}\n\nSubagent '{subagent_type}' session created. Use task_id to resume this session.",
                metadata={
                    "session_id": session_id,
                    "description": description,
                    "subagent_type": subagent_type,
                },
            )

        session = self.sessions[session_id]

        return ToolResult(
            success=True,
            content=f"Resuming task session {session_id} with agent {session.agent.name}",
            metadata={
                "session_id": session_id,
                "description": description,
            },
        )


def create_task_tool(
    agent_registry: AgentRegistry, permission_handler: PermissionHandler
) -> TaskTool:
    """Create and configure the task tool."""
    return TaskTool(
        agent_registry=agent_registry,
        permission_handler=permission_handler,
    )
