"""Tests for event-based pipeline architecture."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSessionProcessorHeadless:
    """Test SessionProcessor in headless mode."""

    def test_headless_init(self):
        """Test SessionProcessor can be created in headless mode."""
        from nanocode.session.processor import SessionProcessor

        processor = SessionProcessor(headless=True)
        assert processor.headless is True
        assert processor.session is None
        assert processor.snapshot is None

    def test_headless_init_with_services(self):
        """Test SessionProcessor can be created with services."""
        from nanocode.session.processor import SessionProcessor

        mock_session = MagicMock()
        mock_snapshot = MagicMock()

        processor = SessionProcessor(
            session_service=mock_session,
            snapshot_service=mock_snapshot,
            headless=False,
        )
        assert processor.headless is False
        assert processor.session is mock_session
        assert processor.snapshot is mock_snapshot


class TestAgentPipeline:
    """Test AgentPipeline."""

    def test_pipeline_init_with_llm(self):
        """Test AgentPipeline can be initialized with just an LLM."""
        from nanocode.agent_pipeline import AgentPipeline
        from nanocode.llm.base import LLMBase
        from nanocode.session.processor import SessionProcessor

        mock_llm = MagicMock(spec=LLMBase)
        pipeline = AgentPipeline(llm=mock_llm)

        assert pipeline.llm is mock_llm
        assert pipeline.processor is not None
        assert isinstance(pipeline.processor, SessionProcessor)

    def test_pipeline_init_with_all_components(self):
        """Test AgentPipeline with all components."""
        from nanocode.agent_pipeline import AgentPipeline
        from nanocode.llm.base import LLMBase
        from nanocode.session.processor import SessionProcessor

        mock_llm = MagicMock(spec=LLMBase)
        mock_context = MagicMock()
        mock_tools = MagicMock()

        processor = SessionProcessor(headless=True)
        pipeline = AgentPipeline(
            llm=mock_llm,
            processor=processor,
            context_manager=mock_context,
            tool_registry=mock_tools,
        )

        assert pipeline.llm is mock_llm
        assert pipeline.processor is processor
        assert pipeline.context_manager is mock_context
        assert pipeline.tool_registry is mock_tools

    def test_pipeline_has_process_stream_method(self):
        """Test AgentPipeline has process_stream method."""
        from nanocode.agent_pipeline import AgentPipeline

        mock_llm = MagicMock()
        pipeline = AgentPipeline(llm=mock_llm)

        assert hasattr(pipeline, 'process_stream')
        assert callable(pipeline.process_stream)

    def test_pipeline_has_process_method(self):
        """Test AgentPipeline has process method."""
        from nanocode.agent_pipeline import AgentPipeline

        mock_llm = MagicMock()
        pipeline = AgentPipeline(llm=mock_llm)

        assert hasattr(pipeline, 'process')
        assert callable(pipeline.process)

    def test_pipeline_get_all_thinking(self):
        """Test get_all_thinking helper method."""
        from nanocode.agent_pipeline import AgentPipeline
        from nanocode.session.message import Message, ReasoningPart

        mock_llm = MagicMock()
        pipeline = AgentPipeline(llm=mock_llm)

        msg = Message(id="test", session_id="sess", role="assistant")
        msg.parts.append(ReasoningPart(id="r1", session_id="sess", message_id="test", text="thinking"))

        thinking = pipeline.get_all_thinking(msg)
        assert len(thinking) == 1
        assert thinking[0] == "thinking"

    def test_pipeline_get_text_content(self):
        """Test get_text_content helper method."""
        from nanocode.agent_pipeline import AgentPipeline
        from nanocode.session.message import Message, TextPart

        mock_llm = MagicMock()
        pipeline = AgentPipeline(llm=mock_llm)

        msg = Message(id="test", session_id="sess", role="assistant")
        msg.parts.append(TextPart(id="t1", session_id="sess", message_id="test", text="Hello "))
        msg.parts.append(TextPart(id="t2", session_id="sess", message_id="test", text="World"))

        text = pipeline.get_text_content(msg)
        assert text == "Hello World"

    def test_pipeline_get_tool_calls(self):
        """Test get_tool_calls helper method."""
        from nanocode.agent_pipeline import AgentPipeline
        from nanocode.session.message import Message, ToolPart

        mock_llm = MagicMock()
        pipeline = AgentPipeline(llm=mock_llm)

        msg = Message(id="test", session_id="sess", role="assistant")
        msg.parts.append(ToolPart(
            id="tc1",
            session_id="sess",
            message_id="test",
            tool="bash",
            call_id="call_1",
            state={"status": "running", "input": {"command": "ls"}},
        ))

        tool_calls = pipeline.get_tool_calls(msg)
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "bash"


class TestPipelineIntegration:
    """Integration tests for the pipeline."""

    def test_autonomous_agent_has_pipeline(self):
        """Test that AutonomousAgent has pipeline attribute."""
        from nanocode.config import get_config

        config = get_config()
        from nanocode.core import AutonomousAgent

        with patch('nanocode.core.get_config', return_value=config):
            agent = AutonomousAgent(config=config)

            assert hasattr(agent, 'pipeline')
            assert agent.pipeline is not None


class TestPipelineEventTypes:
    """Test that event types are properly defined."""

    def test_event_type_enum(self):
        """Test EventType enum has required types."""
        from nanocode.llm.events import EventType

        assert hasattr(EventType, 'START')
        assert hasattr(EventType, 'REASONING_START')
        assert hasattr(EventType, 'REASONING_DELTA')
        assert hasattr(EventType, 'TEXT_START')
        assert hasattr(EventType, 'TEXT_DELTA')
        assert hasattr(EventType, 'TOOL_CALL')
        assert hasattr(EventType, 'FINISH_STEP')

    def test_stream_event_types_importable(self):
        """Test all stream event types can be imported."""
        from nanocode.llm.events import (
            StreamEvent,
            ReasoningStartEvent,
            ReasoningDeltaEvent,
            ReasoningEndEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
            FinishStepEvent,
            ErrorEvent,
        )

        assert StreamEvent is not None
        assert ReasoningStartEvent is not None
        assert ReasoningDeltaEvent is not None
        assert ReasoningEndEvent is not None
        assert TextDeltaEvent is not None
        assert TextEndEvent is not None
        assert ToolCallEvent is not None
        assert FinishStepEvent is not None
        assert ErrorEvent is not None


class TestMessageParts:
    """Test Message parts."""

    def test_message_has_parts(self):
        """Test Message has parts attribute."""
        from nanocode.session.message import Message

        msg = Message(id="test", session_id="sess", role="assistant")
        assert hasattr(msg, 'parts')
        assert isinstance(msg.parts, list)

    def test_text_part(self):
        """Test TextPart works."""
        from nanocode.session.message import TextPart, PartType

        part = TextPart(id="t1", session_id="sess", message_id="msg", text="hello")
        assert part.text == "hello"
        assert part.type == PartType.TEXT

    def test_reasoning_part(self):
        """Test ReasoningPart works."""
        from nanocode.session.message import ReasoningPart, PartType

        part = ReasoningPart(id="r1", session_id="sess", message_id="msg", text="thinking")
        assert part.text == "thinking"
        assert part.type == PartType.REASONING

    def test_tool_part(self):
        """Test ToolPart works."""
        from nanocode.session.message import ToolPart, PartType

        part = ToolPart(
            id="tc1",
            session_id="sess",
            message_id="msg",
            tool="bash",
            call_id="call_1",
            state={"status": "pending"},
        )
        assert part.tool == "bash"
        assert part.state["status"] == "pending"
        assert part.type == PartType.TOOL


class TestPipelineModule:
    """Tests for nanocode/pipeline.py module."""

    def test_create_pipeline(self):
        """Test create_pipeline returns an AgentPipeline."""
        from nanocode.pipeline import create_pipeline
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        pipeline = create_pipeline(mock_llm)
        from nanocode.pipeline import AgentPipeline

        assert isinstance(pipeline, AgentPipeline)

    def test_pipeline_init(self):
        """Test AgentPipeline initialization."""
        from nanocode.pipeline import AgentPipeline
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        mock_processor = MagicMock()
        pipeline = AgentPipeline(llm=mock_llm, processor=mock_processor)
        assert pipeline.llm is mock_llm
        assert pipeline.processor is mock_processor

    @pytest.mark.asyncio
    async def test_pipeline_run(self):
        """Test AgentPipeline.run calls chat_stream and processes events."""
        from nanocode.pipeline import AgentPipeline
        from unittest.mock import AsyncMock, MagicMock

        async def empty_stream(*args, **kwargs):
            """Async generator that yields nothing."""
            return
            yield  # pragma: no cover

        mock_llm = MagicMock()
        mock_llm.chat_stream = empty_stream

        mock_processor = MagicMock()
        mock_processor._handle_event = AsyncMock()

        pipeline = AgentPipeline(llm=mock_llm, processor=mock_processor)
        msg = await pipeline.run(
            session_id="test-session",
            user_input="hello",
            tools=[],
        )
        assert msg.role == "assistant"
        assert msg.session_id == "test-session"
        assert msg.time_completed is not None