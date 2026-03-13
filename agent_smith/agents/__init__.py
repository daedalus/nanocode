"""Agent types and registry for multi-agent system."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, List
import fnmatch
import os


class AgentMode(Enum):
    """Agent mode - primary or subagent."""
    PRIMARY = "primary"
    SUBAGENT = "subagent"


class PermissionAction(Enum):
    """Permission action types."""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionRule:
    """A single permission rule."""
    permission: str
    pattern: str = "*"
    action: PermissionAction = PermissionAction.ASK


@dataclass
class AgentInfo:
    """Agent configuration."""
    name: str
    description: str
    mode: AgentMode = AgentMode.PRIMARY
    native: bool = False
    hidden: bool = False
    system_prompt: Optional[str] = None
    permission: list[PermissionRule] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """Registry for managing agents."""

    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}
        self._default_agent: Optional[str] = None

    def register(self, agent: AgentInfo):
        """Register an agent."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> Optional[AgentInfo]:
        """Get an agent by name."""
        return self._agents.get(name)

    def list(self) -> list[AgentInfo]:
        """List all agents."""
        return list(self._agents.values())

    def list_primary(self) -> list[AgentInfo]:
        """List primary agents."""
        result = []
        for a in self._agents.values():
            if a.mode == AgentMode.PRIMARY and not a.hidden:
                result.append(a)
        return result

    def set_default(self, name: str):
        """Set default agent."""
        if name not in self._agents:
            raise ValueError(f"Agent '{name}' not found")
        self._default_agent = name

    def get_default(self) -> Optional[AgentInfo]:
        """Get default agent."""
        if self._default_agent:
            return self._agents.get(self._default_agent)
        return self._agents.get("build")


def expand_path(pattern: str) -> str:
    """Expand path patterns."""
    if pattern.startswith("~/"):
        return os.path.expanduser(pattern)
    if pattern.startswith("$HOME/"):
        return os.path.expandvars(pattern)
    return pattern


def match_pattern(pattern: str, value: str) -> bool:
    """Match a pattern against a value using wildcards."""
    pattern = expand_path(pattern)
    if pattern == "*":
        return True
    return fnmatch.fnmatch(value, pattern)


def evaluate_permission(
    permission: str,
    pattern: str,
    rules: list[PermissionRule],
) -> PermissionAction:
    """Evaluate a permission request against rules."""
    for rule in reversed(rules):
        if match_pattern(rule.permission, permission) and match_pattern(rule.pattern, pattern):
            return rule.action
    return PermissionAction.ASK


def merge_rules(*rulesets: list[PermissionRule]) -> list[PermissionRule]:
    """Merge multiple rulesets."""
    return list(rulesets[0]) if rulesets else []


def get_disabled_tools(tools: list[str], rules: list[PermissionRule]) -> set[str]:
    """Get tools disabled by rules."""
    disabled = set()
    edit_tools = {"edit", "write", "patch", "str_replace_editor"}
    
    for tool in tools:
        perm = "edit" if tool in edit_tools else tool
        for rule in rules:
            if match_pattern(perm, rule.permission) and rule.pattern == "*" and rule.action == PermissionAction.DENY:
                disabled.add(tool)
                break
    
    return disabled


