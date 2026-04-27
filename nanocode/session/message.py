"""Message and Part types matching opencode's message-v2.ts architecture.

Opencode uses: Message with Parts (TextPart, ReasoningPart, ToolPart, etc.)
This implementation mirrors that in Python.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union
from enum import Enum
from datetime import datetime


class PartType(Enum):
    """Types of message parts (matching opencode's Part discriminators)."""
    TEXT = "text"
    REASONING = "reasoning"
    TOOL = "tool"
    STEP_START = "step-start"
    STEP_FINISH = "step-finish"
    SNAPSHOT = "snapshot"
    PATCH = "patch"


@dataclass
class Part:
    """Base class for message parts."""
    id: str
    session_id: str
    message_id: str
    type: PartType


@dataclass
class TextPart(Part):
    """Text content part."""
    type: PartType = field(default=PartType.TEXT, init=False)
    text: str = ""
    metadata: Optional[Dict[str, Any]] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    synthetic: bool = False


@dataclass
class ReasoningPart(Part):
    """Reasoning/thinking part (matching opencode's ReasoningPart)."""
    type: PartType = field(default=PartType.REASONING, init=False)
    text: str = ""
    metadata: Optional[Dict[str, Any]] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None


@dataclass
class ToolPart(Part):
    """Tool call part (matching opencode's ToolPart)."""
    type: PartType = field(default=PartType.TOOL, init=False)
    tool: str = ""
    call_id: str = ""
    state: Dict[str, Any] = field(default_factory=dict)  # status, input, output, etc.
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class StepStartPart(Part):
    """Step start marker."""
    type: PartType = field(default=PartType.STEP_START, init=False)
    snapshot: Optional[str] = None


@dataclass
class StepFinishPart(Part):
    """Step finish marker."""
    type: PartType = field(default=PartType.STEP_FINISH, init=False)
    reason: str = ""
    tokens: Optional[Dict[str, Any]] = None
    cost: float = 0.0
    snapshot: Optional[str] = None


@dataclass
class Message:
    """Message with parts (matching opencode's Assistant/User messages)."""
    id: str
    session_id: str
    role: str  # "user" or "assistant"
    parts: List[Part] = field(default_factory=list)
    time_created: Optional[float] = None
    time_completed: Optional[float] = None
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    agent: str = ""
    cost: float = 0.0
    tokens: Optional[Dict[str, Any]] = None
    finish: Optional[str] = None
    error: Optional[Dict[str, Any]] = None

    def add_part(self, part: Part):
        """Add a part to the message."""
        self.parts.append(part)

    def get_text(self) -> str:
        """Get all text from TextParts."""
        return "".join(
            part.text for part in self.parts if isinstance(part, TextPart)
        )

    def get_reasoning(self) -> List[str]:
        """Get all reasoning texts."""
        return [
            part.text for part in self.parts if isinstance(part, ReasoningPart)
        ]

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """Get all tool calls."""
        return [
            {"tool": part.tool, "input": part.state.get("input", {}), "call_id": part.call_id}
            for part in self.parts
            if isinstance(part, ToolPart) and part.state.get("status") == "completed"
        ]
