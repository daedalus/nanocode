"""Tests for ACP (Agent Client Protocol)."""

import pytest

from agent_smith.acp import (
    ACPError,
    ACPParseError,
    ACPInvalidRequest,
    ACPMethodNotFound,
    ACPInvalidParams,
    ACPInternalError,
    ACPProtocolVersion,
    ACPCapabilities,
    ACPVersion,
    ACPContentBlock,
    ACPMessage,
    ACPToolUse,
    ACPToolResult,
    ACPSessionState,
    ACPSessionManager,
    ACPRequest,
    ACPResponse,
    ACPHandler,
)


class TestACPError:
    """Test ACP error classes."""

    def test_parse_error(self):
        """Test parse error."""
        error = ACPParseError()
        assert error.code == -32700

    def test_invalid_request(self):
        """Test invalid request error."""
        error = ACPInvalidRequest()
        assert error.code == -32600

    def test_method_not_found(self):
        """Test method not found error."""
        error = ACPMethodNotFound()
        assert error.code == -32601

    def test_invalid_params(self):
        """Test invalid params error."""
        error = ACPInvalidParams()
        assert error.code == -32602

    def test_internal_error(self):
        """Test internal error."""
        error = ACPInternalError("test")
        assert error.code == -32603
        assert str(error) == "test"


class TestACPProtocolVersion:
    """Test protocol version."""

    def test_version_values(self):
        """Test version constants."""
        assert ACPProtocolVersion.CURRENT == 1
        assert ACPProtocolVersion.MIN == 1
        assert ACPProtocolVersion.MAX == 1


class TestACPContentBlock:
    """Test content blocks."""

    def test_text_block(self):
        """Test text content block."""
        block = ACPContentBlock(type="text", text="Hello")
        
        assert block.type == "text"
        assert block.text == "Hello"
        
        d = block.to_dict()
        assert d["type"] == "text"
        assert d["text"] == "Hello"


class TestACPMessage:
    """Test ACP messages."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = ACPMessage(role="user")
        msg.content.append(ACPContentBlock(type="text", text="Hello"))
        
        assert msg.role == "user"
        assert len(msg.content) == 1

    def test_message_to_dict(self):
        """Test message to dict."""
        msg = ACPMessage(role="user")
        msg.content.append(ACPContentBlock(type="text", text="Hello"))
        
        d = msg.to_dict()
        
        assert d["role"] == "user"
        assert len(d["content"]) == 1


class TestACPToolUse:
    """Test tool use."""

    def test_tool_use(self):
        """Test tool use creation."""
        tool = ACPToolUse(id="call_123", name="read", input={"path": "test.py"})
        
        assert tool.id == "call_123"
        assert tool.name == "read"
        assert tool.input["path"] == "test.py"


class TestACPToolResult:
    """Test tool result."""

    def test_tool_result(self):
        """Test tool result creation."""
        result = ACPToolResult(
            tool_use_id="call_123",
            content=[ACPContentBlock(type="text", text="file content")],
        )
        
        assert result.tool_use_id == "call_123"
        assert len(result.content) == 1
        assert result.is_error is False


class TestACPSessionState:
    """Test session state."""

    def test_session_state(self):
        """Test session state creation."""
        state = ACPSessionState(id="sess_123", cwd="/home/user")
        
        assert state.id == "sess_123"
        assert state.cwd == "/home/user"


class TestACPSessionManager:
    """Test session manager."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        return ACPSessionManager()

    def test_create_session(self, manager):
        """Test creating a session."""
        session = manager.create(cwd="/home/user")
        
        assert session.id is not None
        assert session.cwd == "/home/user"

    def test_get_session(self, manager):
        """Test getting a session."""
        session = manager.create(cwd="/home/user")
        
        retrieved = manager.get(session.id)
        
        assert retrieved is not None
        assert retrieved.id == session.id

    def test_list_sessions(self, manager):
        """Test listing sessions."""
        manager.create(cwd="/home/user1")
        manager.create(cwd="/home/user2")
        
        sessions = manager.list()
        
        assert len(sessions) == 2

    def test_delete_session(self, manager):
        """Test deleting a session."""
        session = manager.create(cwd="/home/user")
        
        deleted = manager.delete(session.id)
        
        assert deleted is True
        assert manager.get(session.id) is None


