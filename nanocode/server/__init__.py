"""HTTP Server for remote agent operation.

This module provides an HTTP server for remote agent operation,
similar to opencode's server implementation.

Supports:
- Session management via REST API
- Agent execution with streaming responses
- Basic authentication
- CORS support
- mDNS integration for discovery
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from nanocode.llm import Message as LLMMessage
from nanocode.llm.base import Message
from nanocode.llm.events import (
    EventType,
    FinishStepEvent,
    ReasoningDeltaEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)


class HTTPError(Exception):
    """Base HTTP error."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class NotFoundError(HTTPError):
    """404 Not Found."""

    def __init__(self, message: str = "Not found"):
        super().__init__(message, 404)


class BadRequestError(HTTPError):
    """400 Bad Request."""

    def __init__(self, message: str = "Bad request"):
        super().__init__(message, 400)


class UnauthorizedError(HTTPError):
    """401 Unauthorized."""

    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, 401)


class ForbiddenError(HTTPError):
    """403 Forbidden."""

    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, 403)


class ServerError(HTTPError):
    """500 Internal Server Error."""

    def __init__(self, message: str = "Internal server error"):
        super().__init__(message, 500)


def _openai_message_to_internal(msg: dict) -> Message:
    """Convert an OpenAI-format message dict to a Message object."""
    role = msg.get("role", "user")
    content = msg.get("content", "")
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        content = "".join(text_parts)
    return Message(role=role, content=str(content))


def _format_openai_chunk(
    model: str,
    content_delta: str = "",
    finish_reason: str | None = None,
) -> str:
    """Format an SSE data chunk for OpenAI-compatible streaming."""
    choice: dict = {"delta": {}, "index": 0}
    if content_delta:
        choice["delta"]["content"] = content_delta
    if finish_reason:
        choice["finish_reason"] = finish_reason
    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [choice],
    }
    return f"data: {json.dumps(chunk)}\n\n"


@dataclass
class Session:
    """A server session."""

    id: str
    cwd: str
    created_at: datetime = field(default_factory=datetime.now)
    messages: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    pending_input: str | None = None


@dataclass
class AgentRequest:
    """Request to run agent."""

    messages: list[dict]
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = True


@dataclass
class AgentResponse:
    """Response from agent."""

    message: dict
    session_id: str
    done: bool
    error: str | None = None


class RouteHandler:
    """Base class for route handlers."""

    async def handle(self, request: "Request") -> "Response":
        """Handle the request."""
        raise NotImplementedError


class Request:
    """HTTP request."""

    def __init__(
        self,
        method: str,
        path: str,
        headers: dict = None,
        body: Any = None,
        query_params: dict = None,
    ):
        self.method = method
        self.path = path
        self.headers = headers or {}
        self.body = body
        self.query_params = query_params or {}

    def get_header(self, name: str) -> str | None:
        """Get header value."""
        return self.headers.get(name.lower())


class Response:
    """HTTP response."""

    def __init__(
        self,
        status_code: int = 200,
        body: Any = None,
        headers: dict = None,
    ):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {"content-type": "application/json"}

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "status_code": self.status_code,
            "body": self.body,
            "headers": self.headers,
        }


class JSONResponse(Response):
    """JSON response."""

    def __init__(self, body: Any, status_code: int = 200, **kwargs):
        super().__init__(
            status_code=status_code,
            body=json.dumps(body) if body is not None else None,
            headers={"content-type": "application/json", **kwargs},
        )


class TextResponse(Response):
    """Plain text response."""

    def __init__(self, body: str, status_code: int = 200, **kwargs):
        super().__init__(
            status_code=status_code,
            body=body,
            headers={"content-type": "text/plain", **kwargs},
        )


class StreamResponse(Response):
    """Streaming response with SSE support."""

    def __init__(self, status_code: int = 200, event_stream=None, **kwargs):
        super().__init__(
            status_code=status_code,
            body=None,
            headers={
                "content-type": "text/event-stream",
                "cache-control": "no-cache",
                "connection": "keep-alive",
                **kwargs,
            },
        )
        self.event_stream = event_stream


