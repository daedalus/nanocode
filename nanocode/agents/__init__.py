"""Agent types and registry for multi-agent system."""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("nanocode.agents")


class AgentMode(Enum):
    """Agent mode - primary, subagent, or all."""

    PRIMARY = "primary"
    SUBAGENT = "subagent"
    ALL = "all"


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
class AgentModel:
    """Model configuration for an agent."""

    provider_id: str
    model_id: str


@dataclass
class AgentInfo:
    """Agent configuration."""

    name: str
    description: str
    mode: AgentMode = AgentMode.PRIMARY
    native: bool = False
    hidden: bool = False
    system_prompt: str | None = None
    permission: list[PermissionRule] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    model: AgentModel | None = None
    variant: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    color: str | None = None
    steps: int | None = None


class AgentRegistry:
    """Registry for managing agents."""

    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}
        self._default_agent: str | None = None
        logger.debug("AgentRegistry initialized")

    def register(self, agent: AgentInfo):
        """Register an agent."""
        self._agents[agent.name] = agent
        logger.debug(
            f"Registered agent: name={agent.name}, mode={agent.mode.value}, "
            f"native={agent.native}, hidden={agent.hidden}"
        )

    def get(self, name: str) -> AgentInfo | None:
        """Get an agent by name."""
        agent = self._agents.get(name)
        logger.debug(f"get_agent({name}) -> {agent.name if agent else None}")
        return agent

    def list(self) -> list[AgentInfo]:
        """List all agents."""
        agents = list(self._agents.values())
        logger.debug(
            f"list_agents() -> {len(agents)} agents: {[a.name for a in agents]}"
        )
        return agents

    def list_primary(self) -> list[AgentInfo]:
        """List primary agents."""
        result = []
        for a in self._agents.values():
            if a.mode == AgentMode.PRIMARY and not a.hidden:
                result.append(a)
        logger.debug(
            f"list_primary() -> {len(result)} agents: {[a.name for a in result]}"
        )
        return result

    def list_all(self) -> list[AgentInfo]:
        """List all agents (including hidden and subagents)."""
        agents = list(self._agents.values())
        logger.debug(f"list_all() -> {len(agents)} agents: {[a.name for a in agents]}")
        return agents

    def set_default(self, name: str):
        """Set default agent."""
        if name not in self._agents:
            logger.error(f"set_default('{name}') failed: agent not found")
            raise ValueError(f"Agent '{name}' not found")
        self._default_agent = name
        logger.info(f"Default agent set to: {name}")

    def get_default(self) -> AgentInfo | None:
        """Get default agent."""
        if self._default_agent:
            agent = self._agents.get(self._default_agent)
            logger.debug(
                f"get_default() -> {agent.name if agent else None} (from _default_agent)"
            )
            return agent
        agent = self._agents.get("build")
        logger.debug(
            f"get_default() -> {agent.name if agent else None} (fallback to 'build')"
        )
        return agent


def expand_path(pattern: str) -> str:
    """Expand path patterns (e.g., ~/ and $HOME/)."""
    if pattern.startswith("~/"):
        return os.path.expanduser(pattern)
    if pattern.startswith("~"):
        return os.path.expanduser(pattern)
    if pattern.startswith("$HOME/"):
        return os.path.expandvars(pattern)
    if pattern.startswith("$HOME"):
        return os.path.expandvars(pattern)
    return pattern


def match_pattern(pattern: str, value: str) -> bool:
    """Match a pattern against a value using wildcards."""
    pattern = expand_path(pattern)
    if pattern == "*":
        return True
    result = fnmatch.fnmatch(value, pattern)
    logger.debug(f"match_pattern('{pattern}', '{value}') -> {result}")
    return result


def evaluate_permission(
    permission: str,
    pattern: str,
    rules: list[PermissionRule],
) -> PermissionAction:
    """Evaluate a permission request against rules."""
    for rule in reversed(rules):
        perm_match = match_pattern(rule.permission, permission)
        pat_match = match_pattern(rule.pattern, pattern)
        if perm_match and pat_match:
            logger.debug(
                f"evaluate_permission('{permission}', '{pattern}') -> {rule.action.value} "
                f"(matched rule: permission={rule.permission}, pattern={rule.pattern})"
            )
            return rule.action
    logger.debug(f"evaluate_permission('{permission}', '{pattern}') -> ask (no match)")
    return PermissionAction.ASK


def merge_rules(*rulesets: list[PermissionRule]) -> list[PermissionRule]:
    """Merge multiple rulesets."""
    return list(rulesets[0]) if rulesets else []


def get_disabled_tools(tools: list[str], rules: list[PermissionRule]) -> set[str]:
    """Get tools disabled by rules."""
    disabled = set()
    edit_tools = {
        "edit",
        "write",
        "patch",
        "str_replace_editor",
        "apply_patch",
        "multiedit",
    }

    for tool in tools:
        perm = "edit" if tool in edit_tools else tool
        for rule in rules:
            if (
                match_pattern(perm, rule.permission)
                and rule.pattern == "*"
                and rule.action == PermissionAction.DENY
            ):
                disabled.add(tool)
                logger.debug(
                    f"get_disabled_tools: '{tool}' disabled by rule (permission={rule.permission}, pattern={rule.pattern})"
                )
                break

    if disabled:
        logger.debug(f"get_disabled_tools({tools}) -> {disabled}")
    return disabled


