"""Multi-level hierarchical agent system with depth/spawn limits."""

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("nanocode.hierarchical")


class HierarchyError(Exception):
    """Base exception for hierarchy errors."""

    pass


class MaxDepthError(HierarchyError):
    """Raised when max depth is exceeded."""

    pass


class MaxAgentsError(HierarchyError):
    """Raised when max concurrent agents is exceeded."""

    pass


class AgentDepth(Enum):
    """Agent depth levels."""

    ROOT = 0
    SUBAGENT_1 = 1
    SUBAGENT_2 = 2
    SUBAGENT_3 = 3
    SUBAGENT_4 = 4
    MAX = 5


@dataclass
class HierarchyConfig:
    """Configuration for hierarchical agents."""

    max_depth: int = 5
    max_concurrent: int = 10
    allow_parallel: bool = True
    spawn_timeout: int = 300


@dataclass
class AgentNode:
    """Represents an agent in the hierarchy."""

    id: str
    name: str
    depth: int
    parent_id: Optional[str] = None
    children: list = field(default_factory=list)
    state: str = "pending"
    created_at: Optional[float] = None
    metadata: dict = field(default_factory=dict)


class HierarchyManager:
    """Manages hierarchical agent tree."""

    def __init__(self, config: HierarchyConfig = None):
        self.config = config or HierarchyConfig()
        self._nodes: dict[str, AgentNode] = {}
        self._root_id: Optional[str] = None
        self._active_count: int = 0

    def set_root(self, name: str) -> str:
        """Set the root agent."""
        self._root_id = str(uuid.uuid4())
        node = AgentNode(
            id=self._root_id,
            name=name,
            depth=AgentDepth.ROOT.value,
            state="active",
        )
        self._nodes[self._root_id] = node
        self._active_count += 1
        logger.info(f"Set root agent: {name} ({self._root_id})")
        return self._root_id

    def spawn_agent(
        self,
        parent_id: str,
        name: str,
        metadata: dict = None,
    ) -> str:
        """Spawn a subagent under a parent."""
        parent = self._nodes.get(parent_id)
        if not parent:
            raise HierarchyError(f"Parent agent not found: {parent_id}")

        if parent.depth >= self.config.max_depth:
            raise MaxDepthError(
                f"Cannot spawn: max depth {self.config.max_depth} reached"
            )

        if self._active_count >= self.config.max_concurrent:
            raise MaxAgentsError(
                f"Cannot spawn: max concurrent agents {self.config.max_concurrent} reached"
            )

        agent_id = str(uuid.uuid4())
        node = AgentNode(
            id=agent_id,
            name=name,
            depth=parent.depth + 1,
            parent_id=parent_id,
            state="active",
            metadata=metadata or {},
        )
        self._nodes[agent_id] = node
        parent.children.append(agent_id)
        self._active_count += 1

        logger.info(
            f"Spawned agent: {name} ({agent_id}) under {parent.name}, depth={node.depth}"
        )
        return agent_id

    def get_agent(self, agent_id: str) -> Optional[AgentNode]:
        """Get an agent by ID."""
        return self._nodes.get(agent_id)

    def get_parent(self, agent_id: str) -> Optional[AgentNode]:
        """Get parent of an agent."""
        agent = self._nodes.get(agent_id)
        if not agent or not agent.parent_id:
            return None
        return self._nodes.get(agent.parent_id)

    def get_children(self, agent_id: str) -> list[AgentNode]:
        """Get children of an agent."""
        agent = self._nodes.get(agent_id)
        if not agent:
            return []
        return [self._nodes[c] for c in agent.children if c in self._nodes]

    def complete_agent(self, agent_id: str, result: str = None):
        """Mark an agent as completed."""
        agent = self._nodes.get(agent_id)
        if not agent:
            return

        agent.state = "completed"
        if result:
            agent.metadata["result"] = result
        self._active_count = max(0, self._active_count - 1)
        logger.info(f"Completed agent: {agent.name} ({agent_id})")

    def get_path(self, agent_id: str) -> list[str]:
        """Get path from root to agent."""
        path = []
        current = self._nodes.get(agent_id)
        while current:
            path.insert(0, current.name)
            current = (
                self._nodes.get(current.parent_id)
                if current.parent_id
                else None
            )
        return path

    def get_stats(self) -> dict:
        """Get hierarchy statistics."""
        return {
            "total_nodes": len(self._nodes),
            "active_agents": self._active_count,
            "max_depth": self.config.max_depth,
            "max_concurrent": self.config.max_concurrent,
        }


def create_hierarchy_manager(
    max_depth: int = 5,
    max_concurrent: int = 10,
) -> HierarchyManager:
    """Create a hierarchy manager."""
    config = HierarchyConfig(
        max_depth=max_depth,
        max_concurrent=max_concurrent,
    )
    return HierarchyManager(config)