"""Tests for doom loop detection."""

import pytest
from nanocode.doom_loop import DoomLoopDetection, DoomLoopHandler, ToolCall, create_doom_loop_handler


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_tool_call_creation(self):
        """Test creating a ToolCall."""
        call = ToolCall(tool_name="bash", arguments={"command": "ls"}, call_id="123")
        assert call.tool_name == "bash"
        assert call.arguments == {"command": "ls"}
        assert call.call_id == "123"

    def test_tool_call_with_call_id(self):
        """Test ToolCall with call_id."""
        call = ToolCall(tool_name="read", arguments={"filePath": "/test.py"}, call_id="123")
        assert call.call_id == "123"


class TestDoomLoopDetection:
    """Tests for DoomLoopDetection."""

    def test_initial_state(self):
        """Test initial detection state."""
        detection = DoomLoopDetection(threshold=3)
        assert detection.threshold == 3
        assert detection._recent_calls == {}
        assert detection._exploration_warning_shown is False

    def test_record_call_no_repeat(self):
        """Test recording calls without triggering doom loop."""
        detection = DoomLoopDetection(threshold=3)

        # Single call should not trigger
        result = detection.record_call("bash", {"command": "ls"})
        assert result is False

    def test_record_call_different_tools(self):
        """Test different tools don't trigger doom loop."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("bash", {"command": "ls"})
        detection.record_call("glob", {"pattern": "*.py"})
        detection.record_call("read", {"filePath": "test.py"})

        # Different tools should not trigger
        assert detection._is_doom_loop(detection._recent_calls.get("bash", [])) is False

    def test_record_call_same_args_triggers(self):
        """Test same arguments trigger doom loop."""
        detection = DoomLoopDetection(threshold=3)

        # Record same call 3 times with same args
        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "ls"})

        # Should trigger doom loop
        assert detection._is_doom_loop(detection._recent_calls["bash"]) is True

    def test_record_call_different_args_no_trigger(self):
        """Test different arguments don't trigger doom loop."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "cat file.py"})
        detection.record_call("bash", {"command": "grep pattern file.py"})

        # Different args should not trigger
        assert detection._is_doom_loop(detection._recent_calls["bash"]) is False

    def test_record_call_empty_args_no_trigger(self):
        """Test empty/default arguments don't trigger doom loop."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("bash", {})
        detection.record_call("bash", {})
        detection.record_call("bash", {})

        # Empty args should not trigger
        assert detection._is_doom_loop(detection._recent_calls["bash"]) is False

    def test_record_call_with_none_values(self):
        """Test arguments with None values don't trigger doom loop."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("bash", {"command": None})
        detection.record_call("bash", {"command": None})
        detection.record_call("bash", {"command": None})

        assert detection._is_doom_loop(detection._recent_calls["bash"]) is False

    def test_exploration_loop_detection(self):
        """Test exploration loop detection."""
        detection = DoomLoopDetection(threshold=3)

        # Multiple ls/glob calls without reads
        detection.record_call("ls", {"command": "."})
        detection.record_call("glob", {"pattern": "*.py"})
        detection.record_call("ls", {"command": "."})

        assert detection._is_exploration_loop() is True

    def test_exploration_loop_resets_with_read(self):
        """Test exploration loop is reset when read is used."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("ls", {"command": "."})
        detection.record_call("glob", {"pattern": "*.py"})
        detection.record_call("read", {"filePath": "test.py"})

        # Read breaks the exploration loop
        assert detection._is_exploration_loop() is False

    def test_get_loop_info_repeat_type(self):
        """Test get_loop_info for repeat type."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "ls"})

        info = detection.get_loop_info()
        assert info is not None
        assert info["type"] == "repeat"
        assert info["tool"] == "bash"
        assert info["count"] == 3

    def test_get_loop_info_exploration_type(self):
        """Test get_loop_info for exploration type."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("ls", {"command": "."})
        detection.record_call("glob", {"pattern": "*.py"})
        detection.record_call("ls", {"command": "."})

        info = detection.get_loop_info()
        assert info is not None
        assert info["type"] == "exploration"

    def test_get_loop_info_none(self):
        """Test get_loop_info returns None when no loop."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("read", {"filePath": "test.py"})
        detection.record_call("grep", {"pattern": "bug", "path": "test.py"})

        info = detection.get_loop_info()
        assert info is None

    def test_clear_specific_tool(self):
        """Test clearing specific tool calls."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "ls"})
        detection.clear("bash")

        assert detection._recent_calls.get("bash", []) == []

    def test_clear_all(self):
        """Test clearing all tool calls."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("bash", {"command": "ls"})
        detection.record_call("glob", {"pattern": "*.py"})
        detection.clear()

        assert detection._recent_calls == {}
        assert detection._all_recent_calls == []

    def test_should_prompt_for_permission(self):
        """Test should_prompt returns correct value."""
        detection = DoomLoopDetection(threshold=3)

        # Add calls that will trigger doom loop
        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "ls"})
        detection.record_call("bash", {"command": "ls"})

        assert detection.should_prompt("bash") is True
        assert detection.should_prompt("glob") is True  # exploration loop

    def test_should_not_prompt_when_disabled(self):
        """Test should_prompt returns False when no loop."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("read", {"filePath": "test.py"})

        assert detection.should_prompt("read") is False


class TestDoomLoopHandler:
    """Tests for DoomLoopHandler."""

    def test_handler_creation(self):
        """Test creating handler with threshold."""
        handler = DoomLoopHandler(threshold=5)
        assert handler.detection.threshold == 5
        assert handler.enabled is True

    def test_check_tool_call(self):
        """Test checking tool call."""
        handler = DoomLoopHandler(threshold=3)

        result = handler.check_tool_call("bash", {"command": "ls"})
        assert result is False

        # Multiple same calls trigger
        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})

        result = handler.check_tool_call("bash", {"command": "ls"})
        assert result is True

    def test_check_tool_call_disabled(self):
        """Test disabled handler always returns False."""
        handler = DoomLoopHandler(threshold=3)
        handler.enabled = False

        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})

        result = handler.check_tool_call("bash", {"command": "ls"})
        assert result is False

    def test_get_loop_warning_none(self):
        """Test get_loop_warning returns None when no loop."""
        handler = DoomLoopHandler(threshold=3)

        handler.check_tool_call("read", {"filePath": "test.py"})

        warning = handler.get_loop_warning()
        assert warning is None

    def test_get_loop_warning_repeat(self):
        """Test get_loop_warning for repeat type."""
        handler = DoomLoopHandler(threshold=3)

        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})

        warning = handler.get_loop_warning()
        assert warning is not None
        assert "bash" in warning
        assert "doom loop" in warning.lower()

    def test_get_loop_warning_exploration(self):
        """Test get_loop_warning for exploration type."""
        handler = DoomLoopHandler(threshold=3)

        handler.check_tool_call("ls", {"command": "."})
        handler.check_tool_call("glob", {"pattern": "*.py"})
        handler.check_tool_call("ls", {"command": "."})

        warning = handler.get_loop_warning()
        assert warning is not None
        assert "exploration" in warning.lower()

    def test_should_ask_permission(self):
        """Test should_ask_permission."""
        handler = DoomLoopHandler(threshold=3)

        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})

        assert handler.should_ask_permission("bash") is True

    def test_reset(self):
        """Test resetting handler."""
        handler = DoomLoopHandler(threshold=3)

        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})
        handler.check_tool_call("bash", {"command": "ls"})

        handler.reset()

        assert handler.detection._recent_calls == {}


class TestCreateDoomLoopHandler:
    """Tests for create_doom_loop_handler factory."""

    def test_create_with_default_threshold(self):
        """Test creating with default threshold."""
        handler = create_doom_loop_handler()
        assert handler.detection.threshold == 3

    def test_create_with_custom_threshold(self):
        """Test creating with custom threshold."""
        handler = create_doom_loop_handler(threshold=5)
        assert handler.detection.threshold == 5