"""Tests for agent system."""

import pytest

from nanocode.agents import (
    AgentMode,
    PermissionAction,
    PermissionRule,
    AgentInfo,
    AgentRegistry,
    evaluate_permission,
    get_disabled_tools,
    create_default_agents,
    create_registry_from_config,
    match_pattern,
)


class TestPermissionRule:
    """Test permission rule."""

    def test_default_rule(self):
        """Test default rule creation."""
        rule = PermissionRule(permission="test", action=PermissionAction.ALLOW)

        assert rule.permission == "test"
        assert rule.pattern == "*"
        assert rule.action == PermissionAction.ALLOW

    def test_rule_with_pattern(self):
        """Test rule with pattern."""
        rule = PermissionRule(permission="read", pattern="*.env", action=PermissionAction.ASK)

        assert rule.permission == "read"
        assert rule.pattern == "*.env"
        assert rule.action == PermissionAction.ASK


class TestMatchPattern:
    """Test pattern matching."""

    def test_wildcard_match(self):
        """Test wildcard pattern matching."""
        assert match_pattern("*", "anything") is True
        assert match_pattern("*", "something") is True

    def test_specific_match(self):
        """Test specific pattern matching."""
        assert match_pattern("*.py", "test.py") is True
        assert match_pattern("*.py", "test.txt") is False

    def test_exact_match(self):
        """Test exact pattern matching."""
        assert match_pattern("test", "test") is True
        assert match_pattern("test", "other") is False


class TestEvaluatePermission:
    """Test permission evaluation."""

    def test_allow_all(self):
        """Test allow all rule."""
        rules = [PermissionRule(permission="*", action=PermissionAction.ALLOW)]

        assert evaluate_permission("read", "file.txt", rules) == PermissionAction.ALLOW
        assert evaluate_permission("edit", "file.txt", rules) == PermissionAction.ALLOW
        assert evaluate_permission("bash", "ls", rules) == PermissionAction.ALLOW

    def test_deny_specific(self):
        """Test deny specific permission."""
        rules = [
            PermissionRule(permission="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="edit", action=PermissionAction.DENY),
        ]

        assert evaluate_permission("read", "file.txt", rules) == PermissionAction.ALLOW
        assert evaluate_permission("edit", "file.txt", rules) == PermissionAction.DENY

    def test_ask_for_specific(self):
        """Test ask for specific pattern."""
        rules = [
            PermissionRule(permission="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="read", pattern="*.env", action=PermissionAction.ASK),
        ]

        assert evaluate_permission("read", "file.txt", rules) == PermissionAction.ALLOW
        assert evaluate_permission("read", ".env", rules) == PermissionAction.ASK

    def test_default_ask(self):
        """Test default ask when no rule matches."""
        rules = []

        assert evaluate_permission("read", "file.txt", rules) == PermissionAction.ASK


class TestGetDisabledTools:
    """Test getting disabled tools."""

    def test_all_allow(self):
        """Test no disabled tools when all allowed."""
        rules = [PermissionRule(permission="*", action=PermissionAction.ALLOW)]

        disabled = get_disabled_tools(["read", "edit", "bash"], rules)

        assert len(disabled) == 0

    def test_edit_deny(self):
        """Test edit tools disabled."""
        rules = [
            PermissionRule(permission="*", action=PermissionAction.ALLOW),
            PermissionRule(permission="edit", pattern="*", action=PermissionAction.DENY),
        ]

        disabled = get_disabled_tools(
            ["read", "edit", "write", "str_replace_editor", "bash"], rules
        )

        assert "edit" in disabled
        assert "write" in disabled
        assert "str_replace_editor" in disabled
        assert "read" not in disabled
        assert "bash" not in disabled


class TestAgentInfo:
    """Test agent info."""

    def test_build_agent(self):
        """Test build agent info."""
        agent = AgentInfo(
            name="build",
            description="Build agent",
            mode=AgentMode.PRIMARY,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
            ],
        )

        assert agent.name == "build"
        assert agent.mode == AgentMode.PRIMARY
        assert agent.native is True

    def test_plan_agent(self):
        """Test plan agent info."""
        agent = AgentInfo(
            name="plan",
            description="Plan agent",
            mode=AgentMode.PRIMARY,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="edit", pattern="*", action=PermissionAction.DENY),
            ],
        )

        assert agent.name == "plan"
        assert agent.mode == AgentMode.PRIMARY

    def test_general_agent(self):
        """Test general subagent info."""
        agent = AgentInfo(
            name="general",
            description="General agent",
            mode=AgentMode.SUBAGENT,
            native=True,
            permission=[
                PermissionRule(permission="*", action=PermissionAction.ALLOW),
            ],
        )

        assert agent.name == "general"
        assert agent.mode == AgentMode.SUBAGENT


