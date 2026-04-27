"""Agent pipeline matching opencode's architecture.

Opencode: LLM.stream() → Stream<Event> → Processor.handleEvent() → Message with Parts
This: LLM.stream() → AsyncGenerator[StreamEvent] → Processor → Message with Parts
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, AsyncGenerator

from nanocode.llm.base import LLMBase
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
from nanocode.session.processor import ProcessorContext, SessionProcessor

logger = logging.getLogger("nanocode.pipeline")


class AgentPipeline:
    """Matches opencode's LLM → Processor → Message pipeline.

    Opencode: Effect.gen with stream processing
    This: Async generator with stream processing
    """

    def __init__(self, llm: LLMBase, processor: SessionProcessor):
        self.llm = llm
        self.processor = processor

    async def run(
        self,
        session_id: str,
        user_input: str,
        tools: List[dict],
        show_thinking: bool = True,
    ) -> Message:
        """Run complete agent interaction (matches opencode's flow).

        Returns complete Message with all Parts (text, reasoning, tool calls).
        """
        # Create assistant message
        message_id = f"msg_{int(time.time() * 1000)}"
        assistant_msg = Message(
            id=message_id,
            session_id=session_id,
            role="assistant",
            time_created=time.time(),
        )

        # Create processor context
        ctx = ProcessorContext(
            assistant_message=assistant_msg,
            session_id=session_id,
            model=None,  # TODO: get from LLM
        )

        # Get stream from LLM
        stream_input = {
            "user": type("User", (), {"message": user_input})(),
            "sessionID": session_id,
            "messages": [],  # TODO: get from context manager
            "tools": tools,
            "model": None,
        }

        # Process stream events
        async for event in self.llm.chat_stream([], tools):
            await self.processor._handle_event(ctx, event)

        # Mark completion
        assistant_msg.time_completed = time.time()

        return assistant_msg


def create_pipeline(llm: LLMBase) -> AgentPipeline:
    """Create pipeline matching opencode's architecture."""
    # Create processor (simplified - no full services)
    processor = SessionProcessor(
        session_service=None,  # TODO: wire up
        snapshot_service=None,
        permission_service=None,
        agent_service=None,
        llm_service=llm,
        config_service=None,
    )
    return AgentPipeline(llm, processor)
