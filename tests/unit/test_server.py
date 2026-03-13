"""Tests for HTTP server."""

import pytest

from agent_smith.server import (
    HTTPError,
    NotFoundError,
    BadRequestError,
    UnauthorizedError,
    ForbiddenError,
    ServerError,
    Session,
    ServerSessionManager,
    ServerRouter,
    Request,
    JSONResponse,
    TextResponse,
    StreamResponse,
    AgentServer,
)


class TestHTTPError:
    """Test HTTP error classes."""

    def test_not_found_error(self):
        """Test NotFoundError."""
        error = NotFoundError("Not found")
        assert error.status_code == 404
        assert str(error) == "Not found"

    def test_bad_request_error(self):
        """Test BadRequestError."""
        error = BadRequestError("Bad request")
        assert error.status_code == 400

    def test_unauthorized_error(self):
        """Test UnauthorizedError."""
        error = UnauthorizedError()
        assert error.status_code == 401

    def test_forbidden_error(self):
        """Test ForbiddenError."""
        error = ForbiddenError()
        assert error.status_code == 403

    def test_server_error(self):
        """Test ServerError."""
        error = ServerError("Server error")
        assert error.status_code == 500


class TestSession:
    """Test session dataclass."""

    def test_create_session(self):
        """Test creating a session."""
        session = Session(id="test-123", cwd="/home/user")
        
        assert session.id == "test-123"
        assert session.cwd == "/home/user"
        assert session.created_at is not None
        assert session.messages == []


class TestServerSessionManager:
    """Test session manager."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        return ServerSessionManager()

    def test_create_session(self, manager):
        """Test creating a session."""
        session = manager.create(cwd="/home/user")
        
        assert session.id is not None
        assert session.id.startswith("session_")
        assert session.cwd == "/home/user"

    def test_get_session(self, manager):
        """Test getting a session."""
        session = manager.create()
        
        retrieved = manager.get(session.id)
        
        assert retrieved is not None
        assert retrieved.id == session.id

    def test_get_nonexistent(self, manager):
        """Test getting nonexistent session."""
        result = manager.get("nonexistent")
        
        assert result is None

    def test_delete_session(self, manager):
        """Test deleting a session."""
        session = manager.create()
        
        deleted = manager.delete(session.id)
        
        assert deleted is True
        assert manager.get(session.id) is None

    def test_list_sessions(self, manager):
        """Test listing sessions."""
        manager.create(cwd="/home/user1")
        manager.create(cwd="/home/user2")
        
        sessions = manager.list()
        
        assert len(sessions) == 2

    def test_add_message(self, manager):
        """Test adding a message to session."""
        session = manager.create()
        
        manager.add_message(session.id, {"role": "user", "content": "Hello"})
        
        retrieved = manager.get(session.id)
        assert len(retrieved.messages) == 1


class TestServerRouter:
    """Test server router."""

    @pytest.fixture
    def router(self):
        """Create a router."""
        return ServerRouter()

    def test_add_route(self, router):
        """Test adding a route."""
        async def handler(req):
            return JSONResponse({"ok": True})
        
        router.add_route("GET", "/health", handler)
        
        handler = router.get_handler("GET", "/health")
        assert handler is not None

    def test_get_handler_not_found(self, router):
        """Test getting nonexistent handler."""
        result = router.get_handler("GET", "/nonexistent")
        
        assert result is None

    def test_list_routes(self, router):
        """Test listing routes."""
        async def handler(req):
            return JSONResponse({"ok": True})
        
        router.add_route("GET", "/health", handler)
        router.add_route("POST", "/data", handler)
        
        routes = router.list_routes()
        
        assert len(routes) == 2
        assert ("GET", "/health") in routes
        assert ("POST", "/data") in routes


class TestRequest:
    """Test request class."""

    def test_request_creation(self):
        """Test creating a request."""
        request = Request(
            method="GET",
            path="/health",
            headers={"host": "localhost:8080"},
            query_params={"key": "value"},
        )
        
        assert request.method == "GET"
        assert request.path == "/health"
        assert request.get_header("host") == "localhost:8080"
        assert request.query_params["key"] == "value"


class TestResponses:
    """Test response classes."""

    def test_json_response(self):
        """Test JSON response."""
        response = JSONResponse({"key": "value"})
        
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    def test_text_response(self):
        """Test text response."""
        response = TextResponse("Hello world")
        
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert response.body == "Hello world"

    def test_stream_response(self):
        """Test stream response."""
        response = StreamResponse()
        
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]


class TestAgentServer:
    """Test agent server."""

    @pytest.fixture
    def server(self):
        """Create a server."""
        return AgentServer(host="0.0.0.0", port=8080)

    def test_server_creation(self, server):
        """Test creating a server."""
        assert server.host == "0.0.0.0"
        assert server.port == 8080
        assert server.session_manager is not None
        assert server.router is not None

    def test_routes_registered(self, server):
        """Test routes are registered."""
        routes = server.router.list_routes()
        
        assert ("GET", "/health") in routes
        assert ("GET", "/ready") in routes
        assert ("GET", "/sessions") in routes
        assert ("POST", "/sessions") in routes

    def test_check_auth_no_auth_configured(self, server):
        """Test auth check when no auth configured."""
        request = Request("GET", "/health")
        
        result = server._check_auth(request)
        
        assert result is True

    def test_check_auth_not_required(self, server):
        """Test auth not required for health endpoint."""
        request = Request("GET", "/health")
        
        result = server._check_auth(request)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_health_endpoint(self, server):
        """Test health endpoint."""
        request = Request("GET", "/health")
        
        response = await server._health(request)
        
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ready_endpoint(self, server):
        """Test ready endpoint."""
        request = Request("GET", "/ready")
        
        response = await server._ready(request)
        
        assert response.status_code == 200
        assert "session_count" in response.body

    @pytest.mark.asyncio
    async def test_list_sessions(self, server):
        """Test listing sessions."""
        server.session_manager.create()
        
        request = Request("GET", "/sessions")
        
        response = await server._list_sessions(request)
        
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_session(self, server):
        """Test creating a session."""
        request = Request(
            "POST",
            "/sessions",
            body={"cwd": "/home/user"},
        )
        
        response = await server._create_session(request)
        
        assert response.status_code == 201
        assert "session" in response.body

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, server):
        """Test getting nonexistent session."""
        request = Request("GET", "/sessions/nonexistent")
        
        with pytest.raises(NotFoundError):
            await server._get_session(request)

    @pytest.mark.asyncio
    async def test_openapi_endpoint(self, server):
        """Test OpenAPI endpoint."""
        request = Request("GET", "/openapi.json")
        
        response = await server._openapi(request)
        
        assert response.status_code == 200
        assert "openapi" in response.body

    @pytest.mark.asyncio
    async def test_handle_request_not_found(self, server):
        """Test handling unknown route."""
        response = await server.handle_request("GET", "/unknown", {})
        
        assert response.status_code == 404
