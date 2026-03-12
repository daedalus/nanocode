"""Agent state machine and state management."""

from enum import Enum, auto
from typing import Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path


class AgentState(Enum):
    """Agent execution states."""
    IDLE = auto()
    PLANNING = auto()
    EXECUTING = auto()
    REFLECTING = auto()
    WAITING = auto()
    COMPLETE = auto()
    ERROR = auto()


@dataclass
class TaskStep:
    """A single step in task execution."""
    id: str
    description: str
    tool: Optional[str] = None
    args: dict = field(default_factory=dict)
    result: Any = None
    status: str = "pending"  # pending, running, complete, failed
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class ExecutionPlan:
    """A plan containing multiple steps."""
    id: str
    goal: str
    steps: list[TaskStep] = field(default_factory=list)
    current_step: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    checkpoint_file: Optional[Path] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "tool": s.tool,
                    "args": s.args,
                    "result": str(s.result) if s.result else None,
                    "status": s.status,
                    "error": s.error,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                }
                for s in self.steps
            ],
            "current_step": self.current_step,
            "created_at": self.created_at.isoformat(),
        }

    def save_checkpoint(self, path: Path):
        """Save execution checkpoint."""
        self.checkpoint_file = path
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load_checkpoint(cls, path: Path) -> "ExecutionPlan":
        """Load execution checkpoint."""
        data = json.loads(path.read_text())
        plan = cls(id=data["id"], goal=data["goal"])
        plan.current_step = data["current_step"]
        plan.steps = [
            TaskStep(
                id=s["id"],
                description=s["description"],
                tool=s.get("tool"),
                args=s.get("args", {}),
                status=s["status"],
                error=s.get("error"),
            )
            for s in data["steps"]
        ]
        plan.checkpoint_file = path
        return plan


@dataclass
class AgentStateData:
    """Complete agent state data."""
    state: AgentState = AgentState.IDLE
    task: Optional[str] = None
    plan: Optional[ExecutionPlan] = None
    messages: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    error: Optional[str] = None
    last_update: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "state": self.state.name,
            "task": self.task,
            "plan": self.plan.to_dict() if self.plan else None,
            "messages": self.messages,
            "context": self.context,
            "error": self.error,
            "last_update": self.last_update.isoformat(),
        }
