"""LLM stream events matching opencode's event types.

Opencode uses Effect-TS streams, we use Python async generators.
Events drive the session processor to build message parts incrementally.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum


class EventType(Enum):
    """Types of LLM stream events (matching opencode)."""
    START = "start"
    REASONING_START = "reasoning-start"
    REASONING_DELTA = "reasoning-delta"
    REASONING_END = "reasoning-end"
    TOOL_INPUT_START = "tool-input-start"
    TOOL_INPUT_DELTA = "tool-input-delta"
    TOOL_INPUT_END = "tool-input-end"
    TOOL_CALL = "tool-call"
    TOOL_RESULT = "tool-result"
    TOOL_ERROR = "tool-error"
    TEXT_START = "text-start"
    TEXT_DELTA = "text-delta"
    TEXT_END = "text-end"
    START_STEP = "start-step"
    FINISH_STEP = "finish-step"
    FINISH = "finish"
    ERROR = "error"


@dataclass
class StreamEvent:
    """Base class for stream events."""
    type: EventType
    provider_metadata: Optional[Dict[str, Any]] = None


@dataclass
class ReasoningStartEvent(StreamEvent):
    """Reasoning/thinking started."""
    type: EventType = field(default=EventType.REASONING_START, init=False)
    id: str = ""  # Unique ID for this reasoning block


@dataclass
class ReasoningDeltaEvent(StreamEvent):
    """Reasoning/thinking text delta."""
    type: EventType = field(default=EventType.REASONING_DELTA, init=False)
    id: str = ""
    text: str = ""


@dataclass
class ReasoningEndEvent(StreamEvent):
    """Reasoning/thinking ended."""
    type: EventType = field(default=EventType.REASONING_END, init=False)
    id: str = ""


@dataclass
class ToolInputStartEvent(StreamEvent):
    """Tool input started."""
    type: EventType = field(default=EventType.TOOL_INPUT_START, init=False)
    tool_name: str = ""
    tool_call_id: str = ""


@dataclass
class ToolCallEvent(StreamEvent):
    """Tool call event."""
    type: EventType = field(default=EventType.TOOL_CALL, init=False)
    tool_call_id: str = ""
    tool_name: str = ""
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TextStartEvent(StreamEvent):
    """Text content started."""
    type: EventType = field(default=EventType.TEXT_START, init=False)


@dataclass
class TextDeltaEvent(StreamEvent):
    """Text content delta."""
    type: EventType = field(default=EventType.TEXT_DELTA, init=False)
    text: str = ""


@dataclass
class TextEndEvent(StreamEvent):
    """Text content ended."""
    type: EventType = field(default=EventType.TEXT_END, init=False)


@dataclass
class FinishStepEvent(StreamEvent):
    """Step finished."""
    type: EventType = field(default=EventType.FINISH_STEP, init=False)
    finish_reason: str = ""
    usage: Optional[Dict[str, int]] = None


@dataclass
class ErrorEvent(StreamEvent):
    """Error event."""
    type: EventType = field(default=EventType.ERROR, init=False)
    error: Optional[Exception] = None
