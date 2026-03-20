"""Tests for CLI commands module."""

from nanocode.cli.commands import (
    COMMANDS,
    get_command_help,
    find_command,
    get_command_names,
)


class TestCommands:
    """Test command definitions."""

    def test_commands_not_empty(self):
        """Test that COMMANDS list is not empty."""
        assert len(COMMANDS) > 0

    def test_all_commands_have_names(self):
        """Test that all commands have at least one name."""
        for cmd in COMMANDS:
            assert len(cmd.names) > 0

    def test_all_commands_have_descriptions(self):
        """Test that all commands have descriptions."""
        for cmd in COMMANDS:
            assert cmd.description


class TestGetCommandHelp:
    """Test get_command_help function."""

    def test_get_command_help_returns_string(self):
        """Test that get_command_help returns a string."""
        result = get_command_help()
        assert isinstance(result, str)

    def test_get_command_help_contains_available_commands(self):
        """Test that help contains 'Available commands'."""
        result = get_command_help()
        assert "Available commands:" in result

    def test_get_command_help_contains_help_command(self):
        """Test that help contains /help."""
        result = get_command_help()
        assert "/help" in result

    def test_get_command_help_contains_exit_command(self):
        """Test that help contains /exit."""
        result = get_command_help()
        assert "/exit" in result

    def test_get_command_help_contains_plan_command(self):
        """Test that help contains /plan with argument."""
        result = get_command_help()
        assert "/plan <task>" in result

    def test_get_command_help_contains_show_thinking(self):
        """Test that help contains /show_thinking."""
        result = get_command_help()
        assert "/show_thinking" in result


class TestFindCommand:
    """Test find_command function."""

    def test_find_help_command(self):
        """Test finding /help command."""
        result = find_command("/help")
        assert result is not None
        assert "help" in result.names

    def test_find_help_command_case_insensitive(self):
        """Test finding /HELP command (case insensitive)."""
        result = find_command("/HELP")
        assert result is not None
        assert "help" in result.names

    def test_find_exit_command(self):
        """Test finding /exit command."""
        result = find_command("/exit")
        assert result is not None

    def test_find_quit_command(self):
        """Test finding /quit command."""
        result = find_command("/quit")
        assert result is not None

    def test_find_q_command(self):
        """Test finding /q command."""
        result = find_command("/q")
        assert result is not None

    def test_find_plan_command(self):
        """Test finding /plan command."""
        result = find_command("/plan")
        assert result is not None

    def test_find_plan_with_args(self):
        """Test finding /plan with arguments - should return None (use startswith in code)."""
        result = find_command("/plan some task")
        assert result is None

    def test_find_resume_command(self):
        """Test finding /resume command."""
        result = find_command("/resume")
        assert result is not None

    def test_find_revert_command(self):
        """Test finding /revert command."""
        result = find_command("/revert")
        assert result is not None

    def test_find_snapshot_command(self):
        """Test finding /snapshot command."""
        result = find_command("/snapshot")
        assert result is not None

    def test_find_snapshots_command(self):
        """Test finding /snapshots command."""
        result = find_command("/snapshots")
        assert result is not None

    def test_find_tools_command(self):
        """Test finding /tools command."""
        result = find_command("/tools")
        assert result is not None

    def test_find_skills_command(self):
        """Test finding /skills command."""
        result = find_command("/skills")
        assert result is not None

    def test_find_checkpoint_command(self):
        """Test finding /checkpoint command."""
        result = find_command("/checkpoint")
        assert result is not None

    def test_find_provider_command(self):
        """Test finding /provider command."""
        result = find_command("/provider")
        assert result is not None

    def test_find_history_command(self):
        """Test finding /history command."""
        result = find_command("/history")
        assert result is not None

    def test_find_clear_command(self):
        """Test finding /clear command."""
        result = find_command("/clear")
        assert result is not None

    def test_find_trace_command(self):
        """Test finding /trace command."""
        result = find_command("/trace")
        assert result is not None

    def test_find_debug_command(self):
        """Test finding /debug command."""
        result = find_command("/debug")
        assert result is not None

    def test_find_compact_command(self):
        """Test finding /compact command."""
        result = find_command("/compact")
        assert result is not None

    def test_find_show_thinking_command(self):
        """Test finding /show_thinking command."""
        result = find_command("/show_thinking")
        assert result is not None

    def test_unknown_command_returns_none(self):
        """Test that unknown command returns None."""
        result = find_command("/unknown_command")
        assert result is None

    def test_non_slash_command_without_slash_finds_command(self):
        """Test that non-slash command can still find command (strips slash)."""
        result = find_command("help")
        assert result is not None
        assert "help" in result.names

    def test_empty_command_returns_none(self):
        """Test that empty command returns None."""
        result = find_command("")
        assert result is None


class TestGetCommandNames:
    """Test get_command_names function."""

    def test_get_command_names_returns_list(self):
        """Test that get_command_names returns a list."""
        result = get_command_names()
        assert isinstance(result, list)

    def test_get_command_names_not_empty(self):
        """Test that command names list is not empty."""
        result = get_command_names()
        assert len(result) > 0

    def test_all_names_start_with_slash(self):
        """Test that all command names start with /."""
        result = get_command_names()
        for name in result:
            assert name.startswith("/")
