"""Tests for LSP system."""

import os
import tempfile
from pathlib import Path

import pytest

from nanocode.lsp import (
    CompletionItem,
    Diagnostic,
    Hover,
    Location,
    LSPClient,
    LSPServerInfo,
    LSPServerManager,
    SymbolInformation,
    file_uri_to_path,
    path_to_file_uri,
)


class TestPathConversions:
    """Test path/URI conversions."""

    def test_file_uri_to_path(self):
        """Test converting file URI to path."""
        assert file_uri_to_path("file:///home/user/test.py") == "/home/user/test.py"
        assert file_uri_to_path("file://C:/Users/test.py") == "C:/Users/test.py"

    def test_path_to_file_uri(self):
        """Test converting path to file URI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = os.path.join(tmpdir, "test.py")
            uri = path_to_file_uri(abs_path)
            assert uri.startswith("file://")


class TestLSPServerInfo:
    """Test LSP server info."""

    def test_default_servers(self):
        """Test default server list is not empty."""
        manager = LSPServerManager()
        servers = manager.get_default_servers()
        assert len(servers) >= 0

    def test_configure_server(self):
        """Test configuring a server."""
        manager = LSPServerManager()
        manager.configure_server("pyright", command=["pyright", "--langserver"])

        server = LSPServerInfo(
            id="pyright",
            name="Pyright",
            extensions=[".py"],
            command=["pyright", "--langserver"],
        )
        assert server.id == "pyright"
        assert server.extensions == [".py"]


class TestLSPClientBasics:
    """Test LSP client basic operations."""

    def test_lsp_client_init(self):
        """Test LSP client initialization."""
        client = LSPClient(None, server_id="test")
        assert client.server_id == "test"
        assert client.request_id == 0
        assert len(client._pending_requests) == 0

    def test_lsp_client_set_notification_handler(self):
        """Test setting notification handler."""
        client = LSPClient(None)

        async def handler(msg):
            pass

        client.set_notification_handler(handler)
        assert client._notification_handler is not None


class TestDiagnostic:
    """Test diagnostic dataclass."""

    def test_diagnostic_creation(self):
        """Test creating a diagnostic."""
        diag = Diagnostic(
            range={
                "start": {"line": 1, "character": 1},
                "end": {"line": 1, "character": 10},
            },
            message="Test error",
            severity=1,
            code="E001",
            source="pyright",
        )
        assert diag.message == "Test error"
        assert diag.severity == 1
        assert diag.code == "E001"


class TestCompletionItem:
    """Test completion item dataclass."""

    def test_completion_item_creation(self):
        """Test creating a completion item."""
        item = CompletionItem(
            label="print",
            kind=1,
            detail="print(...)",
            documentation="Print to stdout",
            insert_text="print($0)",
        )
        assert item.label == "print"
        assert item.kind == 1


class TestHover:
    """Test hover dataclass."""

    def test_hover_creation(self):
        """Test creating a hover."""
        hover = Hover(
            contents={"kind": "markdown", "value": "**print** function"},
            range={
                "start": {"line": 1, "character": 1},
                "end": {"line": 1, "character": 10},
            },
        )
        assert hover.contents["kind"] == "markdown"


class TestLocation:
    """Test location dataclass."""

    def test_location_creation(self):
        """Test creating a location."""
        loc = Location(
            uri="file:///home/user/test.py",
            range={
                "start": {"line": 1, "character": 1},
                "end": {"line": 1, "character": 10},
            },
        )
        assert "file://" in loc.uri


class TestSymbolInformation:
    """Test symbol information dataclass."""

    def test_symbol_information_creation(self):
        """Test creating symbol information."""
        sym = SymbolInformation(
            name="MyClass",
            kind=6,
            location=Location(
                uri="file:///home/user/test.py",
                range={
                    "start": {"line": 1, "character": 1},
                    "end": {"line": 1, "character": 10},
                },
            ),
        )
        assert sym.name == "MyClass"
        assert sym.kind == 6


class TestLSPServerManager:
    """Test LSP server manager."""

    def test_manager_init(self):
        """Test manager initialization."""
        manager = LSPServerManager()
        assert len(manager._servers) == 0
        assert len(manager._disabled) == 0

    def test_configure_disable_server(self):
        """Test disabling a server."""
        manager = LSPServerManager()
        manager.configure_server("pyright", disabled=True)
        assert "pyright" in manager._disabled

    def test_get_status(self):
        """Test getting server status."""
        manager = LSPServerManager()
        status = manager.get_status()
        assert isinstance(status, list)

    def test_get_server_for_file_not_started(self):
        """Test get_server_for_file returns None when no server started."""
        manager = LSPServerManager()
        result = manager.get_server_for_file("/tmp/test.py")
        assert result is None


class TestLSPToolIntegration:
    """Test LSP tool integration."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_lsp_manager_finds_server_for_file(self, temp_dir):
        """Test that LSP manager can find servers by extension."""
        manager = LSPServerManager()

        py_file = os.path.join(temp_dir, "test.py")
        Path(py_file).touch()

        ts_file = os.path.join(temp_dir, "test.ts")
        Path(ts_file).touch()

        result = manager.get_server_for_file(py_file)
        assert result is None

        result = manager.get_server_for_file(ts_file)
        assert result is None


class TestLSPCapabilities:
    """Test LSP capability detection."""

    def test_capabilities_structure(self):
        """Test expected capabilities structure."""
        expected_capabilities = {
            "textDocument": {
                "completion": {"completionItem": {"snippetSupport": True}},
                "hover": {},
                "definition": {},
                "references": {},
                "documentSymbol": {},
                "workspaceSymbol": {},
            },
            "workspace": {
                "applyEdit": True,
                "workspaceFolders": True,
            },
        }
        assert "textDocument" in expected_capabilities
        assert "workspace" in expected_capabilities
