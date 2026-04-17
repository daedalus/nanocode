"""Tests for CLI functionality."""

import os
import sys

import pytest

# Add the agent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nanocode.cli import CommandHistory, ConsoleUI, PromptHandler


class TestConsoleUI:
    """Test ConsoleUI functionality."""

    def test_console_ui_initialization(self):
        """Test ConsoleUI initialization."""
        ui = ConsoleUI()
        assert ui.use_colors is not None  # Should be boolean based on terminal
        assert ui.prompts is not None

    def test_console_ui_with_colors_disabled(self):
        """Test ConsoleUI with colors disabled."""
        ui = ConsoleUI(use_colors=False)
        assert ui.use_colors is False

    def test_color_method_no_colors(self):
        """Test color method when colors are disabled."""
        ui = ConsoleUI(use_colors=False)
        result = ui.color("red", "test text")
        assert result == "test text"

    def test_print_welcome(self, capsys):
        """Test print welcome message."""
        ui = ConsoleUI()
        ui.print_welcome()
        captured = capsys.readouterr()
        assert "Autonomous Agent - Ready" in captured.out

    def test_print_help(self, capsys):
        """Test print help message."""
        ui = ConsoleUI()
        ui.print_help()
        captured = capsys.readouterr()
        assert "Commands" in captured.out
        assert "/help" in captured.out

    def test_print_message(self, capsys):
        """Test print message."""
        ui = ConsoleUI()
        ui.print_message("user", "Hello world")
        captured = capsys.readouterr()
        assert "[USER]" in captured.out
        assert "Hello world" in captured.out

    def test_print_tool_call(self, capsys):
        """Test print tool call."""
        ui = ConsoleUI()
        ui.print_tool_call("bash", {"command": "ls"})
        captured = capsys.readouterr()
        assert "Calling tool:" in captured.out
        assert "bash" in captured.out
        assert "command:" in captured.out

    def test_print_tool_result(self, capsys):
        """Test print tool result."""
        ui = ConsoleUI()
        ui.print_tool_result("test result", success=True)
        captured = capsys.readouterr()
        assert "✓ Result:" in captured.out
        assert "test result" in captured.out

        ui.print_tool_result("error result", success=False)
        captured = capsys.readouterr()
        assert "✗ Result:" in captured.out
        assert "error result" in captured.out

    def test_print_error(self, capsys):
        """Test print error."""
        ui = ConsoleUI()
        ui.print_error("Test error")
        captured = capsys.readouterr()
        assert "✗ Error:" in captured.out
        assert "Test error" in captured.out

    def test_print_info(self, capsys):
        """Test print info."""
        ui = ConsoleUI()
        ui.print_info("Test info")
        captured = capsys.readouterr()
        assert "ℹ" in captured.out
        assert "Test info" in captured.out

    def test_print_success(self, capsys):
        """Test print success."""
        ui = ConsoleUI()
        ui.print_success("Test success")
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "Test success" in captured.out

    def test_print_plan(self, capsys):
        """Test print plan."""
        ui = ConsoleUI()
        plan = {
            "steps": [
                {"description": "Step 1", "status": "pending"},
                {"description": "Step 2", "status": "complete"},
                {"description": "Step 3", "status": "failed"},
            ]
        }
        ui.print_plan(plan)
        captured = capsys.readouterr()
        assert "Execution Plan:" in captured.out
        assert "Step 1" in captured.out
        assert "Step 2" in captured.out
        assert "Step 3" in captured.out


