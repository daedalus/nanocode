"""Tests for hierarchical agent module."""

import pytest

from nanocode.hierarchical import (
    AgentDepth,
    AgentNode,
    HierarchyConfig,
    HierarchyError,
    HierarchyManager,
    MaxDepthError,
    MaxAgentsError,
    create_hierarchy_manager,
)


class TestAgentNode:
    """Test AgentNode dataclass."""

    def test_creation(self):
        """Test creating an agent node."""
        node = AgentNode(
            id="test-id",
            name="test-agent",
            depth=1,
            parent_id="parent-id",
        )

        assert node.id == "test-id"
        assert node.name == "test-agent"
        assert node.depth == 1
        assert node.parent_id == "parent-id"
        assert node.state == "pending"
        assert node.children == []

    def test_default_values(self):
        """Test default values."""
        node = AgentNode(id="id", name="name", depth=0)

        assert node.state == "pending"
        assert node.parent_id is None
        assert node.metadata == {}


class TestHierarchyConfig:
    """Test HierarchyConfig."""

    def test_defaults(self):
        """Test default config."""
        config = HierarchyConfig()

        assert config.max_depth == 5
        assert config.max_concurrent == 10
        assert config.allow_parallel is True

    def test_custom_config(self):
        """Test custom config."""
        config = HierarchyConfig(max_depth=3, max_concurrent=5)

        assert config.max_depth == 3
        assert config.max_concurrent == 5


class TestHierarchyManager:
    """Test HierarchyManager."""

    def test_set_root(self):
        """Test setting root agent."""
        manager = HierarchyManager()
        root_id = manager.set_root("root-agent")

        assert root_id is not None
        node = manager.get_agent(root_id)
        assert node.name == "root-agent"
        assert node.depth == 0

    def test_spawn_agent(self):
        """Test spawning an agent."""
        manager = HierarchyManager()
        root_id = manager.set_root("root")
        child_id = manager.spawn_agent(root_id, "child")

        assert child_id is not None
        child = manager.get_agent(child_id)
        assert child.name == "child"
        assert child.depth == 1

    def test_spawn_nested(self):
        """Test spawning nested agents."""
        manager = HierarchyManager()
        root_id = manager.set_root("root")
        child1_id = manager.spawn_agent(root_id, "child1")
        child2_id = manager.spawn_agent(child1_id, "child2")

        child2 = manager.get_agent(child2_id)
        assert child2.depth == 2

    def test_get_parent(self):
        """Test getting parent."""
        manager = HierarchyManager()
        root_id = manager.set_root("root")
        child_id = manager.spawn_agent(root_id, "child")

        parent = manager.get_parent(child_id)
        assert parent.name == "root"

    def test_get_children(self):
        """Test getting children."""
        manager = HierarchyManager()
        root_id = manager.set_root("root")
        child1_id = manager.spawn_agent(root_id, "child1")
        child2_id = manager.spawn_agent(root_id, "child2")

        children = manager.get_children(root_id)
        child_names = {c.name for c in children}
        assert child_names == {"child1", "child2"}

    def test_complete_agent(self):
        """Test completing an agent."""
        manager = HierarchyManager()
        root_id = manager.set_root("root")
        child_id = manager.spawn_agent(root_id, "child")

        manager.complete_agent(child_id, "result")
        child = manager.get_agent(child_id)
        assert child.state == "completed"
        assert child.metadata["result"] == "result"

    def test_get_path(self):
        """Test getting path from root."""
        manager = HierarchyManager()
        root_id = manager.set_root("root")
        child1_id = manager.spawn_agent(root_id, "child1")
        child2_id = manager.spawn_agent(child1_id, "child2")

        path = manager.get_path(child2_id)
        assert path == ["root", "child1", "child2"]

    def test_max_depth_error(self):
        """Test max depth enforcement."""
        config = HierarchyConfig(max_depth=2)
        manager = HierarchyManager(config)
        root_id = manager.set_root("root")

        child1_id = manager.spawn_agent(root_id, "child1")
        child2_id = manager.spawn_agent(child1_id, "child2")

        with pytest.raises(MaxDepthError):
            manager.spawn_agent(child2_id, "child3")

    def test_max_concurrent_error(self):
        """Test max concurrent agents enforcement."""
        config = HierarchyConfig(max_concurrent=2)
        manager = HierarchyManager(config)
        root_id = manager.set_root("root")

        child1_id = manager.spawn_agent(root_id, "child1")

        with pytest.raises(MaxAgentsError):
            manager.spawn_agent(root_id, "child2")

    def test_get_stats(self):
        """Test getting statistics."""
        manager = HierarchyManager(HierarchyConfig(max_depth=3, max_concurrent=5))
        root_id = manager.set_root("root")
        manager.spawn_agent(root_id, "child")

        stats = manager.get_stats()
        assert stats["total_nodes"] == 2
        assert stats["active_agents"] == 2
        assert stats["max_depth"] == 3
        assert stats["max_concurrent"] == 5

    def test_parent_not_found(self):
        """Test error on missing parent."""
        manager = HierarchyManager()

        with pytest.raises(HierarchyError):
            manager.spawn_agent("nonexistent", "child")

    def test_complete_decrement_count(self):
        """Test active count decrements on completion."""
        manager = HierarchyManager()
        root_id = manager.set_root("root")
        child_id = manager.spawn_agent(root_id, "child")

        assert manager._active_count == 2

        manager.complete_agent(child_id)
        assert manager._active_count == 1

    def test_complete_nonexistent(self):
        """Test completing nonexistent agent."""
        manager = HierarchyManager()
        manager.set_root("root")

        manager.complete_agent("nonexistent")


class TestCreateHierarchyManager:
    """Test factory function."""

    def test_create_with_defaults(self):
        """Test create with defaults."""
        manager = create_hierarchy_manager()

        assert isinstance(manager, HierarchyManager)
        assert manager.config.max_depth == 5
        assert manager.config.max_concurrent == 10

    def test_create_with_params(self):
        """Test create with params."""
        manager = create_hierarchy_manager(max_depth=3, max_concurrent=5)

        assert manager.config.max_depth == 3
        assert manager.config.max_concurrent == 5


class TestAgentDepth:
    """Test AgentDepth enum."""

    def test_depth_values(self):
        """Test depth values."""
        assert AgentDepth.ROOT.value == 0
        assert AgentDepth.SUBAGENT_1.value == 1
        assert AgentDepth.SUBAGENT_2.value == 2
        assert AgentDepth.MAX.value == 5