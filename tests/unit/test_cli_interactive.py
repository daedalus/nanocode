"""Tests for InteractiveCLI command processing."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import sys
import os
import traceback

# Add the agent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_smith.cli import InteractiveCLI, ConsoleUI


class TestInteractiveCLI:
    """Test InteractiveCLI command processing."""

    def test_cli_initialization(self):
        """Test that CLI can be initialized."""
        mock_agent = Mock()
        cli = InteractiveCLI(mock_agent)
        assert cli.agent == mock_agent
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
                with patch("os.listdir", return_value=["checkpoint_1.json", "checkpoint_2.json"]):
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
