"""Tests for the Enhanced Streaming Events."""

import pytest

from nanocode.llm.events import (
    EventType,
    StreamEvent,
    ReasoningStartEvent,
    ReasoningDeltaEvent,
    ReasoningEndEvent,
    ToolInputStartEvent,
    ToolCallEvent,
    TextStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    FinishStepEvent,
    ErrorEvent,
    ToolCallStartEvent,
    ToolCallArgsDeltaEvent,
    ToolCallEndEvent,
    UsageEvent,
    ApiErrorEvent,
    WorkerDispatchRequestedEvent,
    create_event,
)


class TestEventType:
    """Tests for EventType enum."""

    def test_all_event_types_exist(self):
        """Test that all event types are defined."""
        # Original events
        assert EventType.START
        assert EventType.REASONING_START
        assert EventType.REASONING_DELTA
        assert EventType.REASONING_END
        assert EventType.TOOL_INPUT_START
        assert EventType.TOOL_CALL
        assert EventType.TEXT_START
        assert EventType.TEXT_DELTA
        assert EventType.TEXT_END
        assert EventType.FINISH_STEP
        assert EventType.ERROR

        # Enhanced events
        assert EventType.TOOL_CALL_START
        assert EventType.TOOL_CALL_ARGS_DELTA
        assert EventType.TOOL_CALL_END
        assert EventType.USAGE
        assert EventType.API_ERROR
        assert EventType.WORKER_DISPATCH_REQUESTED


class TestToolCallStartEvent:
    """Tests for ToolCallStartEvent."""

    def test_creation(self):
        """Test creating a ToolCallStartEvent."""
        event = ToolCallStartEvent(
            tool_call_id="call_123",
            tool_name="bash",
        )
        assert event.type == EventType.TOOL_CALL_START
        assert event.tool_call_id == "call_123"
        assert event.tool_name == "bash"


class TestToolCallArgsDeltaEvent:
    """Tests for ToolCallArgsDeltaEvent."""

    def test_creation(self):
        """Test creating a ToolCallArgsDeltaEvent."""
        event = ToolCallArgsDeltaEvent(
            tool_call_id="call_123",
            tool_name="bash",
            args_delta='{"command": "ls',
        )
        assert event.type == EventType.TOOL_CALL_ARGS_DELTA
        assert event.args_delta == '{"command": "ls'


class TestToolCallEndEvent:
    """Tests for ToolCallEndEvent."""

    def test_creation(self):
        """Test creating a ToolCallEndEvent."""
        event = ToolCallEndEvent(
            tool_call_id="call_123",
            tool_name="bash",
            input={"command": "ls -la"},
        )
        assert event.type == EventType.TOOL_CALL_END
        assert event.input == {"command": "ls -la"}


class TestUsageEvent:
    """Tests for UsageEvent."""

    def test_creation(self):
        """Test creating a UsageEvent."""
        event = UsageEvent(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cache_hit_tokens=20,
            cache_miss_tokens=80,
            model="gpt-4o",
            provider="openai",
        )
        assert event.type == EventType.USAGE
        assert event.prompt_tokens == 100
        assert event.cache_hit_tokens == 20

    def test_defaults(self):
        """Test default values."""
        event = UsageEvent()
        assert event.prompt_tokens == 0
        assert event.cache_hit_tokens == 0


class TestApiErrorEvent:
    """Tests for ApiErrorEvent."""

    def test_creation(self):
        """Test creating an ApiErrorEvent."""
        event = ApiErrorEvent(
            error_code="rate_limit_exceeded",
            error_message="Too many requests",
            status_code=429,
            retryable=True,
            provider="openai",
        )
        assert event.type == EventType.API_ERROR
        assert event.error_code == "rate_limit_exceeded"
        assert event.retryable is True


class TestWorkerDispatchRequestedEvent:
    """Tests for WorkerDispatchRequestedEvent."""

    def test_creation(self):
        """Test creating a WorkerDispatchRequestedEvent."""
        event = WorkerDispatchRequestedEvent(
            task_id="T1",
            task_description="Implement feature X",
            spec={"files": ["main.py"]},
            worker_model="gpt-4o",
        )
        assert event.type == EventType.WORKER_DISPATCH_REQUESTED
        assert event.task_id == "T1"
        assert event.worker_model == "gpt-4o"


class TestCreateEvent:
    """Tests for create_event factory."""

    def test_create_tool_call_start(self):
        """Test creating ToolCallStartEvent via factory."""
        event = create_event(
            EventType.TOOL_CALL_START,
            tool_call_id="call_123",
            tool_name="bash",
        )
        assert isinstance(event, ToolCallStartEvent)
        assert event.tool_name == "bash"

    def test_create_usage(self):
        """Test creating UsageEvent via factory."""
        event = create_event(
            EventType.USAGE,
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert isinstance(event, UsageEvent)
        assert event.prompt_tokens == 100

    def test_create_api_error(self):
        """Test creating ApiErrorEvent via factory."""
        event = create_event(
            EventType.API_ERROR,
            error_code="rate_limit",
            error_message="Too many requests",
        )
        assert isinstance(event, ApiErrorEvent)
        assert event.error_code == "rate_limit"

    def test_create_worker_dispatch(self):
        """Test creating WorkerDispatchRequestedEvent via factory."""
        event = create_event(
            EventType.WORKER_DISPATCH_REQUESTED,
            task_id="T1",
            task_description="Build feature",
        )
        assert isinstance(event, WorkerDispatchRequestedEvent)
        assert event.task_id == "T1"

    def test_create_generic_event(self):
        """Test creating generic StreamEvent via factory."""
        # StreamEvent requires type as positional arg, so we pass it
        event = create_event(EventType.START, type=EventType.START)
        assert isinstance(event, StreamEvent)
        assert event.type == EventType.START


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing events."""

    def test_original_events_still_work(self):
        """Test that original events are not broken."""
        reasoning = ReasoningStartEvent(id="r1")
        assert reasoning.type == EventType.REASONING_START

        tool_call = ToolCallEvent(
            tool_call_id="tc1",
            tool_name="read",
            input={"path": "file.py"},
        )
        assert tool_call.type == EventType.TOOL_CALL

        text = TextDeltaEvent(text="Hello")
        assert text.type == EventType.TEXT_DELTA

        finish = FinishStepEvent(finish_reason="stop")
        assert finish.type == EventType.FINISH_STEP
