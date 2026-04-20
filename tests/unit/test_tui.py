"""Tests for TUI functionality."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nanocode.tui.app import OutputArea, NanoCodeTUI


class TestOutputArea:
    """Test OutputArea functionality."""

    def test_output_area_initialization(self):
        """Test OutputArea initialization."""
        area = OutputArea()
        assert area.GRUVBOX is not None
        assert area.GRUVBOX["fg"] == "#ebdbb2"
        assert area.GRUVBOX["green"] == "#98971a"

    def test_gruvbox_colors(self):
        """Test that Gruvbox colors are defined."""
        area = OutputArea()
        expected_colors = [
            "fg", "gray", "red", "green", "yellow", "blue",
            "purple", "aqua", "orange", "red_bright", "green_bright",
            "yellow_bright", "blue_bright", "purple_bright",
            "aqua_bright", "orange_bright"
        ]
        for color in expected_colors:
            assert color in area.GRUVBOX, f"Missing color: {color}"

    def test_render_markdown_method(self):
        """Test _render_markdown method exists."""
        area = OutputArea()
        md = area._render_markdown("# Hello")
        assert md is not None

    def test_add_line_basic(self):
        """Test add_line method exists and accepts text."""
        area = OutputArea()
        area.add_line("Hello world")

    def test_add_line_with_style(self):
        """Test add_line with different styles."""
        area = OutputArea()
        area.add_line("User message", "user")
        area.add_line("Assistant message", "assistant")
        area.add_line("Tool message", "tool")

    def test_add_line_with_markdown(self):
        """Test add_line with markdown content."""
        area = OutputArea()
        area.add_line("# Heading\n\nThis is **bold** text.")
        area.add_line("`inline code` and *italic*")

    def test_add_line_with_code_block(self):
        """Test add_line with code blocks."""
        area = OutputArea()
        area.add_line("```python\nprint('hello')\n```")

    def test_add_empty_line(self):
        """Test add_empty_line method."""
        area = OutputArea()
        area.add_empty_line()

    def test_clear_lines(self):
        """Test clear_lines method."""
        area = OutputArea()
        area.add_line("Test line")
        area.clear_lines()
        assert len(area._lines) == 0


class TestCLICommands:
    """Test CLI_COMMANDS list."""

    def test_cli_commands_defined(self):
        """Test CLI_COMMANDS is defined on NanoCodeTUI."""
        with patch("nanocode.tui.app.NanoCodeTUI.run_async"):
            app = NanoCodeTUI()
        assert hasattr(app, "CLI_COMMANDS")
        assert len(app.CLI_COMMANDS) > 0

    def test_cli_commands_format(self):
        """Test each command is a tuple of (command, description)."""
        with patch("nanocode.tui.app.NanoCodeTUI.run_async"):
            app = NanoCodeTUI()
        for cmd in app.CLI_COMMANDS:
            assert isinstance(cmd, tuple)
            assert len(cmd) == 2
            assert cmd[0].startswith("/")

    def test_known_commands_present(self):
        """Test known commands are present."""
        with patch("nanocode.tui.app.NanoCodeTUI.run_async"):
            app = NanoCodeTUI()
        command_names = [c[0] for c in app.CLI_COMMANDS]
        assert "/help" in command_names
        assert "/exit" in command_names
        assert "/quit" in command_names
        assert "/clear" in command_names
        assert "/help" in command_names
        assert "/tools" in command_names
        assert "/agents" in command_names
        assert "/debug" in command_names


class TestTUICommandHandler:
    """Test TUI command handling."""

    @pytest.fixture
    def app(self):
        """Create a TUI app instance."""
        with patch("nanocode.tui.app.NanoCodeTUI.run_async"):
            app = NanoCodeTUI(agent=None, show_thinking=True)
            app._print_line = MagicMock()
            app._print_error = MagicMock()
            app._print_info = MagicMock()
            app.exit = MagicMock()
            return app

    @pytest.mark.asyncio
    async def test_handle_help_command(self, app):
        """Test /help command."""
        await app._handle_command("/help")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_exit_command(self, app):
        """Test /exit command."""
        await app._handle_command("/exit")
        app.exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_quit_command(self, app):
        """Test /quit command."""
        await app._handle_command("/quit")
        app.exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_q_command(self, app):
        """Test /q command."""
        await app._handle_command("/q")
        app.exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_clear_command(self, app):
        """Test /clear command."""
        app.query_one = MagicMock()
        mock_output = MagicMock()
        app.query_one.return_value = mock_output
        await app._handle_command("/clear")
        mock_output.clear_lines.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_history_command(self, app):
        """Test /history command."""
        await app._handle_command("/history")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_tools_no_agent(self, app):
        """Test /tools with no agent."""
        await app._handle_command("/tools")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_tools_with_agent(self, app):
        """Test /tools with agent."""
        app.agent = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        app.agent.tool_registry.list_tools.return_value = [mock_tool]
        await app._handle_command("/tools")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_agents_no_agent(self, app):
        """Test /agents when agent is None."""
        app.agent = None
        await app._handle_command("/agents")
        # When agent is None, should still print something

    @pytest.mark.asyncio
    async def test_handle_agents_with_registry(self, app):
        """Test /agents with registry."""
        app.agent = MagicMock()
        mock_agent = MagicMock()
        mock_agent.name = "default"
        mock_agent.description = "Default agent"
        app.agent.nanocode_registry.list_primary.return_value = [mock_agent]
        await app._handle_command("/agents")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_debug(self, app):
        """Test /debug command."""
        app.agent = MagicMock()
        app.agent.debug = False
        await app._handle_command("/debug")
        assert app.agent.debug is True

    @pytest.mark.asyncio
    async def test_handle_show_thinking(self, app):
        """Test /show_thinking command."""
        app.show_thinking = False
        await app._handle_command("/show_thinking")
        assert app.show_thinking is True

    @pytest.mark.asyncio
    async def test_handle_unknown_command(self, app):
        """Test unknown command."""
        await app._handle_command("/unknowncmd")
        app._print_error.assert_called()

    @pytest.mark.asyncio
    async def test_handle_provider_command(self, app):
        """Test /provider command."""
        await app._handle_command("/provider")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_plan_command(self, app):
        """Test /plan command."""
        await app._handle_command("/plan")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_snapshot_commands(self, app):
        """Test /snapshot commands."""
        await app._handle_command("/snapshot")
        app._print_line.assert_called()
        await app._handle_command("/snapshots")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_checkpoint_command(self, app):
        """Test /checkpoint command."""
        await app._handle_command("/checkpoint")
        app._print_line.assert_called()

    @pytest.mark.asyncio
    async def test_handle_trace_command(self, app):
        """Test /trace command."""
        app.agent = None
        await app._handle_command("/trace")
        # Should handle gracefully when agent is None

    @pytest.mark.asyncio
    async def test_handle_compact_command(self, app):
        """Test /compact command."""
        app.agent = MagicMock()
        app.agent.context_manager = MagicMock()
        await app._handle_command("/compact")
        app.agent.context_manager._compact.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_agent_switch(self, app):
        """Test /agent command."""
        app.agent = MagicMock()
        app.agent.switch_agent.return_value = True
        await app._handle_command("/agent default")
        app.agent.switch_agent.assert_called_once_with("default")

    @pytest.mark.asyncio
    async def test_handle_resume_command(self, app):
        """Test /resume command."""
        await app._handle_command("/resume session_123")
        app._print_line.assert_called()
