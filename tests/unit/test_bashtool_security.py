"""Tests for BashTool credential isolation and path guards."""

import pytest
from unittest.mock import patch, MagicMock
from nanocode.tools.builtin import BashTool
from nanocode.tools import ToolResult


class TestBashToolCredentialIsolation:
    """Tests for BashTool credential isolation."""

    @pytest.fixture
    def tool(self):
        """Create a BashTool instance."""
        return BashTool()

    def test_safe_env_contains_path(self, tool):
        """Test that safe env includes PATH."""
        env = tool._get_sanitized_env()
        assert "PATH" in env

    def test_safe_env_contains_home(self, tool):
        """Test that safe env includes HOME."""
        env = tool._get_sanitized_env()
        assert "HOME" in env

    def test_safe_env_excludes_api_keys(self, tool):
        """Test that API keys are NOT passed to bash."""
        env = tool._get_sanitized_env()
        assert "OPENAI_API_KEY" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "EXA_API_KEY" not in env
        assert "BRAVE_API_KEY" not in env

    def test_safe_env_excludes_custom_secrets(self, tool):
        """Test that custom secrets are excluded."""
        env = tool._get_sanitized_env()
        # Common secret patterns
        for key in ["API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASS"]:
            assert key not in env or env.get(key) is None

    @pytest.mark.asyncio
    async def test_bash_uses_sanitized_env(self, tool):
        """Test that bash subprocess uses sanitized env."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="ok", stderr="", returncode=0
            )
            await tool.execute("echo hello")
            
            # Check that env was passed and sanitized
            call_kwargs = mock_run.call_args[1]
            assert "env" in call_kwargs
            env = call_kwargs["env"]
            assert "OPENAI_API_KEY" not in env

    @pytest.mark.asyncio
    async def test_bash_default_env_has_no_api_keys(self, tool):
        """Test that default sanitized env has no API keys."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="ok", stderr="", returncode=0
            )
            await tool.execute("echo $OPENAI_API_KEY")
            
            call_kwargs = mock_run.call_args[1]
            env = call_kwargs["env"]
            # The subprocess should not see API keys
            assert env is not None
            # Check that sensitive keys are not present
            sensitive = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "EXA_API_KEY"]
            for key in sensitive:
                assert key not in env


class TestBashToolPathGuards:
    """Tests for bash path guards (virtualized namespace protection)."""

    @pytest.fixture
    def tool(self):
        return BashTool()

    @pytest.mark.asyncio
    async def test_blocks_skills_path_with_slash(self, tool):
        """Test that /skills/ paths are blocked."""
        result = await tool.execute("cat /skills/my-skill/SKILL.md")
        assert result.success is False
        assert "virtualized" in result.error.lower() or "cannot" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocks_skills_path_without_slash(self, tool):
        """Test that skills/ paths are blocked."""
        result = await tool.execute("grep foo skills/**/SKILL.md")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_blocks_memory_path(self, tool):
        """Test that /memory/ paths are blocked."""
        result = await tool.execute("cat /memory/MEMORY.md")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_blocks_dot_nanocode_skills(self, tool):
        """Test that .nanocode/skills paths are blocked."""
        result = await tool.execute("ls .nanocode/skills/")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_allows_normal_commands(self, tool):
        """Test that normal commands are allowed."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="normal output", stderr="", returncode=0
            )
            result = await tool.execute("ls -la /tmp")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_allows_workspace_commands(self, tool):
        """Test that workspace commands are allowed."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="file content", stderr="", returncode=0
            )
            result = await tool.execute("cat README.md")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_blocks_various_virtualized_patterns(self, tool):
        """Test blocking of various virtualized path patterns."""
        blocked_commands = [
            "cat .opencode/skills/foo.md",
            "grep test .claude/skills/*",
            "rm /skills/something",
            "echo hello > /memory/notes.txt",
        ]
        for cmd in blocked_commands:
            result = await tool.execute(cmd)
            assert result.success is False, f"Should block: {cmd}"

    @pytest.mark.asyncio
    async def test_instructs_to_use_tools(self, tool):
        """Test that error message instructs to use read/write tools."""
        result = await tool.execute("cat /skills/foo/SKILL.md")
        assert "read" in result.error.lower() or "write" in result.error.lower() or "tool" in result.error.lower()
