"""Tests for doom loop detection."""

from nanocode.doom_loop import (
    DoomLoopDetection,
    DoomLoopHandler,
    ToolCall,
    create_doom_loop_handler,
)


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_tool_call_creation(self):
        """Test creating a ToolCall."""
        call = ToolCall(
            tool_name="read", arguments={"path": "test.py"}, call_id="call-1"
        )
        assert call.tool_name == "read"
        assert call.arguments == {"path": "test.py"}
        assert call.call_id == "call-1"


class TestDoomLoopDetection:
    """Tests for DoomLoopDetection."""

    def test_detection_threshold_default(self):
        """Test default threshold is 3."""
        detection = DoomLoopDetection()
        assert detection.threshold == 3

    def test_detection_custom_threshold(self):
        """Test custom threshold."""
        detection = DoomLoopDetection(threshold=5)
        assert detection.threshold == 5

    def test_first_call_no_doom_loop(self):
        """Test that first call doesn't trigger doom loop."""
        detection = DoomLoopDetection()
        assert detection.record_call("read", {"path": "test.py"}) is False

    def test_same_tool_different_args_no_doom_loop(self):
        """Test that same tool with different args doesn't trigger doom loop."""
        detection = DoomLoopDetection()
        detection.record_call("read", {"path": "test.py"})
        detection.record_call("read", {"path": "other.py"})
        detection.record_call("read", {"path": "another.py"})

        assert detection.get_loop_info() is None

    def test_same_tool_same_args_triggers_doom_loop(self):
        """Test that same tool with same args triggers doom loop at threshold."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("read", {"path": "test.py"})
        assert detection.get_loop_info() is None

        detection.record_call("read", {"path": "test.py"})
        assert detection.get_loop_info() is None

        detection.record_call("read", {"path": "test.py"})

        info = detection.get_loop_info()
        assert info is not None
        assert info["tool"] == "read"
        assert info["arguments"] == {"path": "test.py"}
        assert info["count"] == 3

    def test_different_tools_no_doom_loop(self):
        """Test that different tools don't trigger doom loop."""
        detection = DoomLoopDetection()
        detection.record_call("read", {"path": "test.py"})
        detection.record_call("write", {"path": "test.py"})
        detection.record_call("edit", {"path": "test.py"})

        assert detection.get_loop_info() is None

    def test_clear_tool(self):
        """Test clearing calls for a specific tool."""
        detection = DoomLoopDetection()
        detection.record_call("read", {"path": "test.py"})
        detection.record_call("read", {"path": "test.py"})

        detection.clear("read")

        assert detection.get_loop_info() is None

    def test_clear_all(self):
        """Test clearing all calls."""
        detection = DoomLoopDetection()
        detection.record_call("read", {"path": "test.py"})
        detection.record_call("write", {"path": "test.py"})

        detection.clear()

        assert detection.get_loop_info() is None

    def test_should_prompt(self):
        """Test should_prompt method."""
        detection = DoomLoopDetection(threshold=3)

        assert detection.should_prompt("read") is False

        detection.record_call("read", {"path": "test.py"})
        assert detection.should_prompt("read") is False

        detection.record_call("read", {"path": "test.py"})
        assert detection.should_prompt("read") is False

        detection.record_call("read", {"path": "test.py"})
        assert detection.should_prompt("read") is True

    def test_doom_loop_with_dict_order_independence(self):
        """Test doom loop detection is independent of dict key order."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("read", {"path": "test.py", "limit": 100})
        detection.record_call("read", {"limit": 100, "path": "test.py"})
        detection.record_call("read", {"path": "test.py", "limit": 100})

        assert detection.get_loop_info() is not None


class TestDoomLoopHandler:
    """Tests for DoomLoopHandler."""

    def test_handler_creation(self):
        """Test creating a handler."""
        handler = DoomLoopHandler()
        assert handler.enabled is True
        assert handler.detection.threshold == 3

    def test_handler_disabled(self):
        """Test handler when disabled."""
        handler = DoomLoopHandler()
        handler.enabled = False

        result = handler.check_tool_call("read", {"path": "test.py"})
        assert result is False

    def test_check_tool_call(self):
        """Test checking tool calls."""
        handler = DoomLoopHandler()

        result = handler.check_tool_call("read", {"path": "test.py"})
        assert result is False

        result = handler.check_tool_call("read", {"path": "test.py"})
        assert result is False

        result = handler.check_tool_call("read", {"path": "test.py"})
        assert result is True

    def test_get_loop_warning(self):
        """Test getting loop warning."""
        handler = DoomLoopHandler()

        handler.check_tool_call("read", {"path": "test.py"})
        handler.check_tool_call("read", {"path": "test.py"})
        handler.check_tool_call("read", {"path": "test.py"})

        warning = handler.get_loop_warning()
        assert warning is not None
        assert "read" in warning
        assert "test.py" in warning
        assert "3 times" in warning

    def test_should_ask_permission(self):
        """Test checking if should ask permission."""
        handler = DoomLoopHandler()

        assert handler.should_ask_permission("read") is False

        handler.check_tool_call("read", {"path": "test.py"})
        assert handler.should_ask_permission("read") is False

        handler.check_tool_call("read", {"path": "test.py"})
        assert handler.should_ask_permission("read") is False

        handler.check_tool_call("read", {"path": "test.py"})
        assert handler.should_ask_permission("read") is True

    def test_reset(self):
        """Test resetting the handler."""
        handler = DoomLoopHandler()

        handler.check_tool_call("read", {"path": "test.py"})
        handler.check_tool_call("read", {"path": "test.py"})
        handler.check_tool_call("read", {"path": "test.py"})

        handler.reset("read")

        assert handler.should_ask_permission("read") is False


class TestCreateDoomLoopHandler:
    """Tests for create_doom_loop_handler factory."""

    def test_create_with_default_threshold(self):
        """Test creating handler with default threshold."""
        handler = create_doom_loop_handler()
        assert handler.detection.threshold == 3

    def test_create_with_custom_threshold(self):
        """Test creating handler with custom threshold."""
        handler = create_doom_loop_handler(threshold=5)
        assert handler.detection.threshold == 5


class TestDoomLoopIntegration:
    """Integration tests for doom loop detection."""

    def test_multiple_tools_tracked_separately(self):
        """Test that multiple tools are tracked separately."""
        detection = DoomLoopDetection(threshold=3)

        detection.record_call("read", {"path": "a.py"})
        detection.record_call("write", {"path": "b.py"})
        detection.record_call("read", {"path": "a.py"})
        detection.record_call("write", {"path": "b.py"})
        detection.record_call("read", {"path": "a.py"})

        info = detection.get_loop_info()
        assert info is not None
        assert info["tool"] == "read"

    def test_threshold_higher_no_detection(self):
        """Test with higher threshold."""
        detection = DoomLoopDetection(threshold=5)

        for _ in range(4):
            detection.record_call("read", {"path": "test.py"})

        assert detection.get_loop_info() is None

        detection.record_call("read", {"path": "test.py"})

        assert detection.get_loop_info() is not None
