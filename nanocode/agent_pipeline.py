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
from typing import List, Optional, Dict, Any, AsyncGenerator

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
from nanocode.tools import ToolCall

logger = logging.getLogger("nanocode.agent_pipeline")


class AgentPipeline:
    """Opencode-matching LLM → Agent pipeline.

    Flow: user_input → LLM stream → Processor → Message with Parts
    
    Supports two modes:
    1. Full pipeline: Process everything including tool calls
    2. Stream only: Just process LLM stream into Message parts (for hybrid approach)
    """

    def __init__(
        self,
        llm: LLMBase,
        processor: SessionProcessor = None,
        context_manager=None,
        tool_registry=None,
    ):
        self.llm = llm
        # Create headless processor if not provided
        self.processor = processor or SessionProcessor(headless=True)
        self.context_manager = context_manager
        self.tool_registry = tool_registry

    async def process_stream(
        self,
        session_id: str,
        messages: List,
        tools: List[dict] = None,
        on_token: callable = None,
    ) -> Message:
        """Process LLM stream into Message with Parts (matches opencode).
        
        This is the core streaming function - takes messages and tools,
        streams from LLM, and builds a Message with all parts.
        
        Args:
            session_id: The session ID
            messages: Prepared messages to send to LLM
            tools: Tool schemas
            on_token: Callback for streaming text tokens (optional)
            
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

        # Create processor context
        ctx = ProcessorContext(
            assistant_message=assistant_msg,
            session_id=session_id,
            model=self.llm.model,
        )

        logger.info(f"Starting LLM stream for session {session_id}")

        # Process stream events using the processor's event handler
        final_result = "continue"
        try:
            async for event in self.llm.chat_stream(messages, tools):
                logger.debug(f"Pipeline received event: {type(event).__name__} - {event}")
                await self.processor._handle_event(ctx, event)

                # Stream text tokens to callback (like opencode's onToken)
                if on_token and event.type == EventType.TEXT_DELTA:
                    if isinstance(event, TextDeltaEvent) and event.text:
                        on_token(event.text)

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
        logger.info(f"Pipeline stream complete: {final_result}")

        return assistant_msg

    async def process(
        self,
        session_id: str,
        user_input: str,
        tools: List[dict] = None,
        show_thinking: bool = True,
        on_token: callable = None,
    ) -> Message:
        """Process user input through the full pipeline.
        
        This method handles context management and streams the LLM response.
        For tool execution, use process_stream() and handle tool calls in the caller.
        
        Args:
            session_id: The session ID
            user_input: User's input text
            tools: Tool schemas
            show_thinking: Whether to include thinking in response
            on_token: Callback for streaming text tokens
            
        Returns:
            Message with parts (text, reasoning, tool calls)
        """
        # Prepare messages for LLM
        messages = []
        if self.context_manager:
            # Add user input to context first
            self.context_manager.add_message("user", user_input)
            messages = self.context_manager.prepare_messages()

        return await self.process_stream(
            session_id, messages, tools, on_token=on_token
        )

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

    def get_tool_calls(self, message: Message) -> List[ToolCall]:
        """Extract tool calls from message parts."""
        tool_calls = []
        for part in message.parts:
            if isinstance(part, ToolPart):
                state = part.state or {}
                if state.get("status") == "running" or state.get("status") == "pending":
                    tool_calls.append(ToolCall(
                        name=part.tool,
                        arguments=state.get("input", {}),
                        id=part.call_id,
                    ))
        return tool_calls

    def to_llm_response(self, message: Message) -> "LLMResponse":
        """Convert pipeline Message to LLMResponse for backward compatibility."""
        from nanocode.llm.base import LLMResponse
        
        content = self.get_text_content(message)
        thinking = "\n\n".join(self.get_all_thinking(message))
        tool_calls = self.get_tool_calls(message)
        
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            thinking=thinking,
            finish_reason=getattr(message, "finish", "stop"),
        )
