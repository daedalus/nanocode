"""Tests for long horizon task handling in nanocode."""

import pytest
from unittest.mock import Mock, patch


class TestLongHorizonConstants:
    """Test long horizon task constants exist."""

    def test_max_steps_message_exists(self):
        """Test MAX_STEPS_MESSAGE is defined."""
        from nanocode.core import MAX_STEPS_MESSAGE

        assert MAX_STEPS_MESSAGE is not None
        assert len(MAX_STEPS_MESSAGE) > 0

    def test_auto_continue_message_exists(self):
        """Test AUTO_CONTINUE_MESSAGE is defined."""
        from nanocode.core import AUTO_CONTINUE_MESSAGE

        assert AUTO_CONTINUE_MESSAGE is not None
        assert "Continue" in AUTO_CONTINUE_MESSAGE

    def test_overflow_continue_message_exists(self):
        """Test OVERFLOW_CONTINUE_MESSAGE is defined."""
        from nanocode.core import OVERFLOW_CONTINUE_MESSAGE

        assert OVERFLOW_CONTINUE_MESSAGE is not None
        assert "exceeded" in OVERFLOW_CONTINUE_MESSAGE.lower()


class TestRetryLogicLongTasks:
    """Test retry logic doesn't cause infinite loops in long tasks."""

    def test_retry_delay_capped(self):
        """Test retry delay caps at max delay."""
        from nanocode.core import RETRY_MAX_DELAY, calculate_retry_delay

        delay = calculate_retry_delay(1000)  # Very high attempt
        assert delay == RETRY_MAX_DELAY

    def test_retry_backoff_increases(self):
        """Test exponential backoff between attempts."""
        from nanocode.core import calculate_retry_delay

        delays = [calculate_retry_delay(i) for i in range(1, 10)]
        # Each delay should be >= previous
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1]

    def test_retry_respects_retry_after_header(self):
        """Test respects retry-after header."""
        from nanocode.core import calculate_retry_delay

        delay = calculate_retry_delay(1, "retry-after: 10")
        assert delay == 10.0


class TestDoomLoopDetectionLongTasks:
    """Test doom loop detection works over long horizons."""

    def test_no_false_positive_diverse_tools(self):
        """Test that using different tools doesn't trigger doom loop."""
        from nanocode.doom_loop import DoomLoopDetection

        detector = DoomLoopDetection(threshold=3)

        # Simulate using different tools (valid long task behavior)
        tools_args = [
            ("grep", {"pattern": "TODO"}),
            ("read", {"path": "file1.py"}),
            ("grep", {"pattern": "FIXME"}),
            ("read", {"path": "file2.py"}),
            ("bash", {"command": "ls -la"}),
        ]

        for tool, args in tools_args:
            result = detector.record_call(tool, args)
            assert result is False, f"False positive on {tool} with {args}"

    def test_detects_repeated_same_tool_same_args(self):
        """Test detects doom loop when same tool+args repeated."""
        from nanocode.doom_loop import DoomLoopDetection

        detector = DoomLoopDetection(threshold=3)

        # Repeat same call 5 times
        for i in range(5):
            result = detector.record_call("bash", {"command": "ls -la"})

        # Should detect doom loop
        assert detector.record_call("bash", {"command": "ls -la"}) is True

    def test_allows_progressive_tool_usage(self):
        """Test that gradually changing args doesn't trigger doom loop."""
        from nanocode.doom_loop import DoomLoopDetection

        detector = DoomLoopDetection(threshold=3)

        # Progressively read different files
        for i in range(10):
            result = detector.record_call("read", {"path": f"file{i}.py"})
            assert result is False, "False positive on progressive reads"

    def test_doom_loop_detection_clear(self):
        """Test that clearing doom loop detection works."""
        from nanocode.doom_loop import DoomLoopDetection

        detector = DoomLoopDetection(threshold=3)

        # Add some calls
        for i in range(5):
            detector.record_call("bash", {"command": "ls"})

        # Clear detection
        detector.clear("bash")

        # Should not detect doom loop now - check internal state
        assert len(detector._recent_calls.get("bash", [])) == 0