def create_default_agents() -> AgentRegistry:
    """Create default agents with built-in permissions."""
    registry = AgentRegistry()

    registry.register(AgentInfo(
        name="build",
        description="The default agent. Executes tools based on configured permissions.",
        mode=AgentMode.PRIMARY,
        native=True,
        permission=[
            PermissionRule(permission="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="question", action=PermissionAction.ALLOW),
            PermissionRule(permission="plan_enter", action=PermissionAction.ALLOW),
            PermissionRule(permission="read", pattern="*.env", action=PermissionAction.ASK),
            PermissionRule(permission="read", pattern="*.env.*", action=PermissionAction.ASK),
            PermissionRule(permission="read", pattern="*.env.example", action=PermissionAction.ALLOW),
        ],
    ))

    registry.register(AgentInfo(
        name="plan",
        description="Plan mode. Disallows all edit tools. Asks permission before running bash.",
        mode=AgentMode.PRIMARY,
        native=True,
        permission=[
            PermissionRule(permission="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="question", action=PermissionAction.ALLOW),
            PermissionRule(permission="plan_exit", action=PermissionAction.ALLOW),
            PermissionRule(permission="edit", pattern="*", action=PermissionAction.DENY),
            PermissionRule(permission="write", pattern="*", action=PermissionAction.DENY),
            PermissionRule(permission="bash", action=PermissionAction.ASK),
            PermissionRule(permission="read", pattern="*.env", action=PermissionAction.ASK),
            PermissionRule(permission="read", pattern="*.env.*", action=PermissionAction.ASK),
        ],
    ))

    registry.register(AgentInfo(
        name="general",
        description="General-purpose agent for researching complex questions and executing multi-step tasks.",
        mode=AgentMode.SUBAGENT,
        native=True,
        permission=[
            PermissionRule(permission="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="todoread", action=PermissionAction.DENY),
            PermissionRule(permission="todowrite", action=PermissionAction.DENY),
        ],
    ))

    registry.register(AgentInfo(
        name="explore",
        description="Fast agent specialized for exploring codebases. Use for searches and code exploration.",
        mode=AgentMode.SUBAGENT,
        native=True,
        permission=[
            PermissionRule(permission="grep", action=PermissionAction.ALLOW),
            PermissionRule(permission="glob", action=PermissionAction.ALLOW),
            PermissionRule(permission="list", action=PermissionAction.ALLOW),
            PermissionRule(permission="bash", action=PermissionAction.ALLOW),
            PermissionRule(permission="webfetch", action=PermissionAction.ALLOW),
            PermissionRule(permission="websearch", action=PermissionAction.ALLOW),
            PermissionRule(permission="codesearch", action=PermissionAction.ALLOW),
            PermissionRule(permission="read", action=PermissionAction.ALLOW),
            PermissionRule(permission="edit", action=PermissionAction.DENY),
            PermissionRule(permission="write", action=PermissionAction.DENY),
        ],
    ))

    registry.set_default("build")

    return registry


_default_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = create_default_agents()
    return _default_registry


def set_agent_registry(registry: AgentRegistry):
    """Set the global agent registry."""
    global _default_registry
    _default_registry = registry


def create_registry_from_config(config: dict) -> AgentRegistry:
    """Create an agent registry from configuration."""
    registry = create_default_agents()
    
    agents_config = config.get("agents", {})
    default_agent = agents_config.get("default")
    if default_agent:
        try:
            registry.set_default(default_agent)
        except ValueError:
            pass
    
    custom_agents = agents_config.get("custom", {})
    for name, agent_config in custom_agents.items():
        if agent_config.get("disable", False):
            registry._agents.pop(name, None)
            continue
        
        existing = registry.get(name)
        if existing:
            if "description" in agent_config:
                existing.description = agent_config["description"]
            if "system_prompt" in agent_config:
                existing.system_prompt = agent_config["system_prompt"]
            if "hidden" in agent_config:
                existing.hidden = agent_config["hidden"]
        else:
            permission_rules = _parse_permission_config(agent_config.get("permission", {}))
            registry.register(AgentInfo(
                name=name,
                description=agent_config.get("description", f"Custom agent: {name}"),
                mode=AgentMode(agent_config.get("mode", "subagent")),
                native=False,
                system_prompt=agent_config.get("system_prompt"),
                permission=permission_rules,
                options=agent_config.get("options", {}),
            ))
    
    return registry


def _parse_permission_config(permission_config: dict) -> list[PermissionRule]:
    """Parse permission configuration into rules."""
    rules = []
    for key, value in permission_config.items():
        if isinstance(value, str):
            rules.append(PermissionRule(
                permission=key,
                action=PermissionAction(value),
            ))
        elif isinstance(value, dict):
            for pattern, action in value.items():
                rules.append(PermissionRule(
                    permission=key,
                    pattern=pattern,
                    action=PermissionAction(action),
                ))
    return rules
