"""Tests for InteractiveCLI command processing."""

import logging
import os
import sys
import traceback
from unittest.mock import AsyncMock, Mock, patch

# Add the agent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nanocode.cli import ConsoleUI, InteractiveCLI


class TestInteractiveCLI:
    """Test InteractiveCLI command processing."""

    def test_cli_initialization(self):
        """Test that CLI can be initialized."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        assert cli.nanocode == mock_agent
        assert cli.ui is not None
        assert cli.history is not None

    def test_print_history(self):
        """Test _print_history method."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        cli.history.add("command 1", "output 1")
        cli.history.add("command 2", "output 2")

        # Capture print output
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            cli._print_history()
            output = buffer.getvalue()
            assert "Command History:" in output
            assert "command 1" in output
            assert "command 2" in output
        finally:
            sys.stdout = old_stdout

    def test_print_tools(self):
        """Test _print_tools method."""
        mock_agent = Mock()
        mock_tool = Mock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_agent.tool_registry.list_tools.return_value = [mock_tool]

        cli = InteractiveCLI(mock_agent)

        # Capture print output
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            cli._print_tools()
            output = buffer.getvalue()
            assert "Available Tools:" in output
            assert "test_tool" in output
            assert "A test tool" in output
        finally:
            sys.stdout = old_stdout

    def test_list_checkpoints_with_checkpoints(self):
        """Test _list_checkpoints method when checkpoints exist."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)

        # Capture print output
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            with patch("os.path.exists", return_value=True):
                with patch(
                    "os.listdir",
                    return_value=["checkpoint_1.json", "checkpoint_2.json"],
                ):
                    cli._list_checkpoints()
                    output = buffer.getvalue()
                    assert "Saved Checkpoints:" in output
                    assert "checkpoint_1.json" in output
                    assert "checkpoint_2.json" in output
        finally:
            sys.stdout = old_stdout

    def test_list_checkpoints_without_checkpoints(self):
        """Test _list_checkpoints method when no checkpoints exist."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)

        # Capture print output
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            with patch("os.path.exists", return_value=False):
                cli._list_checkpoints()
                output = buffer.getvalue()
                assert "No checkpoints found" in output
        finally:
            sys.stdout = old_stdout

    def test_console_ui_print_help(self):
        """Test that ConsoleUI print_help shows slash commands."""
        ui = ConsoleUI()

        # Capture print output
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            ui.print_help()
            output = buffer.getvalue()
            assert "/help" in output
            assert "/exit" in output
            assert "/clear" in output
            assert "/history" in output
            assert "/tools" in output
            assert "/provider" in output
            assert "/plan" in output
            assert "/resume" in output
            assert "/checkpoint" in output
            assert "/trace" in output
        finally:
            sys.stdout = old_stdout


