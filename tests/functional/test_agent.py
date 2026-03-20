"""Tests for agent core functionality."""

import pytest
from unittest.mock import Mock, patch

from nanocode.core import AutonomousAgent
from nanocode.state import AgentState, ExecutionPlan, TaskStep
from nanocode.llm import Message, LLMResponse, ToolCall


class TestAgentState:
    """Test agent state."""

    def test_execution_plan_creation(self):
        """Test creating an execution plan."""
        plan = ExecutionPlan(
            id="test-123",
            goal="Test goal",
            steps=[
                TaskStep(id="step1", description="First step"),
                TaskStep(id="step2", description="Second step"),
            ],
        )

        assert plan.id == "test-123"
        assert plan.goal == "Test goal"
        assert len(plan.steps) == 2

    def test_execution_plan_to_dict(self):
        """Test plan serialization."""
        plan = ExecutionPlan(id="test", goal="Test")
        plan.steps.append(TaskStep(id="s1", description="Step 1"))

        d = plan.to_dict()

        assert d["id"] == "test"
        assert d["goal"] == "Test"
        assert len(d["steps"]) == 1


class TestLLMMessage:
    """Test LLM message handling."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = Message(role="user", content="Hello")

        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_message_to_dict(self):
        """Test message serialization."""
        msg = Message(role="user", content="Hello")

        d = msg.to_dict()

        assert d["role"] == "user"
        assert d["content"] == "Hello"

    def test_message_with_tool_calls(self):
        """Test message with tool calls."""
        tc = ToolCall("bash", {"command": "ls"})
        msg = Message(role="assistant", content="", tool_calls=[tc])

        d = msg.to_dict()

        assert "tool_calls" in d
        assert len(d["tool_calls"]) == 1


class MockLLM:
    """Mock LLM for testing."""

    def __init__(self, response_content: str = "Mock response"):
        self.response_content = response_content

    async def chat(self, messages, tools=None, **kwargs):
        return LLMResponse(content=self.response_content, tool_calls=[])

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield self.response_content


class MockToolExecutor:
    """Mock tool executor."""

    def __init__(self):
        pass

    async def execute(self, tool_name: str, args: dict):
        from nanocode.tools import ToolResult

        return ToolResult(success=True, content=f"Executed {tool_name}")

    def format_result(self, result):
        return str(result.content)


class TestAutonomousAgent:
    """Test autonomous agent."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config."""
        config = Mock()
        config.providers = {"openai": {"api_key": "test", "model": "gpt-4"}}
        config.default_provider = "openai"
        config.mcp_servers = {}
        config.tools = {}
        config.get = Mock(
            side_effect=lambda key, default=None: {
                "context": {},
                "planning": {},
            }.get(key, default)
        )
        return config

    def test_agent_initialization(self, mock_config):
        """Test agent initialization."""
        with patch("nanocode.core.create_llm") as mock_create:
            mock_create.return_value = MockLLM()

            agent = AutonomousAgent(mock_config)

            assert agent.state is not None
            assert agent.state.state == AgentState.IDLE

    def test_agent_has_tool_registry(self, mock_config):
        """Test agent has tool registry."""
        with patch("nanocode.core.create_llm") as mock_create:
            mock_create.return_value = MockLLM()

            agent = AutonomousAgent(mock_config)

            assert agent.tool_registry is not None

    def test_agent_has_file_tracker(self, mock_config):
        """Test agent has file tracker."""
        with patch("nanocode.core.create_llm") as mock_create:
            mock_create.return_value = MockLLM()

            agent = AutonomousAgent(mock_config)

            assert agent.file_tracker is not None


class TestAutonomousAgentAsync:
    """Test async functionality of autonomous agent."""

    @pytest.fixture
    def agent_with_mock_llm(self):
        """Create agent with mock LLM."""

        with patch("nanocode.llm.OpenAILLM") as MockOpenAI:
            mock_instance = MockLLM("Test response")
            MockOpenAI.return_value = mock_instance
            with patch("nanocode.llm.AnthropicLLM") as MockAnthropic:
                MockAnthropic.return_value = mock_instance
                with patch("nanocode.llm.OllamaLLM") as MockOllama:
                    MockOllama.return_value = mock_instance
                    agent = AutonomousAgent()
                    yield agent

    @pytest.mark.asyncio
    async def test_process_input(self, agent_with_mock_llm):
        """Test processing user input."""
        response = await agent_with_mock_llm.process_input("Hello")

        assert response == "Test response"
        assert agent_with_mock_llm.state.state == AgentState.COMPLETE


class TestConfig:
    """Test configuration."""

    def test_config_get(self):
        """Test config get method."""
        from nanocode.config import Config

        config = Config()

        assert config.get("nonexistent") is None
        assert config.get("nonexistent", "default") == "default"

    def test_config_set(self):
        """Test config set method."""
        from nanocode.config import Config

        config = Config()
        config.set("test.value", "hello")

        assert config.get("test.value") == "hello"
