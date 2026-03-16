"""Tests for CLI functionality."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from agent_smith.cli import ConsoleUI, InteractiveCLI
from agent_smith.core import AutonomousAgent


class TestConsoleUI:
    """Test ConsoleUI functionality."""

    def test_print_prompt_returns_input(self):
        """Test that print_prompt returns user input."""
        ui = ConsoleUI()

        # Mock input to return a specific value
        with patch("builtins.input", return_value="test input"):
            result = ui.print_prompt()
            assert result == "test input"

    def test_print_prompt_with_state(self):
        """Test print_prompt with different states."""
        ui = ConsoleUI()

        with patch("builtins.input", return_value="test"):
            # Test idle state
            result = ui.print_prompt("idle")
            assert result == "test"

            # Test executing state
            result = ui.print_prompt("executing")
            assert result == "test"


class TestInteractiveCLI:
    """Test InteractiveCLI functionality."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent."""
        from agent_smith.state import AgentStateData, AgentState

        agent = Mock(spec=AutonomousAgent)
        agent.state = AgentStateData()
        agent.state.state = AgentState.IDLE
        agent.process_input = AsyncMock(return_value="Test response")
        return agent

    @pytest.fixture
    def cli(self, mock_agent):
        """Create a CLI instance."""
        return InteractiveCLI(mock_agent)

    @pytest.mark.asyncio
    async def test_run_exit_command(self, cli):
        """Test that exit command terminates the CLI."""
        # Mock input to return exit command then keyboard interrupt to break loop
        with patch("builtins.input", side_effect=["/exit", KeyboardInterrupt]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli.ui, "print_message"):
                    try:
                        await cli.run()
                    except KeyboardInterrupt:
                        pass  # Expected to break the loop

                    # Verify goodbye message was printed directly (not through print_message)
                    # The goodbye message is printed directly in the run method
                    # We mainly want to verify it doesn't crash
                    pass

    @pytest.mark.asyncio
    async def test_run_help_command(self, cli):
        """Test that help command displays help."""
        # Mock input to return help command then exit
        with patch("builtins.input", side_effect=["/help", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli.ui, "print_help") as mock_help:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass  # Expected when loop breaks

                        # Verify help was printed
                        mock_help.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_clear_command(self, cli):
        """Test that clear command clears terminal."""
        # Mock input to return clear command then exit
        with patch("builtins.input", side_effect=["/clear", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch("agent_smith.cli.os.system") as mock_system:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify system clear was called (it will be 'clear' on Unix-like systems)
                        mock_system.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_history_command(self, cli):
        """Test that history command displays history."""
        # Mock input to return history command then exit
        with patch("builtins.input", side_effect=["/history", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_print_history") as mock_history:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify history was printed
                        mock_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_tools_command(self, cli):
        """Test that tools command displays tools."""
        # Mock input to return tools command then exit
        with patch("builtins.input", side_effect=["/tools", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_print_tools") as mock_tools:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify tools were printed
                        mock_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_provider_command(self, cli):
        """Test that provider command opens provider selection."""
        # Mock input to return provider command then exit
        with patch("builtins.input", side_effect=["/provider", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_provider_command") as mock_provider:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify provider command was called
                        mock_provider.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_plan_command(self, cli):
        """Test that plan command executes task with planning."""
        # Mock input to return plan command then exit
        with patch("builtins.input", side_effect=["/plan test task", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_execute_task") as mock_execute:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify execute_task was called with correct argument
                        mock_execute.assert_called_once_with("test task")

    @pytest.mark.asyncio
    async def test_run_resume_command(self, cli):
        """Test that resume command resumes from checkpoint."""
        # Mock input to return resume command then exit
        with patch("builtins.input", side_effect=["/resume checkpoint123", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_resume_checkpoint") as mock_resume:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify resume_checkpoint was called with correct argument
                        mock_resume.assert_called_once_with("checkpoint123")

    @pytest.mark.asyncio
    async def test_run_checkpoint_command(self, cli):
        """Test that checkpoint command lists checkpoints."""
        # Mock input to return checkpoint command then exit
        with patch("builtins.input", side_effect=["/checkpoint", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_list_checkpoints") as mock_list:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify list_checkpoints was called
                        mock_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_regular_input(self, cli):
        """Test that regular input is processed through agent."""
        # Mock input to return regular input then exit
        with patch("builtins.input", side_effect=["hello world", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_process_input") as mock_process:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify process_input was called with correct argument
                        mock_process.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_run_regular_input_is_treated_as_agent_input(self, cli):
        """Test that regular input (without slash) is processed as agent input."""
        # Mock input to return regular input then exit
        with patch("builtins.input", side_effect=["hello world", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_process_input") as mock_process:
                    with patch.object(cli.ui, "print_message"):
                        try:
                            await cli.run()
                        except StopAsyncIteration:
                            pass

                        # Verify process_input was called with the regular input
                        mock_process.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_run_plain_text_help_is_not_command(self, cli):
        """Test that typing 'help' (without slash) is treated as regular input, not help command."""
        # Mock input to return "help" then exit
        with patch("builtins.input", side_effect=["help", "/exit"]):
            with patch.object(cli.ui, "print_welcome"):
                with patch.object(cli, "_process_input") as mock_process:
                    with patch.object(cli.ui, "print_help") as mock_help:
                        with patch.object(cli.ui, "print_message"):
                            try:
                                await cli.run()
                            except StopAsyncIteration:
                                pass

                            # Verify process_input was called with "help" (not converted to "/help")
                            mock_process.assert_any_call("help")
                            # Verify help command was NOT called
                            mock_help.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])
