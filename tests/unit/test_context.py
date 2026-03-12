"""Tests for context manager."""

import pytest
from agent.context import ContextManager, ContextStrategy, TokenCounter, MessageToken


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


class TestContextManager:
    """Test context manager."""

    @pytest.fixture
    def manager(self):
        """Create a context manager."""
        return ContextManager(max_tokens=1000)

    def test_set_system_prompt(self, manager):
        """Test setting system prompt."""
        manager.set_system_prompt("You are a helpful assistant.")
        
        assert manager._system_message is not None
        assert manager._system_message.content == "You are a helpful assistant."
        assert manager._system_message.role == "system"

    def test_add_message(self, manager):
        """Test adding messages."""
        manager.add_message("user", "Hello")
        
        assert len(manager._messages) == 1
        assert manager._messages[0].role == "user"
        assert manager._messages[0].content == "Hello"

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

    def test_get_token_usage(self, manager):
        """Test token usage reporting."""
        manager.add_message("user", "Hello world")
        
        usage = manager.get_token_usage()
        
        assert "current_tokens" in usage
        assert "max_tokens" in usage
        assert usage["max_tokens"] == 1000
        assert usage["current_tokens"] > 0

    def test_clear_messages(self, manager):
        """Test clearing messages."""
        manager.add_message("user", "Hello")
        assert len(manager._messages) == 1
        
        manager.clear()
        assert len(manager._messages) == 0

    def test_truncate_tool_result(self, manager):
        """Test tool result truncation."""
        long_result = "line " * 1000
        
        truncated = manager.truncate_tool_result(long_result, max_tokens=50)
        
        assert TokenCounter.count_tokens(truncated) <= 60

    def test_preserve_system_message(self, manager):
        """Test system message is preserved."""
        manager.set_system_prompt("Important system prompt")
        manager.add_message("user", "Hello")
        
        messages = manager.prepare_messages()
        
        assert any(m.get("role") == "system" for m in messages)

    def test_importance_scoring(self, manager):
        """Test importance scoring by role."""
        manager.add_message("system", "System prompt")
        manager.add_message("user", "User message")
        manager.add_message("assistant", "Assistant response")
        manager.add_message("tool", "Tool result")
        
        assert manager._messages[0].importance == 1.0
        assert manager._messages[1].importance == 0.8
        assert manager._messages[2].importance == 0.6
        assert manager._messages[3].importance == 0.4