class TestContextManagementLongConversations:
    """Test context management over extended interactions."""

    def test_context_strategy_enum_exists(self):
        """Test ContextStrategy enum has required values."""
        from nanocode.context import ContextStrategy

        assert ContextStrategy.SLIDING_WINDOW
        assert ContextStrategy.SUMMARY
        assert ContextStrategy.IMPORTANCE

    def test_token_counter_estimate(self):
        """Test token estimation function exists."""
        from nanocode.context import TokenCounter

        tokens = TokenCounter.estimate_message_tokens("user", "Hello world")
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_context_manager_initialization(self):
        """Test ContextManager can be initialized."""
        from nanocode.context import ContextManager, ContextStrategy

        cm = ContextManager(max_tokens=8000, strategy=ContextStrategy.SLIDING_WINDOW)
        assert cm.max_tokens == 8000
        assert cm.strategy == ContextStrategy.SLIDING_WINDOW

    def test_add_message_increases_count(self):
        """Test adding messages works."""
        from nanocode.context import ContextManager, ContextStrategy

        cm = ContextManager(max_tokens=8000, strategy=ContextStrategy.SLIDING_WINDOW)
        initial_count = len(cm._messages)
        cm.add_message({"role": "user", "content": "Hello"})
        assert len(cm._messages) == initial_count + 1


class TestAutoContinueMechanism:
    """Test auto-continue works for long tasks."""

    def test_auto_continue_message_content(self):
        """Test AUTO_CONTINUE_MESSAGE has correct content."""
        from nanocode.core import AUTO_CONTINUE_MESSAGE

        assert "Continue" in AUTO_CONTINUE_MESSAGE
        assert "next steps" in AUTO_CONTINUE_MESSAGE.lower()

    def test_max_steps_message_content(self):
        """Test MAX_STEPS_MESSAGE has correct content."""
        from nanocode.core import MAX_STEPS_MESSAGE

        assert "Do NOT make any tool calls" in MAX_STEPS_MESSAGE
        assert "summarizing" in MAX_STEPS_MESSAGE.lower()

    def test_overflow_continue_message_content(self):
        """Test OVERFLOW_CONTINUE_MESSAGE has correct content."""
        from nanocode.core import OVERFLOW_CONTINUE_MESSAGE

        assert "exceeded" in OVERFLOW_CONTINUE_MESSAGE.lower()
        # Note: message doesn't contain "summarize", it explains media was removed


class TestIsRetryableError:
    """Test retryable error detection for long tasks."""

    def test_context_overflow_not_retryable(self):
        """Test context overflow is not retryable."""
        from nanocode.core import is_retryable_error

        err = Exception("context overflow error")
        retryable, reason = is_retryable_error(err)
        assert retryable is False
        assert reason is None

    def test_5xx_error_retryable(self):
        """Test 5xx errors are retryable."""
        from nanocode.core import is_retryable_error

        err = Exception("status_code: 503 Service Unavailable")
        retryable, reason = is_retryable_error(err)
        assert retryable is True
        assert "Server error" in reason

    def test_rate_limit_retryable(self):
        """Test rate limit errors are retryable."""
        from nanocode.core import is_retryable_error

        err = Exception("rate limit exceeded")
        retryable, reason = is_retryable_error(err)
        assert retryable is True
        assert "Rate limited" in reason


class TestAgentRegistryLongTasks:
    """Test agent registry for multi-agent long tasks."""

    def test_registry_creation(self):
        """Test AgentRegistry can be created."""
        from nanocode.agents import AgentRegistry

        registry = AgentRegistry()
        assert registry is not None

    def test_registry_has_methods(self):
        """Test registry has required methods."""
        from nanocode.agents import AgentRegistry

        registry = AgentRegistry()
        assert hasattr(registry, "register")
        assert hasattr(registry, "get")
        assert hasattr(registry, "set_default")
        assert hasattr(registry, "list_all")

    def test_create_default_agents(self):
        """Test default agents can be created."""
        from nanocode.agents import create_default_agents

        registry = create_default_agents()
        assert registry is not None
        # Should have at least one agent
        agents = registry.list_all()
        assert len(agents) > 0


class TestAutoExecuteFlag:
    """Test auto_execute flag in AutonomousAgent."""

    def test_auto_execute_default_false(self, tmp_path):
        """Test auto_execute defaults to False."""
        from nanocode.core import AutonomousAgent

        # Create a temporary config file
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
llm:
  default_model: gpt-4
  default_connector: openai
  connectors:
    openai:
      api_key: test-key
      model: gpt-4
""")

        from nanocode.config import Config
        config = Config(str(config_file))

        agent = AutonomousAgent(config)
        assert agent.auto_execute is False

    def test_auto_execute_can_be_enabled(self, tmp_path):
        """Test auto_execute can be set to True."""
        from nanocode.core import AutonomousAgent

        # Create a temporary config file
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
llm:
  default_model: gpt-4
  default_connector: openai
  connectors:
    openai:
      api_key: test-key
      model: gpt-4
""")

        from nanocode.config import Config
        config = Config(str(config_file))

        agent = AutonomousAgent(config, auto_execute=True)
        assert agent.auto_execute is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