class ServerSessionManager:
    """Manages server sessions."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, cwd: str = ".") -> Session:
        """Create a new session."""
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        session = Session(id=session_id, cwd=cwd)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """Get a session."""
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def list(self) -> list[Session]:
        """List all sessions."""
        return list(self._sessions.values())

    def add_message(self, session_id: str, message: dict):
        """Add a message to session."""
        session = self._sessions.get(session_id)
        if session:
            session.messages.append(message)


class ServerRouter:
    """Simple HTTP router."""

    def __init__(self):
        self._routes: dict[tuple[str, str], Callable] = {}

    def add_route(self, method: str, path: str, handler: Callable):
        """Add a route."""
        self._routes[(method.upper(), path)] = handler

    def get_handler(self, method: str, path: str) -> Callable | None:
        """Get handler for method and path."""
        return self._routes.get((method.upper(), path))

    def list_routes(self) -> list[tuple[str, str]]:
        """List all routes."""
        return list(self._routes.keys())


class AgentServer:
    """HTTP server for remote agent operation."""

    def __init__(
        self,
        host: str = "127.0.0.1",  # localhost only by default for security
        port: int = 8080,
        agent=None,
        auth_username: str = None,
        auth_password: str = None,
    ):
        self.host = host
        self.port = port
        self.nanocode = agent
        self.auth_username = auth_username
        self.auth_password = auth_password

        self.session_manager = ServerSessionManager()
        self.router = ServerRouter()
        self._server = None
        self._running = False

        self._setup_routes()

    def _setup_routes(self):
        """Setup routes."""
        self.router.add_route("GET", "/health", self._health)
        self.router.add_route("GET", "/ready", self._ready)
        self.router.add_route("GET", "/app", self._app)

        self.router.add_route("GET", "/sessions", self._list_sessions)
        self.router.add_route("POST", "/sessions", self._create_session)
        self.router.add_route("GET", "/sessions/{id}", self._get_session)
        self.router.add_route("DELETE", "/sessions/{id}", self._delete_session)

        self.router.add_route("POST", "/sessions/{id}/prompt", self._session_prompt)
        self.router.add_route(
            "POST", "/sessions/{id}/prompt/stream", self._session_prompt_stream
        )

        self.router.add_route("POST", "/tui/append-prompt", self._append_prompt)

        self.router.add_route("GET", "/tools", self._list_tools)
        self.router.add_route("GET", "/config", self._get_config)
        self.router.add_route("GET", "/stats", self._get_stats)

        self.router.add_route("GET", "/openapi.json", self._openapi)

        self.router.add_route("GET", "/v1/models", self._handle_v1_models)
        self.router.add_route("POST", "/v1/chat/completions", self._handle_v1_chat_completions)

    def _get_model_name(self) -> str:
        if self.nanocode and hasattr(self.nanocode, "llm") and self.nanocode.llm:
            return getattr(self.nanocode.llm, "model", "nanocode")
        return "nanocode"

    async def _handle_v1_models(self, request: Request) -> Response:
        """GET /v1/models — return available models."""
        self._require_auth(request)
        model = self._get_model_name()
        return JSONResponse({
            "object": "list",
            "data": [{
                "id": model,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "nanocode",
            }],
        })

    async def _handle_v1_chat_completions(self, request: Request) -> Response:
        """POST /v1/chat/completions — OpenAI Chat Completions format."""
        self._require_auth(request)
        body = request.body or {}
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        model = body.get("model", self._get_model_name())

        if not messages:
            raise BadRequestError("messages required")

        internal_messages = [_openai_message_to_internal(m) for m in messages]

        if not self.nanocode or not hasattr(self.nanocode, "llm") or not self.nanocode.llm:
            return JSONResponse({"error": "No LLM configured"}, status_code=500)

        llm = self.nanocode.llm

        if stream:
            return await self._stream_chat_completions(llm, internal_messages, model)

        try:
            response = await llm.chat(internal_messages)
            text = getattr(response, "content", "") or ""
            finish = getattr(response, "finish_reason", "stop") or "stop"
            return JSONResponse({
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": finish,
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            })
        except Exception as e:
            logger.exception("Chat completion failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    async def _stream_chat_completions(self, llm, messages: list[Message], model: str) -> StreamResponse:
        """Stream chat completions in OpenAI SSE format."""
        async def event_stream():
            try:
                async for event in llm.chat_stream(messages):
                    if isinstance(event, TextDeltaEvent):
                        yield _format_openai_chunk(model, content_delta=event.text)
                    elif isinstance(event, FinishStepEvent):
                        yield _format_openai_chunk(model, finish_reason="stop")
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.exception("Stream error")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                yield "data: [DONE]\n\n"

        return StreamResponse(event_stream=event_stream())

    async def _health(self, request: Request) -> Response:
        """Health check."""
        return JSONResponse({"status": "ok"})

    async def _ready(self, request: Request) -> Response:
        """Readiness check."""
        return JSONResponse(
            {
                "status": "ready",
                "session_count": len(self.session_manager.list()),
            }
        )

    async def _app(self, request: Request) -> Response:
        """App endpoint for VSCode extension connectivity check."""
        return JSONResponse(
            {
                "status": "ok",
                "name": "nanocode",
                "version": "0.1.0",
            }
        )

    async def _append_prompt(self, request: Request) -> Response:
        """Append text to the current session prompt."""
        try:
            body = request.body or {}
            text = body.get("text", "")
            session_id = body.get("session_id")

            if not session_id:
                sessions = self.session_manager.list()
                if not sessions:
                    return JSONResponse({"error": "No active session"}, status_code=400)
                session = sessions[0]
                session_id = session.id

            session = self.session_manager.get(session_id)
            if not session:
                return JSONResponse({"error": "Session not found"}, status_code=404)

            session.pending_input = text

            return JSONResponse({"status": "ok", "session_id": session_id})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    def _check_auth(self, request: Request) -> bool:
        """Check authentication."""
        if not self.auth_username or not self.auth_password:
            return True

        auth_header = request.get_header("authorization")
        if not auth_header:
            return False

        if not auth_header.startswith("Basic "):
            return False

        import base64

        try:
            credentials = base64.b64decode(auth_header[6:]).decode()
            username, password = credentials.split(":", 1)
            return username == self.auth_username and password == self.auth_password
        except Exception:
            return False

    def _require_auth(self, request: Request):
        """Require authentication or raise error."""
        if not self._check_auth(request):
            raise UnauthorizedError("Authentication required")

    async def _list_sessions(self, request: Request) -> Response:
        """List sessions."""
        self._require_auth(request)

        sessions = self.session_manager.list()
        return JSONResponse(
            {
                "sessions": [
                    {
                        "id": s.id,
                        "cwd": s.cwd,
                        "created_at": s.created_at.isoformat(),
                        "message_count": len(s.messages),
                    }
                    for s in sessions
                ]
            }
        )

    async def _create_session(self, request: Request) -> Response:
        """Create session."""
        self._require_auth(request)

        body = request.body or {}
        cwd = body.get("cwd", ".")

        session = self.session_manager.create(cwd=cwd)

        return JSONResponse(
            {"session": {"id": session.id, "cwd": session.cwd}},
            status_code=201,
        )

    async def _get_session(self, request: Request) -> Response:
        """Get session."""
        self._require_auth(request)

        session_id = request.path.split("/")[-1]
        session = self.session_manager.get(session_id)

        if not session:
            raise NotFoundError(f"Session {session_id} not found")

        return JSONResponse(
            {
                "session": {
                    "id": session.id,
                    "cwd": session.cwd,
                    "created_at": session.created_at.isoformat(),
                    "messages": session.messages,
                }
            }
        )

    async def _delete_session(self, request: Request) -> Response:
        """Delete session."""
        self._require_auth(request)

        session_id = request.path.split("/")[-1]
        deleted = self.session_manager.delete(session_id)

        if not deleted:
            raise NotFoundError(f"Session {session_id} not found")

        return JSONResponse({"deleted": True})

    async def _session_prompt(self, request: Request) -> Response:
        """Prompt session (non-streaming)."""
        self._require_auth(request)

        parts = request.path.split("/")
        session_id = parts[2]

        session = self.session_manager.get(session_id)
        if not session:
            raise NotFoundError(f"Session {session_id} not found")

        body = request.body or {}
        messages = body.get("messages", [])
        system_prompt = body.get("system_prompt")

        if not messages:
            raise BadRequestError("messages required")

        llm_messages = []
        if system_prompt:
            llm_messages.append(LLMMessage(role="system", content=system_prompt))

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_content = ""
                for block in content:
                    if block.get("type") == "text":
                        text_content += block.get("text", "")
                content = text_content
            llm_messages.append(LLMMessage(role=role, content=content))

        self.session_manager.add_message(
            session_id,
            {
                "role": "user",
                "content": messages,
                "timestamp": datetime.now().isoformat(),
            },
        )

        try:
            if self.nanocode:
                response = await self.nanocode.process_input(
                    messages[-1].get("content", "") if messages else ""
                )
                content = response if isinstance(response, str) else str(response)
            else:
                content = "Agent not configured. Use --agent to configure."

            self.session_manager.add_message(
                session_id,
                {
                    "role": "assistant",
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                },
            )

            return JSONResponse(
                {
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": content}],
                    },
                    "done": True,
                }
            )

        except Exception as e:
            return JSONResponse(
                {
                    "error": str(e),
                    "done": True,
                },
                status_code=500,
            )

    async def _session_prompt_stream(self, request: Request) -> Response:
        """Prompt session with streaming."""
        self._require_auth(request)

        return StreamResponse()

    async def _list_tools(self, request: Request) -> Response:
        """List tools."""
        self._require_auth(request)

        tools = []
        if self.nanocode and hasattr(self.nanocode, "tool_registry"):
            for tool in self.nanocode.tool_registry.list_tools():
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                    }
                )

        return JSONResponse({"tools": tools})

    async def _get_config(self, request: Request) -> Response:
        """Get server config."""
        self._require_auth(request)

        return JSONResponse(
            {
                "version": "0.1.0",
                "name": "nanocode",
                "auth_enabled": bool(self.auth_username and self.auth_password),
                "session_count": len(self.session_manager.list()),
            }
        )

    async def _get_stats(self, request: Request) -> Response:
        """Get current stats including token usage, model, and provider info."""
        self._require_auth(request)

        stats = {
            "tokens_used": 0,
            "context_percent_used": 0.0,
            "max_tokens_context": 0,
            "model": "unknown",
            "provider": "unknown",
        }

        if self.nanocode:
            if (
                hasattr(self.nanocode, "context_manager")
                and self.nanocode.context_manager
            ):
                token_usage = self.nanocode.context_manager.get_token_usage()
                stats["tokens_used"] = token_usage.get("current_tokens", 0)
                stats["context_percent_used"] = token_usage.get(
                    "context_usage_percent", 0.0
                )
                stats["max_tokens_context"] = token_usage.get("context_limit", 0)

            if hasattr(self.nanocode, "llm") and self.nanocode.llm:
                stats["model"] = getattr(self.nanocode.llm, "model", "unknown")
                stats["provider"] = getattr(self.nanocode.llm, "provider", "unknown")

            if hasattr(self.nanocode, "config") and self.nanocode.config:
                config = self.nanocode.config
                stats["provider"] = config.get("default_connector", "unknown")
                if "llm" in config:
                    stats["model"] = config.get("default_model", stats["model"])

        return JSONResponse(stats)

    async def _openapi(self, request: Request) -> Response:
        """OpenAPI spec."""
        return JSONResponse(
            {
                "openapi": "3.0.0",
                "info": {
                    "title": "Agent Smith Server",
                    "version": "0.1.0",
                },
                "paths": {
                    "/health": {"get": {"summary": "Health check"}},
                    "/ready": {"get": {"summary": "Readiness check"}},
                    "/sessions": {
                        "get": {"summary": "List sessions"},
                        "post": {"summary": "Create session"},
                    },
                    "/sessions/{id}": {
                        "get": {"summary": "Get session"},
                        "delete": {"summary": "Delete session"},
                    },
                    "/sessions/{id}/prompt": {
                        "post": {"summary": "Send prompt"},
                    },
                    "/tools": {"get": {"summary": "List tools"}},
                },
            }
        )

    def _parse_query_params(self, path: str) -> tuple[str, dict]:
        query_params = {}
        if "?" not in path:
            return path, query_params
        path, query_str = path.split("?", 1)
        for param in query_str.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                query_params[key] = value
        return path, query_params

    def _match_dynamic_route(self, method: str, path: str, request) -> Response | None:
        for route_method, route_path in self.router.list_routes():
            if "{" not in route_path:
                continue
            route_parts = route_path.split("/")
            path_parts = path.split("/")
            if len(route_parts) != len(path_parts):
                continue
            match = True
            params = {}
            for i, (rp, pp) in enumerate(zip(route_parts, path_parts)):
                if rp.startswith("{") and rp.endswith("}"):
                    params[rp[1:-1]] = pp
                elif rp != pp:
                    match = False
                    break
            if match:
                request.path = path
                handler = self.router.get_handler(route_method, route_path)
                if handler:
                    return handler(request)
        return None

    async def handle_request(
        self, method: str, path: str, headers: dict, body: Any = None
    ) -> Response:
        """Handle an HTTP request."""
        try:
            path, query_params = self._parse_query_params(path)
            request = Request(method, path, headers, body, query_params)
            if not self._check_auth(request) and path not in ["/health", "/ready", "/openapi.json"]:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            handler = self.router.get_handler(method, path)
            if handler:
                return await handler(request)
            result = self._match_dynamic_route(method, path, request)
            if result:
                return await result
            raise NotFoundError(f"Route {method} {path} not found")
        except HTTPError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status_code)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def start(self):
        """Start the server."""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )
        print(f"Server started on http://{self.host}:{self.port}")

    async def _parse_http_headers(
        self, reader: asyncio.StreamReader
    ) -> tuple[dict, int]:
        """Parse HTTP headers. Returns (headers, content_length)."""
        headers = {}
        content_length = 0
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
            header_line = line.decode().strip()
            if ":" in header_line:
                key, value = header_line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
                if key.strip().lower() == "content-length":
                    content_length = int(value.strip())
        return headers, content_length

    async def _parse_http_body(self, reader: asyncio.StreamReader, content_length: int) -> Any:
        if content_length <= 0:
            return None
        body_data = await reader.read(content_length)
        try:
            return json.loads(body_data.decode())
        except json.JSONDecodeError:
            return body_data.decode()

    def _write_http_response(self, writer: asyncio.StreamWriter, response: Response):
        writer.write(f"HTTP/1.1 {response.status_code} OK\r\n".encode())
        for key, value in response.headers.items():
            writer.write(f"{key}: {value}\r\n".encode())
        writer.write(b"\r\n")
        if response.body:
            writer.write(response.body.encode() if isinstance(response.body, str) else response.body)

    async def _write_stream_response(
        self, writer: asyncio.StreamWriter, response: StreamResponse
    ):
        """Write an SSE stream response."""
        writer.write(f"HTTP/1.1 {response.status_code} OK\r\n".encode())
        for key, value in response.headers.items():
            writer.write(f"{key}: {value}\r\n".encode())
        writer.write(b"\r\n")
        await writer.drain()

        if response.event_stream:
            async for chunk in response.event_stream:
                data = chunk.encode() if isinstance(chunk, str) else chunk
                writer.write(data)
                await writer.drain()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle a client connection."""
        try:
            request_data = await reader.readline()
            if not request_data:
                return
            request_line = request_data.decode().strip()
            if not request_line:
                return
            parts = request_line.split()
            if len(parts) < 2:
                return
            method, path = parts[0], parts[1]
            headers, content_length = await self._parse_http_headers(reader)
            body = await self._parse_http_body(reader, content_length)
            response = await self.handle_request(method, path, headers, body)
            if isinstance(response, StreamResponse) and response.event_stream:
                await self._write_stream_response(writer, response)
            else:
                self._write_http_response(writer, response)
                await writer.drain()
        except Exception as e:
            print(f"Error handling client: {e}")

        finally:
            writer.close()
            await writer.wait_closed()

    async def stop(self):
        """Stop the server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        print("Server stopped")


async def run_server(
    host: str = "127.0.0.1",  # localhost only by default for security
    port: int = 8080,
    agent=None,
    auth_username: str = None,
    auth_password: str = None,
):
    """Run the server."""
    server = AgentServer(
        host=host,
        port=port,
        agent=agent,
        auth_username=auth_username,
        auth_password=auth_password,
    )
    await server.start()
    return server