class TestPromptHandler:
    """Test PromptHandler functionality."""

    @pytest.mark.asyncio
    async def test_confirm_yes(self, monkeypatch):
        """Test confirm with yes response."""
        handler = PromptHandler()
        monkeypatch.setattr("builtins.input", lambda _: "y")
        result = await handler.confirm("Continue?")
        assert result is True

    @pytest.mark.asyncio
    async def test_confirm_no(self, monkeypatch):
        """Test confirm with no response."""
        handler = PromptHandler()
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = await handler.confirm("Continue?")
        assert result is False

    @pytest.mark.asyncio
    async def test_confirm_default_no(self, monkeypatch):
        """Test confirm with empty response defaults to no."""
        handler = PromptHandler()
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = await handler.confirm("Continue?")
        assert result is False

    @pytest.mark.asyncio
    async def test_password(self, monkeypatch):
        """Test password input."""
        handler = PromptHandler()
        monkeypatch.setattr("builtins.input", lambda _: "secret123")
        result = await handler.password("Enter password")
        assert result == "secret123"

    @pytest.mark.asyncio
    async def test_password_validation(self, monkeypatch):
        """Test password validation."""
        handler = PromptHandler()
        # First call fails validation, second passes
        inputs = iter(["short", "longenough"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        def validate(password):
            if len(password) < 8:
                return "Password too short"
            return None

        result = await handler.password("Enter password", validate)
        assert result == "longenough"

    @pytest.mark.asyncio
    async def test_autocomplete(self, monkeypatch):
        """Test autocomplete selection."""
        handler = PromptHandler()
        options = {
            "message": "Choose option",
            "options": [
                {"label": "Option 1", "value": "value1"},
                {"label": "Option 2", "value": "value2"},
            ],
        }
        monkeypatch.setattr("builtins.input", lambda _: "2")
        result = await handler.autocomplete(options)
        assert result == "value2"

    @pytest.mark.asyncio
    async def test_autocomplete_invalid(self, monkeypatch):
        """Test autocomplete with invalid selection."""
        handler = PromptHandler()
        options = {
            "message": "Choose option",
            "options": [
                {"label": "Option 1", "value": "value1"},
                {"label": "Option 2", "value": "value2"},
            ],
        }
        monkeypatch.setattr("builtins.input", lambda _: "5")  # Invalid
        result = await handler.autocomplete(options)
        assert result is None

    @pytest.mark.asyncio
    async def test_autocomplete_cancel(self, monkeypatch):
        """Test autocomplete cancellation."""
        handler = PromptHandler()
        options = {
            "message": "Choose option",
            "options": [
                {"label": "Option 1", "value": "value1"},
            ],
        }
        monkeypatch.setattr("builtins.input", lambda _: "")  # Empty input
        result = await handler.autocomplete(options)
        assert result is None

    def test_is_cancel(self):
        """Test isCancel method."""
        handler = PromptHandler()
        assert handler.isCancel(None) is True
        assert handler.isCancel("") is False
        assert handler.isCancel("test") is False


class TestCommandHistory:
    """Test CommandHistory functionality."""

    def test_command_history_initialization(self):
        """Test CommandHistory initialization."""
        history = CommandHistory()
        assert len(history.history) == 0
        assert history.max_size == 100

    def test_command_history_custom_size(self):
        """Test CommandHistory with custom size."""
        history = CommandHistory(max_size=10)
        assert history.max_size == 10

    def test_add_command(self):
        """Test adding command to history."""
        history = CommandHistory()
        history.add("test command", "test output")
        assert len(history.history) == 1
        assert history.history[0]["command"] == "test command"
        assert history.history[0]["output"] == "test output"

    def test_add_command_without_output(self):
        """Test adding command without output."""
        history = CommandHistory()
        history.add("test command")
        assert len(history.history) == 1
        assert history.history[0]["command"] == "test command"
        assert history.history[0]["output"] is None

    def test_history_limit(self):
        """Test history size limit."""
        history = CommandHistory(max_size=2)
        history.add("command 1")
        history.add("command 2")
        history.add("command 3")  # Should remove first command

        assert len(history.history) == 2
        assert history.history[0]["command"] == "command 2"
        assert history.history[1]["command"] == "command 3"

    def test_get_all(self):
        """Test getting all history."""
        history = CommandHistory()
        history.add("command 1", "output 1")
        history.add("command 2", "output 2")

        all_history = history.get_all()
        assert len(all_history) == 2
        assert all_history[0]["command"] == "command 1"
        assert all_history[1]["command"] == "command 2"

    def test_search(self):
        """Test searching history."""
        history = CommandHistory()
        history.add("help me", "output 1")
        history.add("run command", "output 2")
        history.add("help again", "output 3")

        results = history.search("help")
        assert len(results) == 2
        assert results[0]["command"] == "help me"
        assert results[1]["command"] == "help again"

    def test_clear(self):
        """Test clearing history."""
        history = CommandHistory()
        history.add("command 1")
        history.add("command 2")
        assert len(history.history) == 2

        history.clear()
        assert len(history.history) == 0
