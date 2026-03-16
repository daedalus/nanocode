"""Tests for context manager."""

import pytest
from agent_smith.context import (
    ContextManager,
    ContextStrategy,
    TokenCounter,
    Message,
    MessagePartType,
    ModelLimits,
    ScrapManager,
)


class TestTokenCounter:
    """Test token counting."""

    def test_count_tokens_empty(self):
        """Test counting empty string."""
        assert TokenCounter.count_tokens("") >= 0

    def test_count_tokens_short(self):
        """Test counting short text."""
        tokens = TokenCounter.count_tokens("hello world")
        assert tokens >= 1

    def test_count_tokens_long(self):
        """Test counting long text."""
        text = "word " * 1000
        tokens = TokenCounter.count_tokens(text)
        assert tokens > 100

    def test_estimate_message_tokens(self):
        """Test estimating message tokens."""
        tokens = TokenCounter.estimate_message_tokens("user", "hello")
        assert tokens >= 1


class TestMessage:
    """Test message class."""

    def test_create_text_message(self):
        """Test creating text message."""
        msg = Message.create_text("user", "Hello world")

        assert msg.role == "user"
        assert len(msg.parts) == 1
        assert msg.parts[0].part_type == MessagePartType.TEXT
        assert msg.parts[0].content == "Hello world"

    def test_add_reasoning(self):
        """Test adding reasoning part."""
        msg = Message(role="assistant")
        msg.add_reasoning("Let me think about this...", {"provider": "openai"})

        assert len(msg.parts) == 1
        assert msg.parts[0].part_type == MessagePartType.REASONING

    def test_add_tool_call(self):
        """Test adding tool call part."""
        msg = Message(role="assistant")
        msg.add_tool_call("read_file", "call_123", '{"path": "test.py"}')

        assert len(msg.parts) == 1
        assert msg.parts[0].part_type == MessagePartType.TOOL_CALL
        assert msg.parts[0].tool_name == "read_file"

    def test_get_text_content(self):
        """Test getting text content."""
        msg = Message(role="user")
        msg.add_text("Hello")
        msg.add_text("world")

        content = msg.get_text_content()
        assert "Hello" in content
        assert "world" in content

    def test_to_dict_text_only(self):
        """Test converting to dict with text only."""
        msg = Message.create_text("user", "Hello")

        d = msg.to_dict()

        assert d["role"] == "user"
        assert d["content"] == "Hello"


class TestModelLimits:
    """Test model limits."""

    def test_get_limits_gpt4(self):
        """Test getting limits for GPT-4."""
        limits = ModelLimits.get_limits_sync("gpt-4")

        assert limits["context"] == 8192
        assert limits["output"] == 4096

    def test_get_limits_claude(self):
        """Test getting limits for Claude."""
        limits = ModelLimits.get_limits_sync("claude-3-5-sonnet")

        assert limits["context"] == 200000
        assert limits["output"] == 8192

    def test_get_limits_default(self):
        """Test getting default limits."""
        limits = ModelLimits.get_limits_sync("unknown-model")

        assert limits["context"] == 8000
        assert limits["output"] == 4096

    def test_get_limits_with_provider_prefix(self):
        """Test getting limits with provider prefix (e.g., openai/gpt-4o)."""
        limits = ModelLimits.get_limits_sync("openai/gpt-4o")

        assert limits["context"] == 128000


class TestScrapManager:
    """Test scrap manager."""

    def test_save_and_read(self, tmp_path):
        """Test saving and reading scrap."""
        manager = ScrapManager(str(tmp_path))

        path = manager.save("test content", "txt")

        assert manager.read(path) == "test content"

    def test_save_creates_file(self, tmp_path):
        """Test saving creates file."""
        manager = ScrapManager(str(tmp_path))

        path = manager.save("content", "txt")

        import os

        assert os.path.exists(path)