def from_config(permission_config: dict) -> list[PermissionRule]:
    """Parse permission configuration into ruleset, handling path expansion."""
    rules: list[PermissionRule] = []
    for key, value in permission_config.items():
        if isinstance(value, str):
            rules.append(
                PermissionRule(
                    permission=key,
                    pattern="*",
                    action=PermissionAction(value),
                )
            )
        elif isinstance(value, dict):
            for pattern, action in value.items():
                rules.append(
                    PermissionRule(
                        permission=key,
                        pattern=expand_path(pattern),
                        action=PermissionAction(action),
                    )
                )
    return rules


def merge_rulesets(*rulesets: list[PermissionRule]) -> list[PermissionRule]:
    """Merge multiple rulesets by concatenating them."""
    return list(rulesets[0]) if rulesets else []


def create_default_agents() -> AgentRegistry:
    """Create default agents with built-in permissions (mirrors opencode behavior)."""
    logger.info("Creating default agent registry")
    registry = AgentRegistry()

    home = os.path.expanduser("~")
    glob_pattern = "*"

    logger.debug(f"Home directory: {home}")

    registry.register(
        AgentInfo(
            name="build",
            description="The default agent. Executes tools based on configured permissions.",
            mode=AgentMode.PRIMARY,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="doom_loop", action=PermissionAction.ASK),
                PermissionRule(
                    permission="external_directory",
                    pattern=glob_pattern,
                    action=PermissionAction.ASK,
                ),
                PermissionRule(
                    permission="external_directory",
                    pattern=f"{home}/*",
                    action=PermissionAction.ALLOW,
                ),
                PermissionRule(permission="question", action=PermissionAction.DENY),
                PermissionRule(permission="plan_enter", action=PermissionAction.DENY),
                PermissionRule(permission="plan_exit", action=PermissionAction.DENY),
                PermissionRule(
                    permission="read", pattern="*.env", action=PermissionAction.ASK
                ),
                PermissionRule(
                    permission="read", pattern="*.env.*", action=PermissionAction.ASK
                ),
                PermissionRule(
                    permission="read",
                    pattern="*.env.example",
                    action=PermissionAction.ALLOW,
                ),
                PermissionRule(
                    permission="task", pattern="*", action=PermissionAction.ALLOW
                ),
                PermissionRule(permission="todo", action=PermissionAction.ALLOW),
            ],
        )
    )

    registry.register(
        AgentInfo(
            name="plan",
            description="Plan mode. Disallows all edit tools.",
            mode=AgentMode.PRIMARY,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="doom_loop", action=PermissionAction.ASK),
                PermissionRule(
                    permission="external_directory",
                    pattern=f"{home}/.opencode/plans/*",
                    action=PermissionAction.ALLOW,
                ),
                PermissionRule(permission="question", action=PermissionAction.ALLOW),
                PermissionRule(permission="plan_enter", action=PermissionAction.DENY),
                PermissionRule(permission="plan_exit", action=PermissionAction.ALLOW),
                PermissionRule(
                    permission="edit", pattern="*", action=PermissionAction.DENY
                ),
                PermissionRule(
                    permission="write", pattern="*", action=PermissionAction.DENY
                ),
                PermissionRule(
                    permission="patch", pattern="*", action=PermissionAction.DENY
                ),
                PermissionRule(
                    permission="apply_patch", pattern="*", action=PermissionAction.DENY
                ),
                PermissionRule(
                    permission="multiedit", pattern="*", action=PermissionAction.DENY
                ),
                PermissionRule(
                    permission="read", pattern="*.env", action=PermissionAction.ASK
                ),
                PermissionRule(
                    permission="read", pattern="*.env.*", action=PermissionAction.ASK
                ),
                PermissionRule(permission="todo", action=PermissionAction.ALLOW),
                PermissionRule(permission="task", action=PermissionAction.ALLOW),
            ],
        )
    )

    registry.register(
        AgentInfo(
            name="general",
            description="General-purpose agent for researching complex questions and executing multi-step tasks.",
            mode=AgentMode.SUBAGENT,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="doom_loop", action=PermissionAction.ASK),
                PermissionRule(
                    permission="external_directory",
                    pattern=glob_pattern,
                    action=PermissionAction.ASK,
                ),
                PermissionRule(
                    permission="external_directory",
                    pattern=f"{home}/*",
                    action=PermissionAction.ALLOW,
                ),
                PermissionRule(permission="question", action=PermissionAction.DENY),
                PermissionRule(permission="plan_enter", action=PermissionAction.DENY),
                PermissionRule(permission="plan_exit", action=PermissionAction.DENY),
                PermissionRule(
                    permission="read", pattern="*.env", action=PermissionAction.ASK
                ),
                PermissionRule(
                    permission="read", pattern="*.env.*", action=PermissionAction.ASK
                ),
                PermissionRule(
                    permission="read",
                    pattern="*.env.example",
                    action=PermissionAction.ALLOW,
                ),
                PermissionRule(permission="todoread", action=PermissionAction.DENY),
                PermissionRule(permission="todowrite", action=PermissionAction.DENY),
                PermissionRule(permission="todo", action=PermissionAction.ALLOW),
            ],
        )
    )

    registry.register(
        AgentInfo(
            name="explore",
            description="Fast agent specialized for exploring codebases. Use for searches and code exploration.",
            mode=AgentMode.SUBAGENT,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="task", action=PermissionAction.DENY),
                PermissionRule(permission="doom_loop", action=PermissionAction.ASK),
                PermissionRule(
                    permission="external_directory",
                    pattern=glob_pattern,
                    action=PermissionAction.ASK,
                ),
                PermissionRule(
                    permission="external_directory",
                    pattern=f"{home}/*",
                    action=PermissionAction.ALLOW,
                ),
                PermissionRule(permission="edit", action=PermissionAction.DENY),
                PermissionRule(permission="write", action=PermissionAction.DENY),
            ],
        )
    )

    registry.set_default("build")

    logger.info(
        f"Default agents created: {[a.name for a in registry.list()]} (default: build)"
    )
    return registry


