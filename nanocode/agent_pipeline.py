"""Core agent using opencode's event-based pipeline.

Architecture (matching opencode):
  LLM.chat_stream() → AsyncGenerator[StreamEvent]
  SessionProcessor → consumes events, builds Message with Parts
  Message.parts contains: TextPart, ReasoningPart, ToolPart, etc.

This replaces the old: LLM.chat() → LLMResponse approach.
"""

import asyncio
import logging
import time
from typing import List, Optional, Dict, Any

from nanocode.llm.base import LLMBase
from nanocode.llm.events import (
    StreamEvent, EventType,
    ReasoningStartEvent, ReasoningDeltaEvent, ReasoningEndEvent,
    ToolCallEvent, TextDeltaEvent, TextEndEvent, FinishStepEvent,
)
from nanocode.session.message import (
    Message, Part, PartType,
    TextPart, ReasoningPart, ToolPart,
)
from nanocode.session.processor import SessionProcessor, ProcessorContext

logger = logging.getLogger("nanocode.agent_pipeline")


class AgentPipeline:
    """Opencode-matching LLM → Agent pipeline.

    Flow: user_input → LLM stream → Processor → Message with Parts
    """

    def __init__(
        self,
        llm: LLMBase,
        processor: SessionProcessor,
        context_manager=None,
        tool_registry=None,
    ):
        self.llm = llm
        self.processor = processor
        self.context_manager = context_manager
        self.tool_registry = tool_registry

    async def process(
        self,
        session_id: str,
        user_input: str,
        tools: List[dict] = None,
        show_thinking: bool = True,
    ) -> Message:
        """Process user input through the pipeline (matches opencode's flow).

        Returns:
            Message with parts (text, reasoning, tool calls)
        """
        # Create assistant message
        message_id = f"msg_{int(time.time() * 1000)}"
        assistant_msg = Message(
            id=message_id,
            session_id=session_id,
            role="assistant",
            time_created=time.time(),
        )

        # Create processor context (matches opencode's ctx)
        ctx = ProcessorContext(
            assistant_message=assistant_msg,
            session_id=session_id,
            model=None,  # TODO: get from LLM
        )

        # Prepare messages for LLM
        messages = []
        if self.context_manager:
            messages = self.context_manager.prepare_messages()

        # Get stream from LLM
        stream_input = {
            "messages": messages,
            "tools": tools or [],
            "model": None,
        }

        logger.info(f"Starting LLM stream for session {session_id}")

        # Process stream events (matches opencode's process())
        final_result = "continue"
        try:
            async for event in self.llm.chat_stream(messages, tools):
                await self.processor._handle_event(ctx, event)

                # Check if we need to stop (compact, error, etc.)
                if ctx.needs_compaction:
                    final_result = "compact"
                    break

        except Exception as e:
            logger.error(f"Stream processing failed: {e}")
            assistant_msg.error = {"name": "StreamError", "message": str(e)}
            return assistant_msg

        # Cleanup
        await self.processor._cleanup(ctx)

        # Store thinking for display
        ctx.all_thinking = [
            part.text for part in assistant_msg.parts
            if isinstance(part, ReasoningPart) and part.text
        ]

        assistant_msg.time_completed = time.time()
        logger.info(f"Pipeline complete: {final_result}")

        return assistant_msg

    def get_all_thinking(self, message: Message) -> List[str]:
        """Extract all thinking from message parts."""
        return [
            part.text for part in message.parts
            if isinstance(part, ReasoningPart) and part.text
        ]

    def get_text_content(self, message: Message) -> str:
        """Extract text content from message parts."""
        return "".join(
            part.text for part in message.parts
            if isinstance(part, TextPart)
        )
