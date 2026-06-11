"""Tests for the Context Reconstruction system."""

import os
import tempfile
import pytest
from nanocode.context import (
    CheckpointManager,
    ContextReconstructor,
    Checkpoint,
    CheckpointMessage,
    get_checkpoint_manager,
    get_context_reconstructor,
    reset_context_reconstruction,
)


class TestCheckpointMessage:
    """Tests for CheckpointMessage dataclass."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = CheckpointMessage(
            role="user",
            content="Hello",
            timestamp=1234567890.0,
        )
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tokens == 0
        assert msg.importance == 0.5

    def test_message_with_metadata(self):
        """Test message with metadata."""
        msg = CheckpointMessage(
            role="assistant",
            content="Response",
            timestamp=1234567890.0,
            tokens=10,
            importance=0.8,
            metadata={"tool": "bash"},
        )
        assert msg.tokens == 10
        assert msg.importance == 0.8
        assert msg.metadata["tool"] == "bash"


class TestCheckpoint:
    """Tests for Checkpoint dataclass."""

    def test_checkpoint_creation(self):
        """Test creating a checkpoint."""
        cp = Checkpoint(session_id="session-1")
        assert cp.session_id == "session-1"
        assert len(cp.messages) == 0
        assert cp.token_count == 0

    def test_checkpoint_to_dict(self):
        """Test converting checkpoint to dict."""
        cp = Checkpoint(session_id="session-1")
        cp.messages.append(
            CheckpointMessage(role="user", content="Hello", timestamp=1234567890.0)
        )
        d = cp.to_dict()
        assert d["session_id"] == "session-1"
        assert len(d["messages"]) == 1

    def test_checkpoint_from_dict(self):
        """Test creating checkpoint from dict."""
        data = {
            "session_id": "session-1",
            "messages": [
                {"role": "user", "content": "Hello", "timestamp": 1234567890.0}
            ],
            "summary": "Test session",
            "token_count": 100,
        }
        cp = Checkpoint.from_dict(data)
        assert cp.session_id == "session-1"
        assert len(cp.messages) == 1
        assert cp.summary == "Test session"


class TestCheckpointManager:
    """Tests for CheckpointManager."""

    def test_init(self, tmp_path):
        """Test initialization."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        assert manager.storage_dir == str(tmp_path)

    def test_save_and_load_checkpoint(self, tmp_path):
        """Test saving and loading a checkpoint."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        cp = Checkpoint(session_id="test-session")
        cp.messages.append(
            CheckpointMessage(role="user", content="Hello", timestamp=1234567890.0)
        )

        # Save
        result = manager.save_checkpoint(cp)
        assert result is True

        # Load
        loaded = manager.load_checkpoint("test-session")
        assert loaded is not None
        assert loaded.session_id == "test-session"
        assert len(loaded.messages) == 1

    def test_load_nonexistent_checkpoint(self, tmp_path):
        """Test loading a nonexistent checkpoint."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        loaded = manager.load_checkpoint("nonexistent")
        assert loaded is None

    def test_delete_checkpoint(self, tmp_path):
        """Test deleting a checkpoint."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        cp = Checkpoint(session_id="test-session")
        manager.save_checkpoint(cp)

        result = manager.delete_checkpoint("test-session")
        assert result is True
        assert manager.load_checkpoint("test-session") is None

    def test_list_checkpoints(self, tmp_path):
        """Test listing checkpoints."""
        manager = CheckpointManager(storage_dir=str(tmp_path))

        # Create some checkpoints
        for i in range(3):
            cp = Checkpoint(session_id=f"session-{i}")
            manager.save_checkpoint(cp)

        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 3


class TestContextReconstructor:
    """Tests for ContextReconstructor."""

    def test_init(self, tmp_path):
        """Test initialization."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=8000,
        )
        assert reconstructor.max_context_tokens == 8000

    def test_should_reconstruct(self, tmp_path):
        """Test reconstruction threshold check."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=10000,
        )

        # Below threshold
        assert not reconstructor.should_reconstruct(8000, threshold=0.85)

        # Above threshold
        assert reconstructor.should_reconstruct(9000, threshold=0.85)

    def test_create_checkpoint_from_messages(self, tmp_path):
        """Test creating checkpoint from messages."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(checkpoint_manager=manager)

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        checkpoint = reconstructor.create_checkpoint_from_messages(
            "test-session", messages
        )

        assert checkpoint.session_id == "test-session"
        assert len(checkpoint.messages) == 3
        assert checkpoint.token_count > 0

    def test_reconstruct_context_with_checkpoint(self, tmp_path):
        """Test context reconstruction with existing checkpoint."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(
            checkpoint_manager=manager,
            max_context_tokens=1000,
        )

        # Create and save a checkpoint
        old_messages = [
            {"role": "user", "content": "Old message 1"},
            {"role": "assistant", "content": "Old response 1"},
        ]
        checkpoint = reconstructor.create_checkpoint_from_messages(
            "test-session", old_messages, summary="Previous conversation"
        )
        manager.save_checkpoint(checkpoint)

        # Current messages
        current_messages = [
            {"role": "user", "content": "New message"},
            {"role": "assistant", "content": "New response"},
        ]

        # Reconstruct
        reconstructed = reconstructor.reconstruct_context(
            "test-session", current_messages
        )

        # Should have summary + current messages
        assert len(reconstructed) >= 2
        assert reconstructed[-1]["content"] == "New response"

    def test_reconstruct_context_without_checkpoint(self, tmp_path):
        """Test context reconstruction without existing checkpoint."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(checkpoint_manager=manager)

        current_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        reconstructed = reconstructor.reconstruct_context(
            "nonexistent", current_messages
        )

        # Should return current messages
        assert reconstructed == current_messages

    def test_calculate_importance(self, tmp_path):
        """Test importance calculation."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(checkpoint_manager=manager)

        assert reconstructor._calculate_importance("system", "test") == 1.0
        assert reconstructor._calculate_importance("user", "test") >= 0.7
        assert reconstructor._calculate_importance("assistant", "test") >= 0.6
        assert reconstructor._calculate_importance("tool", "test") >= 0.4

    def test_estimate_tokens(self, tmp_path):
        """Test token estimation."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(checkpoint_manager=manager)

        assert reconstructor._estimate_tokens("") == 0
        assert reconstructor._estimate_tokens("Hello") > 0
        assert reconstructor._estimate_tokens("Hello world test") > reconstructor._estimate_tokens("Hello")

    def test_save_session_checkpoint(self, tmp_path):
        """Test saving a session checkpoint."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(checkpoint_manager=manager)

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        result = reconstructor.save_session_checkpoint(
            "test-session",
            messages,
            summary="Test session",
            task_progress={"T1": "in_progress"},
        )

        assert result is True

        # Verify saved
        checkpoint = manager.load_checkpoint("test-session")
        assert checkpoint is not None
        assert checkpoint.summary == "Test session"
        assert checkpoint.task_progress["T1"] == "in_progress"

    def test_get_stats(self, tmp_path):
        """Test getting statistics."""
        manager = CheckpointManager(storage_dir=str(tmp_path))
        reconstructor = ContextReconstructor(checkpoint_manager=manager)

        stats = reconstructor.get_stats()
        assert "total_checkpoints" in stats
        assert "max_context_tokens" in stats


class TestGlobalInstances:
    """Tests for global instances."""

    def test_get_checkpoint_manager_singleton(self):
        """Test global manager is singleton."""
        reset_context_reconstruction()
        m1 = get_checkpoint_manager()
        m2 = get_checkpoint_manager()
        assert m1 is m2

    def test_get_context_reconstructor_singleton(self):
        """Test global reconstructor is singleton."""
        reset_context_reconstruction()
        r1 = get_context_reconstructor()
        r2 = get_context_reconstructor()
        assert r1 is r2

    def test_reset_context_reconstruction(self):
        """Test resetting global instances."""
        m1 = get_checkpoint_manager()
        r1 = get_context_reconstructor()
        reset_context_reconstruction()
        m2 = get_checkpoint_manager()
        r2 = get_context_reconstructor()
        assert m1 is not m2
        assert r1 is not r2