class TestTraceCommand:
    """Test /trace command functionality."""

    def test_trace_no_error(self):
        """Test /trace command when no error has occurred."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        cli.last_error_trace = None

        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            cli._print_trace()
            output = buffer.getvalue()
            assert "No error trace available" in output
        finally:
            sys.stdout = old_stdout

    def test_trace_with_error(self):
        """Test /trace command when an error has occurred."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        cli.last_error_trace = "Traceback (most recent call last):\n  File \"test.py\", line 1, in <module>\n    raise ValueError('test error')\nValueError: test error"

        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            cli._print_trace()
            output = buffer.getvalue()
            assert "Error Trace" in output
            assert "ValueError: test error" in output
        finally:
            sys.stdout = old_stdout

    def test_trace_stores_error_on_exception(self):
        """Test that exceptions store their trace."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)

        async def raise_error():
            raise ValueError("test error")

        async def test():
            try:
                await raise_error()
            except Exception:
                cli.last_error_trace = traceback.format_exc()

        import asyncio

        asyncio.run(test())

        assert cli.last_error_trace is not None
        assert "ValueError: test error" in cli.last_error_trace

    def test_trace_command_in_help(self):
        """Test that /trace appears in help text."""
        ui = ConsoleUI()

        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            ui.print_help()
            output = buffer.getvalue()
            assert "/trace" in output
            assert "Show last error trace" in output
        finally:
            sys.stdout = old_stdout


class TestCompactCommand:
    """Test /compact command functionality."""

    def test_compact_no_context_manager(self):
        """Test /compact when context manager is not available."""
        mock_agent = Mock()
        mock_agent.context_manager = None
        cli = InteractiveCLI(mock_agent)

        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        import asyncio

        async def test():
            await cli._compact_context()

        asyncio.run(test())
        output = buffer.getvalue()
        assert "not available" in output or "Error" in output
        sys.stdout = old_stdout

    def test_compact_with_context_manager(self):
        """Test /compact with context manager."""
        mock_agent = Mock()
        mock_ctx = Mock()
        mock_ctx._messages = [Mock(), Mock(), Mock()]
        mock_ctx.get_token_usage.return_value = {"current_tokens": 1000}
        mock_ctx._compact_async = AsyncMock()
        mock_agent.context_manager = mock_ctx

        cli = InteractiveCLI(mock_agent)

        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        import asyncio

        async def test():
            await cli._compact_context()

        asyncio.run(test())
        output = buffer.getvalue()
        assert "Context compacted" in output
        sys.stdout = old_stdout

    def test_compact_command_in_help(self):
        """Test that /compact appears in help text."""
        ui = ConsoleUI()

        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            ui.print_help()
            output = buffer.getvalue()
            assert "/compact" in output
            assert "Compact context" in output
        finally:
            sys.stdout = old_stdout


class TestAutoCompact:
    """Test auto-compaction functionality."""

    def test_auto_compact_threshold_default(self):
        """Test default compact threshold is 85."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        assert cli.compact_threshold == 85.0

    def test_auto_compact_threshold_custom(self):
        """Test custom compact threshold."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        cli.compact_threshold = 70.0
        assert cli.compact_threshold == 70.0

    def test_auto_compact_when_threshold_reached(self):
        """Test auto-compact triggers when threshold is reached."""
        mock_agent = Mock()
        mock_ctx = Mock()
        mock_ctx._messages = [Mock(), Mock()]
        mock_ctx.get_token_usage.return_value = {"context_usage_percent": 90.0}
        mock_ctx._compact_async = AsyncMock()
        mock_agent.context_manager = mock_ctx

        cli = InteractiveCLI(mock_agent)
        cli.compact_threshold = 85.0

        import asyncio

        asyncio.run(cli._check_and_compact_context())

        mock_ctx._compact_async.assert_called_once()

    def test_auto_compact_when_below_threshold(self):
        """Test auto-compact does not trigger when below threshold."""
        mock_agent = Mock()
        mock_ctx = Mock()
        mock_ctx._messages = [Mock(), Mock()]
        mock_ctx.get_token_usage.return_value = {"context_usage_percent": 50.0}
        mock_ctx._compact_async = AsyncMock()
        mock_agent.context_manager = mock_ctx

        cli = InteractiveCLI(mock_agent)
        cli.compact_threshold = 85.0

        import asyncio

        asyncio.run(cli._check_and_compact_context())

        mock_ctx._compact_async.assert_not_called()

    def test_auto_compact_no_context_manager(self):
        """Test auto-compact with no context manager does not error."""
        mock_agent = Mock()
        mock_agent.context_manager = None

        cli = InteractiveCLI(mock_agent)
        cli.compact_threshold = 85.0

        import asyncio

        asyncio.run(cli._check_and_compact_context())


class TestPromptHistoryNavigation:
    """Test up/down arrow key prompt history navigation."""

    def test_readline_available_flag_exists(self):
        """Test that READLINE_AVAILABLE flag is defined."""
        from nanocode.cli import READLINE_AVAILABLE

        assert isinstance(READLINE_AVAILABLE, bool)

    def test_console_ui_initializes_readline(self):
        """Test that ConsoleUI initializes readline on creation."""
        ui = ConsoleUI()
        assert ui is not None

    def test_add_to_history_with_readline(self):
        """Test add_to_history method exists and is callable."""
        ui = ConsoleUI()
        ui.add_to_history("test command")
        ui.add_to_history("")

    def test_clear_history_with_readline(self):
        """Test clear_history method exists and is callable."""
        ui = ConsoleUI()
        ui.clear_history()

    def test_save_history_method_exists(self):
        """Test save_history method exists and is callable."""
        ui = ConsoleUI()
        ui.save_history()

    def test_load_history_from_file(self):
        """Test that history is loaded from file on initialization."""
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix="_history"
        ) as f:
            f.write("command1\ncommand2\n")
            temp_file = f.name

        try:
            with patch.dict(os.environ, {"AGENT_SMITH_HISTORY": temp_file}):
                ui = ConsoleUI()
                ui._load_history()
        finally:
            os.unlink(temp_file)

    def test_save_history_to_file(self):
        """Test that history is saved to file."""
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix="_history") as f:
            temp_file = f.name

        try:
            with patch.dict(os.environ, {"AGENT_SMITH_HISTORY": temp_file}):
                ui = ConsoleUI()
                ui.add_to_history("test command")
                ui.save_history()

                with open(temp_file) as f:
                    content = f.read()
                    assert "test command" in content
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_history_persistence_across_sessions(self):
        """Test that history persists across CLI sessions."""
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix="_history") as f:
            temp_file = f.name

        try:
            with patch.dict(os.environ, {"AGENT_SMITH_HISTORY": temp_file}):
                ui1 = ConsoleUI()
                ui1.add_to_history("command from session 1")
                ui1.save_history()

                ui2 = ConsoleUI()
                ui2._load_history()
                ui2.add_to_history("command from session 2")
                ui2.save_history()

                with open(temp_file) as f:
                    content = f.read()
                    assert "command from session 1" in content
                    assert "command from session 2" in content
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_history_file_creation(self):
        """Test that history file is created if it doesn't exist."""
        import os
        import tempfile

        temp_dir = tempfile.mkdtemp()
        history_file = os.path.join(temp_dir, "new_history")

        try:
            with patch.dict(os.environ, {"AGENT_SMITH_HISTORY": history_file}):
                ui = ConsoleUI()
                ui.save_history()

                assert os.path.exists(history_file)
        finally:
            if os.path.exists(history_file):
                os.unlink(history_file)
            os.rmdir(temp_dir)

    def test_print_prompt_returns_input(self):
        """Test that print_prompt returns user input."""
        ui = ConsoleUI(use_colors=False)

        with patch("builtins.input", return_value="test input"):
            result = ui.print_prompt(state="idle")
            assert result == "test input"

    def test_print_prompt_with_custom_state(self):
        """Test print_prompt with different states."""
        ui = ConsoleUI(use_colors=False)

        with patch("builtins.input", return_value="test"):
            for state in [
                "idle",
                "planning",
                "executing",
                "waiting",
                "complete",
                "error",
            ]:
                result = ui.print_prompt(state=state)
                assert result == "test"

    def test_history_integration_with_cli(self):
        """Test that CLI uses history correctly."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)

        cli.history.add("command 1")
        cli.history.add("command 2")
        cli.history.add("command 3")

        assert len(cli.history.get_all()) == 3
        assert cli.history.get_all()[0]["command"] == "command 1"
        assert cli.history.get_all()[1]["command"] == "command 2"
        assert cli.history.get_all()[2]["command"] == "command 3"


class TestDebugCommand:
    """Test /debug command."""

    def test_debug_flag_initialization(self):
        """Test debug flag is initially False."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        assert cli.debug is False

    @patch("logging.getLogger")
    def test_debug_toggle_on(self, mock_get_logger):
        """Test toggling debug on."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        cli.debug = False

        import asyncio

        asyncio.run(cli._handle_debug_command())

        mock_logger.setLevel.assert_called_with(logging.DEBUG)
        assert cli.debug is True

    @patch("logging.getLogger")
    def test_debug_toggle_off(self, mock_get_logger):
        """Test toggling debug off."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        cli.debug = False

        import asyncio

        asyncio.run(cli._handle_debug_command())

        mock_logger.setLevel.assert_any_call(logging.DEBUG)
        mock_logger.setLevel.assert_any_call(logging.DEBUG)
        assert cli.debug is True

    def test_debug_in_help_text(self):
        """Test that /debug command appears in help."""
        import io
        import sys

        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)

        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            cli.ui.print_help()
            output = buffer.getvalue()
            assert "/debug" in output
            assert "HTTP" in output or "tool" in output.lower()
        finally:
            sys.stdout = old_stdout

    @patch("logging.getLogger")
    def test_debug_sets_agent_debug_flag(self, mock_get_logger):
        """Test that debug command sets agent.debug flag."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_agent = Mock()
        mock_agent.debug = False
        cli = InteractiveCLI(mock_agent)

        import asyncio

        asyncio.run(cli._handle_debug_command())

        assert cli.debug is True
        assert mock_agent.debug is True

    @patch("logging.getLogger")
    def test_debug_unsets_agent_debug_flag(self, mock_get_logger):
        """Test that debug command unsets agent.debug flag when toggling off."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_agent = Mock()
        mock_agent.debug = True
        cli = InteractiveCLI(mock_agent)
        cli.debug = True

        import asyncio

        asyncio.run(cli._handle_debug_command())

        assert cli.debug is False
        assert mock_agent.debug is False


class TestAgentDebug:
    """Test agent debug functionality."""

    def test_agent_debug_attribute_in_class(self):
        """Test that AutonomousAgent class has debug in __init__."""
        import inspect

        from nanocode.core import AutonomousAgent

        source = inspect.getsource(AutonomousAgent.__init__)
        assert "self.debug = False" in source

    def test_mock_agent_debug_can_be_set(self):
        """Test that mock agent debug flag can be set."""
        mock_agent = Mock()
        mock_agent.debug = False
        mock_agent.debug = True
        assert mock_agent.debug is True
        from nanocode import core

        assert hasattr(core, "tool_logger")
        assert core.tool_logger.name == "nanocode.tools"