class TestContextManager:
    """Test context manager."""

    @pytest.fixture
    def manager(self):
        """Create a context manager."""
        return ContextManager(max_tokens=1000)

    def test_set_system_prompt(self, manager):
        """Test setting system prompt."""
        manager.set_system_prompt("You are a helpful assistant.")

        assert len(manager._system_parts) == 1
        assert manager._system_parts[0].content == "You are a helpful assistant."

    def test_add_system_prompt_multiple(self, manager):
        """Test adding multiple system prompts."""
        manager.add_system_prompt("System 1")
        manager.add_system_prompt("System 2")

        assert len(manager._system_parts) == 2

    def test_add_message(self, manager):
        """Test adding messages."""
        manager.add_message("user", "Hello")

        assert len(manager._messages) == 1
        assert manager._messages[0].role == "user"
        assert manager._messages[0].get_text_content() == "Hello"

    def test_add_message_with_dict_content(self, manager):
        """Test adding message with dict content."""
        manager.add_message("assistant", {"type": "text", "text": "Response"})

        assert len(manager._messages) == 1
        assert manager._messages[0].get_text_content() == "Response"

    def test_add_message_with_reasoning(self, manager):
        """Test adding message with reasoning."""
        msg = Message(role="assistant")
        msg.add_reasoning("Thinking...", {"provider": "test"})
        msg.add_text("Final answer")

        manager._messages.append(msg)

        assert len(manager._messages[0].parts) == 2

    def test_add_multiple_messages(self, manager):
        """Test adding multiple messages."""
        manager.add_message("user", "Hello")
        manager.add_message("assistant", "Hi there!")
        manager.add_message("user", "How are you?")

        assert len(manager._messages) == 3

    def test_prepare_messages_sliding_window(self, manager):
        """Test sliding window strategy."""
        manager.set_system_prompt("System")
        for i in range(10):
            manager.add_message("user", f"Message {i}")

        messages = manager.prepare_messages()

        assert len(messages) > 0

    def test_prepare_messages_compaction(self, manager):
        """Test compaction strategy."""
        manager.strategy = ContextStrategy.COMPACTION
        manager.set_system_prompt("System")

        for i in range(5):
            manager.add_message("user", f"Message {i}")

        messages = manager.prepare_messages()

        assert len(messages) > 0

    def test_get_token_usage(self, manager):
        """Test token usage reporting."""
        manager.add_message("user", "Hello world")

        usage = manager.get_token_usage()

        assert "current_tokens" in usage
        assert "max_tokens" in usage
        assert "context_limit" in usage
        assert "output_limit" in usage
        assert "usable_context" in usage

    def test_clear_messages(self, manager):
        """Test clearing messages."""
        manager.add_message("user", "Hello")
        manager.clear()

        assert len(manager._messages) == 0

    def test_truncate_tool_result(self, manager):
        """Test tool result truncation."""
        long_content = "line " * 1000

        truncated = manager.truncate_tool_result(long_content, max_tokens=100)

        assert "truncated" in truncated.lower()

    def test_preserve_system_message(self, manager):
        """Test preserving system message."""
        manager.set_system_prompt("System prompt")
        manager.add_message("user", "Hello")

        messages = manager.prepare_messages()

        assert messages[0]["role"] == "system"
        assert "System prompt" in messages[0]["content"]

    def test_importance_scoring(self, manager):
        """Test importance scoring."""
        manager.add_message("system", "System")
        manager.add_message("user", "User message")
        manager.add_message("tool", "Tool result")

        assert manager._messages[0].importance == 1.0
        assert manager._messages[1].importance == 0.8

    def test_save_to_file(self, manager, tmp_path):
        """Test saving to file."""
        manager.set_system_prompt("System")
        manager.add_message("user", "Hello")

        filepath = tmp_path / "context.json"
        manager.save_to_file(str(filepath))

        assert filepath.exists()

    def test_load_from_file(self, manager, tmp_path):
        """Test loading from file."""
        manager.set_system_prompt("System")
        manager.add_message("user", "Hello")

        filepath = tmp_path / "context.json"
        manager.save_to_file(str(filepath))

        new_manager = ContextManager(max_tokens=1000)
        new_manager.load_from_file(str(filepath))

        assert len(new_manager._messages) == 1
