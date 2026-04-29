"""Session processor matching opencode's processor.ts architecture.

Opencode: LLM streams events → Processor.handleEvent() → builds message parts
This implementation mirrors that architecture in Python.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, AsyncGenerator

from nanocode.llm.events import (
    StreamEvent, EventType,
    ReasoningStartEvent, ReasoningDeltaEvent, ReasoningEndEvent,
    ToolCallEvent, ToolInputStartEvent,
    TextStartEvent, TextDeltaEvent, TextEndEvent,
    FinishStepEvent, ErrorEvent,
)
from nanocode.session.message import (
    Message, Part, PartType,
    ReasoningPart, TextPart, ToolPart, StepStartPart, StepFinishPart,
)

logger = logging.getLogger(__name__)

# Threshold to detect doom loops (repeated tool calls)
DOOM_LOOP_THRESHOLD = 3


@dataclass
class ProcessorContext:
    """Context for processing a single assistant message (matches opencode's ctx)."""
    assistant_message: Message
    session_id: str
    model: Any  # Provider model info
    tool_calls: Dict[str, "ToolCallState"] = field(default_factory=dict)
    should_break: bool = False
    snapshot: Optional[str] = None
    blocked: bool = False
    needs_compaction: bool = False
    current_text: Optional[TextPart] = None
    reasoning_map: Dict[str, ReasoningPart] = field(default_factory=dict)
    all_thinking: List[str] = field(default_factory=list)


@dataclass
class ToolCallState:
    """State for a tool call being processed."""
    part_id: str
    message_id: str
    session_id: str
    done: asyncio.Event = field(default_factory=asyncio.Event)


class SessionProcessor:
    """Processes LLM stream events into message parts (matches opencode's SessionProcessor).

    Opencode: Effect.gen with handleEvent() processing stream events
    Nanocode: Async generator processing stream events
    
    Can work in "headless" mode without services for simpler integration.
    """

    def __init__(self, session_service=None, snapshot_service=None, permission_service=None,
                 agent_service=None, llm_service=None, config_service=None,
                 headless: bool = True):
        """Initialize processor.
        
        Args:
            session_service: Optional session service for persistence
            snapshot_service: Optional snapshot service
            permission_service: Optional permission service
            agent_service: Optional agent service
            llm_service: Optional LLM service
            config_service: Optional config service
            headless: If True, skip service calls that require persistence (default True)
        """
        self.session = session_service
        self.snapshot = snapshot_service
        self.permission = permission_service
        self.agents = agent_service
        self.llm = llm_service
        self.config = config_service
        self.headless = headless

    async def create_handle(self, input: dict) -> "ProcessorHandle":
        """Create a processor handle for one assistant message (matches opencode's create())."""
        ctx = ProcessorContext(
            assistant_message=input["assistant_message"],
            session_id=input["session_id"],
            model=input["model"],
        )

        return ProcessorHandle(ctx, self)

    async def process_stream(
        self,
        ctx: "ProcessorContext",
        llm_stream,
    ) -> str:
        """Process an LLM stream into message parts (matches opencode's process()).
        
        Args:
            ctx: The processor context
            llm_stream: An async generator yielding StreamEvent objects
        """
        ctx.needs_compaction = False

        # Track snapshot before stream starts (like opencode)
        if not self.headless and self.snapshot:
            ctx.snapshot = await self.snapshot.track()

        # Process events
        async for event in llm_stream:
            await self._handle_event(ctx, event)

            # Check if we need compaction
            if ctx.needs_compaction:
                break

        # Cleanup
        await self._cleanup(ctx)

        if ctx.needs_compaction:
            return "compact"
        if ctx.blocked or ctx.assistant_message.error:
            return "stop"
        return "continue"

    async def process(self, handle: "ProcessorHandle", stream_input: dict) -> str:
        """Process an LLM stream into message parts (matches opencode's process()).
        
        Note: This method requires llm_service to be set. For direct LLM usage,
        use process_stream() instead.
        """
        if not self.llm:
            raise ValueError("llm_service not set. Use process_stream() with direct LLM.")
        ctx = handle.ctx
        
        # Get stream from LLM service
        stream = await self.llm.stream(stream_input)
        return await self.process_stream(ctx, stream)

    async def _handle_event(self, ctx: ProcessorContext, event: StreamEvent):
        """Handle a single stream event (matches opencode's handleEvent())."""
        if event.type == EventType.START:
            await self._handle_start(ctx)
        elif event.type == EventType.REASONING_START:
            await self._handle_reasoning_start(ctx, event)
        elif event.type == EventType.REASONING_DELTA:
            await self._handle_reasoning_delta(ctx, event)
        elif event.type == EventType.REASONING_END:
            await self._handle_reasoning_end(ctx, event)
        elif event.type == EventType.TOOL_INPUT_START:
            await self._handle_tool_input_start(ctx, event)
        elif event.type == EventType.TOOL_CALL:
            await self._handle_tool_call(ctx, event)
        elif event.type == EventType.TEXT_START:
            await self._handle_text_start(ctx, event)
        elif event.type == EventType.TEXT_DELTA:
            await self._handle_text_delta(ctx, event)
        elif event.type == EventType.TEXT_END:
            await self._handle_text_end(ctx, event)
        elif event.type == EventType.START_STEP:
            await self._handle_start_step(ctx)
        elif event.type == EventType.FINISH_STEP:
            await self._handle_finish_step(ctx, event)
        elif event.type == EventType.ERROR:
            await self._handle_error(ctx, event)

    async def _handle_start(self, ctx: ProcessorContext):
        """Handle stream start."""
        if self.headless or not self.session:
            return
        await self.session.set_status(ctx.session_id, {"type": "busy"})

    async def _handle_reasoning_start(self, ctx: ProcessorContext, event: ReasoningStartEvent):
        """Handle reasoning start (matches opencode's reasoning-start)."""
        if event.id in ctx.reasoning_map:
            return
        reasoning_part = ReasoningPart(
            id=f"part_{int(time.time() * 1000)}",
            session_id=ctx.session_id,
            message_id=ctx.assistant_message.id,
            text="",
            time_start=time.time(),
            metadata=event.provider_metadata,
        )
        ctx.reasoning_map[event.id] = reasoning_part
        ctx.all_thinking.append("")  # Placeholder for this reasoning block
        # Add to message parts (always do this, even in headless mode)
        ctx.assistant_message.parts.append(reasoning_part)
        if self.headless or not self.session:
            return
        await self.session.update_part(reasoning_part)

    async def _handle_reasoning_delta(self, ctx: ProcessorContext, event: ReasoningDeltaEvent):
        """Handle reasoning delta (matches opencode's reasoning-delta)."""
        if event.id not in ctx.reasoning_map:
            return
        ctx.reasoning_map[event.id].text += event.text
        # Update the accumulated thinking
        ctx.all_thinking[-1] = ctx.reasoning_map[event.id].text
        if self.headless or not self.session:
            return
        await self.session.update_part_delta({
            "session_id": ctx.reasoning_map[event.id].session_id,
            "message_id": ctx.reasoning_map[event.id].message_id,
            "part_id": ctx.reasoning_map[event.id].id,
            "field": "text",
            "delta": event.text,
        })

    async def _handle_reasoning_end(self, ctx: ProcessorContext, event: ReasoningEndEvent):
        """Handle reasoning end (matches opencode's reasoning-end)."""
        if event.id not in ctx.reasoning_map:
            return
        part = ctx.reasoning_map[event.id]
        part.time_end = time.time()
        if event.provider_metadata:
            part.metadata = event.provider_metadata
        if self.headless or not self.session:
            return
        await self.session.update_part(part)
        del ctx.reasoning_map[event.id]

    async def _handle_tool_input_start(self, ctx: ProcessorContext, event: ToolInputStartEvent):
        """Handle tool input start."""
        tool_part = ToolPart(
            id=f"part_{int(time.time() * 1000)}",
            session_id=ctx.session_id,
            message_id=ctx.assistant_message.id,
            tool=event.tool_name,
            call_id=event.tool_call_id,
            state={"status": "pending", "input": {}, "raw": ""},
        )
        # Add to message parts (always do this, even in headless mode)
        ctx.assistant_message.parts.append(tool_part)
        ctx.tool_calls[event.tool_call_id] = ToolCallState(
            part_id=tool_part.id,
            message_id=tool_part.message_id,
            session_id=tool_part.session_id,
        )
        if self.headless or not self.session:
            return
        await self.session.update_part(tool_part)

    async def _handle_tool_call(self, ctx: ProcessorContext, event: ToolCallEvent):
        """Handle tool call (matches opencode's tool-call)."""
        if event.tool_call_id not in ctx.tool_calls:
            return
        # Update tool part with input
        # (Implementation depends on session service)
        pass

    async def _handle_text_start(self, ctx: ProcessorContext, event: TextStartEvent):
        """Handle text start."""
        ctx.current_text = TextPart(
            id=f"part_{int(time.time() * 1000)}",
            session_id=ctx.session_id,
            message_id=ctx.assistant_message.id,
            text="",
            time_start=time.time(),
        )
        # Add to message parts (always do this, even in headless mode)
        ctx.assistant_message.parts.append(ctx.current_text)
        if self.headless or not self.session:
            return
        await self.session.update_part(ctx.current_text)

    async def _handle_text_delta(self, ctx: ProcessorContext, event: TextDeltaEvent):
        """Handle text delta."""
        # Auto-create TextPart if not exists (for LLMs that don't send TextStartEvent)
        if not ctx.current_text:
            ctx.current_text = TextPart(
                id=f"part_{int(time.time() * 1000)}",
                session_id=ctx.session_id,
                message_id=ctx.assistant_message.id,
                text="",
                time_start=time.time(),
            )
            ctx.assistant_message.parts.append(ctx.current_text)

        ctx.current_text.text += event.text
        if self.headless or not self.session:
            return
        await self.session.update_part_delta({
            "session_id": ctx.current_text.session_id,
            "message_id": ctx.current_text.message_id,
            "part_id": ctx.current_text.id,
            "field": "text",
            "delta": event.text,
        })

    async def _handle_text_end(self, ctx: ProcessorContext, event: TextEndEvent):
        """Handle text end."""
        if not ctx.current_text:
            return
        ctx.current_text.time_end = time.time()
        if self.headless or not self.session:
            return
        await self.session.update_part(ctx.current_text)
        ctx.current_text = None

    async def _handle_start_step(self, ctx: ProcessorContext):
        """Handle step start."""
        if not self.headless and self.snapshot:
            ctx.snapshot = await self.snapshot.track()
        step_part = StepStartPart(
            id=f"part_{int(time.time() * 1000)}",
            session_id=ctx.session_id,
            message_id=ctx.assistant_message.id,
            snapshot=ctx.snapshot,
        )
        ctx.assistant_message.parts.append(step_part)
        if self.headless or not self.session:
            return
        await self.session.update_part(step_part)

    async def _handle_finish_step(self, ctx: ProcessorContext, event: FinishStepEvent):
        """Handle step finish (matches opencode's finish-step)."""
        ctx.assistant_message.finish = event.finish_reason
        # Update usage, cost, etc.
        if self.headless or not self.session:
            return
        await self.session.update_message(ctx.assistant_message)

        # Check for compaction
        if self.config:
            try:
                config = await self.config.get()
                if hasattr(config, 'context') and hasattr(config.context, 'max_tokens'):
                    # Simplified compaction check
                    pass
            except Exception:
                pass

    async def _handle_error(self, ctx: ProcessorContext, event: ErrorEvent):
        """Handle error event."""
        if event.error:
            ctx.assistant_message.error = str(event.error)

    async def _cleanup(self, ctx: ProcessorContext):
        """Cleanup after processing (matches opencode's cleanup())."""
        # Handle any remaining reasoning parts
        for part in list(ctx.reasoning_map.values()):
            part.time_end = part.time_end or time.time()
            if not self.headless and self.session:
                # Note: update_part expects the part object, not a dict
                pass
        ctx.reasoning_map.clear()

        # Handle any remaining tool calls
        for tool_call_id in list(ctx.tool_calls.keys()):
            # Mark as error/interrupted
            pass

        ctx.assistant_message.time_completed = time.time()
        if self.headless or not self.session:
            return
        await self.session.update_message(ctx.assistant_message)


class ProcessorHandle:
    """Handle for processing a single message (matches opencode's Handle)."""

    def __init__(self, ctx: ProcessorContext, processor: SessionProcessor):
        self.ctx = ctx
        self._processor = processor

    @property
    def message(self) -> Message:
        return self.ctx.assistant_message

    @property
    def all_thinking(self) -> List[str]:
        return self.ctx.all_thinking