class TestAgentRegistry:
    """Test agent registry."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry."""
        return AgentRegistry()

    def test_register_agent(self, registry):
        """Test registering an agent."""
        agent = AgentInfo(
            name="test",
            description="Test agent",
            mode=AgentMode.PRIMARY,
        )

        registry.register(agent)

        assert registry.get("test") == agent

    def test_get_nonexistent(self, registry):
        """Test getting nonexistent agent."""
        assert registry.get("nonexistent") is None

    def test_list_agents(self, registry):
        """Test listing agents."""
        registry.register(AgentInfo(name="a1", description="A1", mode=AgentMode.PRIMARY))
        registry.register(AgentInfo(name="a2", description="A2", mode=AgentMode.SUBAGENT))
        registry.register(
            AgentInfo(name="a3", description="A3", mode=AgentMode.PRIMARY, hidden=True)
        )

        agents = registry.list()

        assert len(agents) == 3

    def test_list_primary(self, registry):
        """Test listing primary agents."""
        registry.register(AgentInfo(name="a1", description="A1", mode=AgentMode.PRIMARY))
        registry.register(AgentInfo(name="a2", description="A2", mode=AgentMode.SUBAGENT))
        registry.register(
            AgentInfo(name="a3", description="A3", mode=AgentMode.PRIMARY, hidden=True)
        )

        primary = registry.list_primary()

        assert len(primary) == 1
        assert primary[0].name == "a1"

    def test_set_default(self, registry):
        """Test setting default agent."""
        registry.register(AgentInfo(name="a1", description="A1", mode=AgentMode.PRIMARY))
        registry.register(AgentInfo(name="a2", description="A2", mode=AgentMode.PRIMARY))

        registry.set_default("a2")

        assert registry.get_default().name == "a2"

    def test_set_default_invalid(self, registry):
        """Test setting default to nonexistent agent."""
        with pytest.raises(ValueError):
            registry.set_default("nonexistent")


class TestCreateDefaultAgents:
    """Test creating default agents."""

    def test_default_agents_created(self):
        """Test default agents are created."""
        registry = create_default_agents()

        assert registry.get("build") is not None
        assert registry.get("plan") is not None
        assert registry.get("general") is not None
        assert registry.get("explore") is not None

    def test_build_agent_permissions(self):
        """Test build agent has full permissions."""
        registry = create_default_agents()
        build = registry.get("build")

        assert build is not None
        assert build.mode == AgentMode.PRIMARY

        assert evaluate_permission("read", "file.txt", build.permission) == PermissionAction.ALLOW
        assert evaluate_permission("edit", "file.txt", build.permission) == PermissionAction.ALLOW
        assert evaluate_permission("bash", "ls", build.permission) == PermissionAction.ALLOW

    def test_plan_agent_denies_edit(self):
        """Test plan agent denies edit tools."""
        registry = create_default_agents()
        plan = registry.get("plan")

        assert plan is not None
        assert plan.mode == AgentMode.PRIMARY

        assert evaluate_permission("edit", "file.txt", plan.permission) == PermissionAction.DENY
        assert evaluate_permission("write", "file.txt", plan.permission) == PermissionAction.DENY
        assert evaluate_permission("read", "file.txt", plan.permission) == PermissionAction.ALLOW

    def test_general_agent_permissions(self):
        """Test general agent permissions."""
        registry = create_default_agents()
        general = registry.get("general")

        assert general is not None
        assert general.mode == AgentMode.SUBAGENT

        assert evaluate_permission("read", "file.txt", general.permission) == PermissionAction.ALLOW
        assert evaluate_permission("edit", "file.txt", general.permission) == PermissionAction.ALLOW

    def test_explore_agent_denies_edit(self):
        """Test explore agent denies edit tools."""
        registry = create_default_agents()
        explore = registry.get("explore")

        assert explore is not None
        assert explore.mode == AgentMode.SUBAGENT

        assert evaluate_permission("grep", "pattern", explore.permission) == PermissionAction.ALLOW
        assert evaluate_permission("glob", "*.py", explore.permission) == PermissionAction.ALLOW
        assert evaluate_permission("edit", "file.txt", explore.permission) == PermissionAction.DENY

    def test_default_agent_is_build(self):
        """Test default agent is build."""
        registry = create_default_agents()

        assert registry.get_default().name == "build"


class TestCreateRegistryFromConfig:
    """Test creating registry from config."""

    def test_custom_agent(self):
        """Test adding custom agent from config."""
        config = {
            "agents": {
                "custom": {
                    "my_agent": {
                        "description": "My custom agent",
                        "mode": "subagent",
                        "permission": {
                            "read": "allow",
                            "edit": "deny",
                        },
                    },
                },
            },
        }

        registry = create_registry_from_config(config)

        assert registry.get("my_agent") is not None
        assert registry.get("my_agent").description == "My custom agent"
        assert registry.get("my_agent").mode == AgentMode.SUBAGENT

    def test_disable_agent(self):
        """Test disabling an agent from config."""
        config = {
            "agents": {
                "custom": {
                    "build": {
                        "disable": True,
                    },
                },
            },
        }

        registry = create_registry_from_config(config)

        assert registry.get("build") is None

    def test_set_default_from_config(self):
        """Test setting default agent from config."""
        config = {
            "agents": {
                "default": "plan",
            },
        }

        registry = create_registry_from_config(config)

        assert registry.get_default().name == "plan"

    def test_override_existing_agent(self):
        """Test overriding existing agent from config."""
        config = {
            "agents": {
                "custom": {
                    "build": {
                        "description": "Custom description",
                    },
                },
            },
        }

        registry = create_registry_from_config(config)

        assert registry.get("build").description == "Custom description"
