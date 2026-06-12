"""LLM stream events matching opencode's event types.

Opencode uses Effect-TS streams, we use Python async generators.
Events drive the session processor to build message parts incrementally.

Enhanced with Aura-style events:
- ToolCallStart/ToolCallArgsDelta/ToolCallEnd pattern
- Usage event with cache_hit/cache_miss buckets
- ApiError as a first-class event
- WorkerDispatchRequested event
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

    # Enhanced events (Aura-style)
    TOOL_CALL_START = "tool-call-start"
    TOOL_CALL_ARGS_DELTA = "tool-call-args-delta"
    TOOL_CALL_END = "tool-call-end"
    USAGE = "usage"
    API_ERROR = "api-error"
    WORKER_DISPATCH_REQUESTED = "worker-dispatch-requested"


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


# =====================================================
# Enhanced Events (Aura-style)
# =====================================================


@dataclass
class ToolCallStartEvent(StreamEvent):
    """Tool call started - initial announcement."""

    type: EventType = field(default=EventType.TOOL_CALL_START, init=False)
    tool_call_id: str = ""
    tool_name: str = ""
    provider_metadata: Optional[Dict[str, Any]] = None


@dataclass
class ToolCallArgsDeltaEvent(StreamEvent):
    """Tool call arguments streaming delta."""

    type: EventType = field(default=EventType.TOOL_CALL_ARGS_DELTA, init=False)
    tool_call_id: str = ""
    tool_name: str = ""
    args_delta: str = ""  # Partial JSON string


@dataclass
class ToolCallEndEvent(StreamEvent):
    """Tool call completed - final arguments."""

    type: EventType = field(default=EventType.TOOL_CALL_END, init=False)
    tool_call_id: str = ""
    tool_name: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    provider_metadata: Optional[Dict[str, Any]] = None


@dataclass
class UsageEvent(StreamEvent):
    """Token usage with cache hit/miss buckets."""

    type: EventType = field(default=EventType.USAGE, init=False)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    model: str = ""
    provider: str = ""


@dataclass
class ApiErrorEvent(StreamEvent):
    """API error as a first-class event (not exception)."""

    type: EventType = field(default=EventType.API_ERROR, init=False)
    error_code: str = ""
    error_message: str = ""
    status_code: Optional[int] = None
    retryable: bool = False
    provider: str = ""


@dataclass
class WorkerDispatchRequestedEvent(StreamEvent):
    """Worker dispatch requested for planner/worker handoff."""

    type: EventType = field(default=EventType.WORKER_DISPATCH_REQUESTED, init=False)
    task_id: str = ""
    task_description: str = ""
    spec: Optional[Dict[str, Any]] = None
    worker_model: Optional[str] = None
    provider_metadata: Optional[Dict[str, Any]] = None


# =====================================================
# Event Factory
# =====================================================


def create_event(event_type: EventType, **kwargs) -> StreamEvent:
    """Create an event by type.

    Args:
        event_type: Type of event to create
        **kwargs: Event-specific arguments

    Returns:
        StreamEvent instance
    """
    event_map = {
        EventType.START: StreamEvent,
        EventType.REASONING_START: ReasoningStartEvent,
        EventType.REASONING_DELTA: ReasoningDeltaEvent,
        EventType.REASONING_END: ReasoningEndEvent,
        EventType.TOOL_INPUT_START: ToolInputStartEvent,
        EventType.TOOL_CALL: ToolCallEvent,
        EventType.TEXT_START: TextStartEvent,
        EventType.TEXT_DELTA: TextDeltaEvent,
        EventType.TEXT_END: TextEndEvent,
        EventType.FINISH_STEP: FinishStepEvent,
        EventType.ERROR: ErrorEvent,
        EventType.TOOL_CALL_START: ToolCallStartEvent,
        EventType.TOOL_CALL_ARGS_DELTA: ToolCallArgsDeltaEvent,
        EventType.TOOL_CALL_END: ToolCallEndEvent,
        EventType.USAGE: UsageEvent,
        EventType.API_ERROR: ApiErrorEvent,
        EventType.WORKER_DISPATCH_REQUESTED: WorkerDispatchRequestedEvent,
    }

    event_class = event_map.get(event_type, StreamEvent)
    return event_class(**kwargs)