_default_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _default_registry
    if _default_registry is None:
        logger.debug("Creating new global agent registry")
        _default_registry = create_default_agents()
    else:
        logger.debug("Returning existing global agent registry")
    return _default_registry


def set_agent_registry(registry: AgentRegistry):
    """Set the global agent registry."""
    global _default_registry
    agent_names = [a.name for a in registry.list()]
    _default_registry = registry
    logger.info(f"Global agent registry replaced with: {agent_names}")


def create_registry_from_config(config: dict) -> AgentRegistry:
    """Create an agent registry from configuration (supports opencode-style config)."""
    logger.info("Creating agent registry from config")
    registry = create_default_agents()

    agents_config = config.get("agents", {})
    logger.debug(f"Agent config: {list(agents_config.keys())}")

    default_agent = agents_config.get("default")
    if default_agent:
        logger.info(f"Setting default agent from config: {default_agent}")
        try:
            registry.set_default(default_agent)
        except ValueError as e:
            logger.warning(f"Failed to set default agent: {e}")

    custom_agents = agents_config.get("custom", {})
    logger.debug(f"Custom agents in config: {list(custom_agents.keys())}")

    for name, agent_config in custom_agents.items():
        logger.debug(f"Processing agent config: {name} = {agent_config}")

        if agent_config.get("disable", False):
            logger.info(f"Disabling agent: {name}")
            registry._agents.pop(name, None)
            continue

        existing = registry.get(name)
        if existing:
            logger.debug(f"Modifying existing agent: {name}")
            if "description" in agent_config:
                existing.description = agent_config["description"]
            if "system_prompt" in agent_config:
                existing.system_prompt = agent_config["system_prompt"]
            if "hidden" in agent_config:
                existing.hidden = agent_config["hidden"]
            if "temperature" in agent_config:
                existing.temperature = agent_config["temperature"]
            if "top_p" in agent_config:
                existing.top_p = agent_config["top_p"]
            if "color" in agent_config:
                existing.color = agent_config["color"]
            if "steps" in agent_config:
                existing.steps = agent_config["steps"]
            if "variant" in agent_config:
                existing.variant = agent_config["variant"]
            if "model" in agent_config and isinstance(agent_config["model"], dict):
                model_cfg = agent_config["model"]
                existing.model = AgentModel(
                    provider_id=model_cfg.get("provider_id", "openai"),
                    model_id=model_cfg.get("model_id", "gpt-4"),
                )
                logger.debug(f"  Set model: {existing.model}")
        else:
            logger.debug(f"Creating new agent: {name}")
            permission_rules = from_config(agent_config.get("permission", {}))
            model_cfg = agent_config.get("model", {})
            model = None
            if isinstance(model_cfg, dict):
                model = AgentModel(
                    provider_id=model_cfg.get("provider_id", "openai"),
                    model_id=model_cfg.get("model_id", "gpt-4"),
                )
            registry.register(
                AgentInfo(
                    name=name,
                    description=agent_config.get(
                        "description", f"Custom agent: {name}"
                    ),
                    mode=AgentMode(agent_config.get("mode", "subagent")),
                    native=False,
                    system_prompt=agent_config.get("system_prompt"),
                    permission=permission_rules,
                    options=agent_config.get("options", {}),
                    model=model,
                    variant=agent_config.get("variant"),
                    temperature=agent_config.get("temperature"),
                    top_p=agent_config.get("top_p"),
                    color=agent_config.get("color"),
                    steps=agent_config.get("steps"),
                )
            )

    logger.info(f"Registry created with agents: {[a.name for a in registry.list()]}")
    return registry
