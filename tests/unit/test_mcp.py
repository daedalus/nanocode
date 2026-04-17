"""Tests for MCP (Model Context Protocol) module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanocode.mcp import (
    MCPClient,
    MCPConnection,
    MCPManager,
    MCPProtocol,
    MCPResource,
    MCPSSEConnection,
    MCPStdioConnection,
    MCPTool,
)


class TestMCPProtocol:
    """Tests for MCPProtocol class."""

    def test_create_request(self):
        """Test creating JSON-RPC requests."""
        protocol = MCPProtocol()

        request = protocol.create_request("initialize", {"foo": "bar"})

        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "initialize"
        assert request["params"] == {"foo": "bar"}
        assert "id" in request

    def test_create_request_without_params(self):
        """Test creating request without params."""
        protocol = MCPProtocol()

        request = protocol.create_request("tools/list")

        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "tools/list"
        assert "params" not in request


class TestMCPResource:
    """Tests for MCPResource dataclass."""

    def test_creation(self):
        """Test creating MCPResource."""
        resource = MCPResource(
            uri="file:///test.txt",
            name="test.txt",
            description="A test file",
            mime_type="text/plain",
        )

        assert resource.uri == "file:///test.txt"
        assert resource.name == "test.txt"
        assert resource.description == "A test file"
        assert resource.mime_type == "text/plain"

    def test_default_mime_type(self):
        """Test default mime type."""
        resource = MCPResource(uri="test://test", name="test")

        assert resource.mime_type == "text/plain"


class TestMCPTool:
    """Tests for MCPTool dataclass."""

    def test_creation(self):
        """Test creating MCPTool."""
        tool = MCPTool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
        )

        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.input_schema == {"type": "object", "properties": {}}


class TestMCPStdioConnection:
    """Tests for MCPStdioConnection class."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test stdio connection initialization."""
        connection = MCPStdioConnection(
            command="echo", args=["hello"], env={"TEST": "value"}
        )

        assert connection.command == "echo"
        assert connection.args == ["hello"]
        assert connection.env == {"TEST": "value"}


class TestMCPSSEConnection:
    """Tests for MCPSSEConnection class."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test SSE connection initialization."""
        connection = MCPSSEConnection(
            url="http://localhost:8080/mcp", headers={"Authorization": "Bearer token"}
        )

        assert connection.url == "http://localhost:8080/mcp"
        assert connection.headers == {"Authorization": "Bearer token"}


class TestMCPClient:
    """Tests for MCPClient class."""

    @pytest.mark.asyncio
    async def test_with_mock_connection(self):
        """Test MCPClient with mock connection."""
        mock_connection = MagicMock(spec=MCPConnection)
        mock_connection.initialize = AsyncMock(return_value={"capabilities": {}})
        mock_connection.list_tools = AsyncMock(
            return_value=[MCPTool(name="tool1", description="Tool 1", input_schema={})]
        )
        mock_connection.call_tool = AsyncMock(return_value={"result": "success"})

        client = MCPClient(mock_connection)

        result = await client.initialize()
        assert result == {"capabilities": {}}

        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "tool1"

        tool_result = await client.call_tool("tool1", {"arg": "value"})
        assert tool_result == {"result": "success"}


class TestMCPManager:
    """Tests for MCPManager class."""

    def test_initialization(self):
        """Test MCPManager initialization."""
        manager = MCPManager()

        assert len(manager._clients) == 0
        assert manager.list_servers() == []

    def test_add_stdio_server(self):
        """Test adding stdio server."""
        manager = MCPManager()

        manager.add_server(
            "test-server",
            {
                "type": "stdio",
                "command": "node",
                "args": ["server.js"],
                "env": {"TEST": "value"},
            },
        )

        assert "test-server" in manager._clients

    def test_add_sse_server(self):
        """Test adding SSE server."""
        manager = MCPManager()

        manager.add_server(
            "test-server",
            {
                "type": "sse",
                "url": "http://localhost:8080/mcp",
                "headers": {"Authorization": "Bearer token"},
            },
        )

        assert "test-server" in manager._clients

    def test_add_server_default_type(self):
        """Test adding server with default type (SSE)."""
        manager = MCPManager()

        manager.add_server("test-server", {"url": "http://localhost:8080/mcp"})

        assert "test-server" in manager._clients

    def test_get_client(self):
        """Test getting client by name."""
        manager = MCPManager()

        manager.add_server(
            "test-server", {"type": "sse", "url": "http://localhost:8080/mcp"}
        )

        client = manager.get_client("test-server")
        assert client is not None

        missing = manager.get_client("nonexistent")
        assert missing is None

    def test_list_servers(self):
        """Test listing server names."""
        manager = MCPManager()

        manager.add_server("server1", {"type": "sse", "url": "http://localhost:8080/1"})
        manager.add_server("server2", {"type": "sse", "url": "http://localhost:8080/2"})

        servers = manager.list_servers()

        assert len(servers) == 2
        assert "server1" in servers
        assert "server2" in servers

    @pytest.mark.asyncio
    async def test_connect_all(self):
        """Test connecting to all servers."""
        manager = MCPManager()

        manager.add_server(
            "test-server", {"type": "sse", "url": "http://localhost:8080/mcp"}
        )

        client = manager.get_client("test-server")
        client.initialize = AsyncMock()

        await manager.connect_all()

        client.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_all(self):
        """Test disconnecting all servers."""
        manager = MCPManager()

        manager.add_server(
            "test-server", {"type": "sse", "url": "http://localhost:8080/mcp"}
        )

        client = manager.get_client("test-server")
        client.close = AsyncMock()

        await manager.disconnect_all()

        assert len(manager._clients) == 0
