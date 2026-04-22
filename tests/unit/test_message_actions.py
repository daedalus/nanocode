"""Tests for message actions."""

import pytest

from nanocode.message_actions import (
    MessageAction,
    MessageActionManager,
    create_message_manager,
)


class TestMessageAction:
    """Test MessageAction."""

    def test_creation(self):
        """Test creating message action."""
        action = MessageAction(
            action_type="revert",
            message_index=5,
            details="Test",
        )

        assert action.action_type == "revert"
        assert action.message_index == 5


class TestMessageActionManager:
    """Test MessageActionManager."""

    def test_create_empty(self):
        """Test creating empty manager."""
        manager = MessageActionManager()
        assert len(manager._messages) == 0

    def test_create_with_messages(self):
        """Test creating with initial messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        manager = MessageActionManager(messages)

        assert len(manager._messages) == 2

    def test_get_message_positive(self):
        """Test getting message by positive index."""
        messages = [{"role": "a", "content": "1"}, {"role": "b", "content": "2"}]
        manager = MessageActionManager(messages)

        msg = manager.get_message(0)
        assert msg["content"] == "1"

    def test_get_message_negative(self):
        """Test getting message by negative index."""
        messages = [{"role": "a", "content": "1"}, {"role": "b", "content": "2"}]
        manager = MessageActionManager(messages)

        msg = manager.get_message(-1)
        assert msg["content"] == "2"

    def test_get_message_out_of_bounds(self):
        """Test getting message out of bounds."""
        manager = MessageActionManager([{"role": "a", "content": "1"}])

        msg = manager.get_message(5)
        assert msg is None

    def test_revert_messages(self):
        """Test reverting messages."""
        messages = [
            {"role": "a", "content": "1"},
            {"role": "b", "content": "2"},
            {"role": "c", "content": "3"},
        ]
        manager = MessageActionManager(messages)

        removed = manager.revert(2)

        assert len(manager._messages) == 1
        assert len(removed) == 2

    def test_revert_all(self):
        """Test reverting all messages."""
        messages = [{"role": "a", "content": "1"}]
        manager = MessageActionManager(messages)

        removed = manager.revert(10)

        assert len(manager._messages) == 0

    def test_copy_message(self):
        """Test copying a message."""
        messages = [{"role": "a", "content": "Test content"}]
        manager = MessageActionManager(messages)

        copied = manager.copy_message(0)

        assert copied is not None
        assert copied["content"] == "Test content"
        assert len(manager._messages) == 1

    def test_copy_message_invalid(self):
        """Test copying invalid message."""
        manager = MessageActionManager()

        copied = manager.copy_message(0)

        assert copied is None

    def test_fork(self):
        """Test forking messages."""
        messages = [
            {"role": "a", "content": "1"},
            {"role": "b", "content": "2"},
        ]
        manager = MessageActionManager(messages)

        forked, fork_id = manager.fork()

        assert len(forked) == 2
        assert fork_id is not None

    def test_fork_with_count(self):
        """Test forking with specific count."""
        messages = [
            {"role": "a", "content": "1"},
            {"role": "b", "content": "2"},
            {"role": "c", "content": "3"},
        ]
        manager = MessageActionManager(messages)

        forked, fork_id = manager.fork(message_count=2)

        assert len(forked) == 2

    def test_save_and_load(self, tmp_path):
        """Test saving and loading fork."""
        messages = [{"role": "a", "content": "Test"}]
        manager = MessageActionManager(messages)

        was_saved = manager.save_as("test_fork")
        assert was_saved is True

        new_manager = MessageActionManager()
        was_loaded = new_manager.load_fork("test_fork")
        assert was_loaded is True
        assert len(new_manager._messages) == 1

    def test_list_forks_empty(self):
        """Test listing forks when none exist."""
        import shutil
        from pathlib import Path

        storage_dir = Path.home() / ".local" / "share" / "nanocode" / "storage" / "forks"
        if storage_dir.exists():
            shutil.rmtree(storage_dir)

        manager = MessageActionManager()

        forks = manager.list_forks()

        assert forks == []

    def test_get_action_history(self):
        """Test getting action history."""
        messages = [{"role": "a", "content": "1"}, {"role": "b", "content": "2"}]
        manager = MessageActionManager(messages)

        manager.revert(1)
        manager.copy_message(0)
        history = manager.get_action_history()

        assert len(history) == 2

    def test_get_stats(self):
        """Test getting stats."""
        messages = [{"role": "a", "content": "1"}]
        manager = MessageActionManager(messages)

        stats = manager.get_stats()

        assert stats["message_count"] == 1
        assert "forks_available" in stats


class TestCreateMessageManager:
    """Test factory function."""

    def test_create(self):
        """Test creating manager."""
        manager = create_message_manager()

        assert isinstance(manager, MessageActionManager)