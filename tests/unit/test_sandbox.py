"""Tests for sandbox module - lifecycle management for agent sandboxes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSandbox:
    """Test Sandbox class."""

    def test_sandbox_creation(self):
        """Test Sandbox initialization."""
        from nanocode.sandbox.base import Sandbox

        provider = MagicMock()
        sandbox = Sandbox(sandbox_id="sb_1", provider=provider)
        assert sandbox.id == "sb_1"
        assert sandbox.status == "running"

    @pytest.mark.asyncio
    async def test_execute(self):
        """Test Sandbox.execute delegates to provider."""
        from nanocode.sandbox.base import Sandbox

        provider = MagicMock()
        provider.execute = AsyncMock(return_value={"success": True, "stdout": "output"})
        sandbox = Sandbox(sandbox_id="sb_1", provider=provider)

        result = await sandbox.execute("ls", cwd="/tmp")
        provider.execute.assert_called_once_with("sb_1", "ls", cwd="/tmp", env=None)
        assert result == {"success": True, "stdout": "output"}

    @pytest.mark.asyncio
    async def test_read_file(self):
        """Test Sandbox.read_file delegates to provider."""
        from nanocode.sandbox.base import Sandbox

        provider = MagicMock()
        provider.read_file = AsyncMock(return_value="file content")
        sandbox = Sandbox(sandbox_id="sb_1", provider=provider)

        result = await sandbox.read_file("/path/to/file")
        provider.read_file.assert_called_once_with("sb_1", "/path/to/file")
        assert result == "file content"

    @pytest.mark.asyncio
    async def test_write_file(self):
        """Test Sandbox.write_file delegates to provider."""
        from nanocode.sandbox.base import Sandbox

        provider = MagicMock()
        provider.write_file = AsyncMock(return_value=True)
        sandbox = Sandbox(sandbox_id="sb_1", provider=provider)

        result = await sandbox.write_file("/path/to/file", "content")
        provider.write_file.assert_called_once_with("sb_1", "/path/to/file", "content")
        assert result is True

    @pytest.mark.asyncio
    async def test_suspend(self):
        """Test Sandbox.suspend changes status."""
        from nanocode.sandbox.base import Sandbox

        provider = MagicMock()
        provider.suspend = AsyncMock()
        sandbox = Sandbox(sandbox_id="sb_1", provider=provider)

        await sandbox.suspend()
        provider.suspend.assert_called_once_with("sb_1")
        assert sandbox.status == "suspended"

    @pytest.mark.asyncio
    async def test_resume(self):
        """Test Sandbox.resume changes status."""
        from nanocode.sandbox.base import Sandbox

        provider = MagicMock()
        provider.resume = AsyncMock()
        sandbox = Sandbox(sandbox_id="sb_1", provider=provider)
        sandbox.status = "suspended"

        await sandbox.resume()
        provider.resume.assert_called_once_with("sb_1")
        assert sandbox.status == "running"

    @pytest.mark.asyncio
    async def test_destroy(self):
        """Test Sandbox.destroy changes status."""
        from nanocode.sandbox.base import Sandbox

        provider = MagicMock()
        provider.destroy = AsyncMock()
        sandbox = Sandbox(sandbox_id="sb_1", provider=provider)

        await sandbox.destroy()
        provider.destroy.assert_called_once_with("sb_1")
        assert sandbox.status == "stopped"


class TestSandboxProvider:
    """Test SandboxProvider abstract base class."""

    def test_is_abstract(self):
        """Test SandboxProvider cannot be instantiated directly."""
        from nanocode.sandbox.base import SandboxProvider

        with pytest.raises(TypeError):
            SandboxProvider()

    def test_can_subclass(self):
        """Test SandboxProvider can be subclassed."""
        from nanocode.sandbox.base import SandboxProvider

        class TestProvider(SandboxProvider):
            async def create(self, session_id, **kwargs): pass
            async def suspend(self, sandbox_id): pass
            async def resume(self, sandbox_id): pass
            async def destroy(self, sandbox_id): pass
            async def execute(self, sandbox_id, command, cwd=None, env=None): pass
            async def read_file(self, sandbox_id, path): pass
            async def write_file(self, sandbox_id, path, content): pass
            async def list_sandboxes(self): pass

        provider = TestProvider()
        assert isinstance(provider, SandboxProvider)


class TestSandboxModule:
    """Test sandbox module functions."""

    def test_get_local_provider(self):
        """Test get_sandbox_provider returns local provider."""
        from nanocode.sandbox import get_sandbox_provider
        from nanocode.sandbox.local import LocalSandboxProvider

        provider = get_sandbox_provider("local")
        assert isinstance(provider, LocalSandboxProvider)

    def test_get_unknown_provider(self):
        """Test get_sandbox_provider raises for unknown type."""
        from nanocode.sandbox import get_sandbox_provider

        with pytest.raises(ValueError, match="Unknown sandbox provider"):
            get_sandbox_provider("unknown")

    def test_register_provider(self):
        """Test register_sandbox_provider adds new provider."""
        from nanocode.sandbox import register_sandbox_provider, get_sandbox_provider
        from nanocode.sandbox.base import SandboxProvider

        class MockProvider(SandboxProvider):
            def __init__(self, config=None):
                self.config = config
            async def create(self, session_id, **kwargs): pass
            async def suspend(self, sandbox_id): pass
            async def resume(self, sandbox_id): pass
            async def destroy(self, sandbox_id): pass
            async def execute(self, sandbox_id, command, cwd=None, env=None): pass
            async def read_file(self, sandbox_id, path): pass
            async def write_file(self, sandbox_id, path, content): pass
            async def list_sandboxes(self): pass

        register_sandbox_provider("mock", MockProvider)
        provider = get_sandbox_provider("mock")
        assert isinstance(provider, MockProvider)

    def test_docker_provider_optional(self):
        """Test Docker provider import is optional."""
        import importlib
        import sys

        with patch.dict("sys.modules", {"nanocode.sandbox.docker": None}):
            with patch("importlib.import_module", side_effect=ImportError):
                import nanocode.sandbox
                importlib.reload(nanocode.sandbox)
                assert "docker" not in nanocode.sandbox._PROVIDERS
                assert "local" in nanocode.sandbox._PROVIDERS

        importlib.reload(nanocode.sandbox)