class TestACPRequest:
    """Test ACP request."""

    def test_request_creation(self):
        """Test creating a request."""
        request = ACPRequest(id=1, method="initialize", params={"protocolVersion": 1})
        
        assert request.id == 1
        assert request.method == "initialize"
        assert request.params["protocolVersion"] == 1

    def test_request_from_dict(self):
        """Test creating request from dict."""
        data = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        
        request = ACPRequest.from_dict(data)
        
        assert request.id == 1
        assert request.method == "ping"


class TestACPResponse:
    """Test ACP response."""

    def test_response_with_result(self):
        """Test response with result."""
        response = ACPResponse(id=1, result={"pong": True})
        
        d = response.to_dict()
        
        assert d["id"] == 1
        assert d["result"]["pong"] is True

    def test_response_with_error(self):
        """Test response with error."""
        error = ACPMethodNotFound()
        response = ACPResponse(id=1, error=error)
        
        d = response.to_dict()
        
        assert d["id"] == 1
        assert d["error"]["code"] == -32601


class TestACPHandler:
    """Test ACP handler."""

    @pytest.fixture
    def handler(self):
        """Create an ACP handler."""
        return ACPHandler(ACPSessionManager())

    @pytest.mark.asyncio
    async def test_initialize(self, handler):
        """Test initialize request."""
        request = ACPRequest(
            id=1,
            method="initialize",
            params={"protocolVersion": 1}
        )
        
        response = await handler.handle(request)
        
        assert response.result is not None
        assert "protocol_version" in response.result
        assert "capabilities" in response.result

    @pytest.mark.asyncio
    async def test_ping(self, handler):
        """Test ping request."""
        handler._initialized = True
        
        request = ACPRequest(id=1, method="ping")
        
        response = await handler.handle(request)
        
        assert response.result["pong"] is True

    @pytest.mark.asyncio
    async def test_session_new(self, handler):
        """Test session/new request."""
        handler._initialized = True
        
        request = ACPRequest(
            id=1,
            method="session/new",
            params={"cwd": "/home/user"}
        )
        
        response = await handler.handle(request)
        
        assert "session" in response.result
        assert response.result["session"]["cwd"] == "/home/user"

    @pytest.mark.asyncio
    async def test_session_list(self, handler):
        """Test session/list request."""
        handler._initialized = True
        
        manager = handler.session_manager
        manager.create(cwd="/home/user1")
        manager.create(cwd="/home/user2")
        
        request = ACPRequest(id=1, method="session/list")
        
        response = await handler.handle(request)
        
        assert len(response.result["sessions"]) == 2

    @pytest.mark.asyncio
    async def test_session_delete(self, handler):
        """Test session/delete request."""
        handler._initialized = True
        
        session = handler.session_manager.create(cwd="/home/user")
        
        request = ACPRequest(
            id=1,
            method="session/delete",
            params={"sessionId": session.id}
        )
        
        response = await handler.handle(request)
        
        assert response.result["deleted"] is True

    @pytest.mark.asyncio
    async def test_session_prompt(self, handler):
        """Test session/prompt request."""
        handler._initialized = True
        
        session = handler.session_manager.create(cwd="/home/user")
        
        request = ACPRequest(
            id=1,
            method="session/prompt",
            params={
                "sessionId": session.id,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
            }
        )
        
        response = await handler.handle(request)
        
        assert "message" in response.result

    @pytest.mark.asyncio
    async def test_tools_list(self, handler):
        """Test tools/list request."""
        handler._initialized = True
        
        request = ACPRequest(id=1, method="tools/list")
        
        response = await handler.handle(request)
        
        assert "tools" in response.result

    @pytest.mark.asyncio
    async def test_resources_list(self, handler):
        """Test resources/list request."""
        handler._initialized = True
        
        request = ACPRequest(id=1, method="resources/list")
        
        response = await handler.handle(request)
        
        assert "resources" in response.result

    @pytest.mark.asyncio
    async def test_method_not_found(self, handler):
        """Test unknown method."""
        handler._initialized = True
        
        request = ACPRequest(id=1, method="unknown/method")
        
        response = await handler.handle(request)
        
        assert response.error is not None
        assert response.error.code == -32601

    @pytest.mark.asyncio
    async def test_not_initialized(self, handler):
        """Test request before initialization."""
        request = ACPRequest(id=1, method="ping")
        
        response = await handler.handle(request)
        
        assert response.error is not None
