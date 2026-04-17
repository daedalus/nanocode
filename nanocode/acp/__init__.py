"""ACP (Agent Client Protocol) server implementation.

This module provides an implementation of the Agent Client Protocol (ACP)
for connecting agents to clients like editors (Zed, VSCode) and other tools.

Specification: https://agentclientprotocol.com/
"""

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from nanocode.llm import Message as LLMMessage


class ACPError(Exception):
    """Base error for ACP."""

    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code
        self.message = message


class ACPParseError(ACPError):
    """Invalid JSON was received."""

    def __init__(self, message: str = "Parse error"):
        super().__init__(message, -32700)


class ACPInvalidRequest(ACPError):
    """JSON sent is not a valid Request object."""

    def __init__(self, message: str = "Invalid Request"):
        super().__init__(message, -32600)


class ACPMethodNotFound(ACPError):
    """Method does not exist / is not available."""

    def __init__(self, message: str = "Method not found"):
        super().__init__(message, -32601)


class ACPInvalidParams(ACPError):
    """Invalid method parameter(s)."""

    def __init__(self, message: str = "Invalid params"):
        super().__init__(message, -32602)


class ACPInternalError(ACPError):
    """Internal ACP error."""

    def __init__(self, message: str = "Internal error"):
        super().__init__(message, -32603)


class ACPServerError(ACPError):
    """Server error."""

    def __init__(self, message: str, code: int = -32000):
        super().__init__(message, code)


class ACPProtocolVersion:
    """Supported ACP protocol versions."""

    CURRENT = 1
    MIN = 1
    MAX = 1


@dataclass
class ACPCapabilities:
    """Agent capabilities advertised to clients."""

    prompts = True
    tools = True
    resources = True
    resources_subscribe = False
    notifications = False
    chat = False
    streaming = False


@dataclass
class ACPVersion:
    """Protocol version info."""

    major: int
    minor: int
    protocol_version: str = "2024-11-05"


@dataclass
class ACPInitializeResult:
    """Result of initialize request."""

    protocol_version: ACPVersion
    capabilities: ACPCapabilities
    server_info: dict


@dataclass
class ACPContentBlock:
    """A content block in a message."""

    type: str
    text: str | None = None
    resource: dict | None = None
    resource_uri: str | None = None
    image: str | None = None
    mime_type: str | None = None

    def to_dict(self) -> dict:
        result = {"type": self.type}
        if self.text:
            result["text"] = self.text
        if self.resource:
            result["resource"] = self.resource
        if self.resource_uri:
            result["resource_uri"] = self.resource_uri
        if self.mime_type:
            result["mime_type"] = self.mime_type
        return result


@dataclass
class ACPMessage:
    """A message in ACP."""

    role: str
    content: list[ACPContentBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"role": self.role, "content": [c.to_dict() for c in self.content]}


@dataclass
class ACPToolUse:
    """A tool use in ACP."""

    id: str
    name: str
    input: dict

    def to_dict(self) -> dict:
        return {
            "type": "tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


@dataclass
class ACPToolResult:
    """A tool result in ACP."""

    tool_use_id: str
    content: list[ACPContentBlock]
    is_error: bool = False

    def to_dict(self) -> dict:
        result = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": [c.to_dict() for c in self.content],
        }
        if self.is_error:
            result["is_error"] = True
        return result


@dataclass
class ACPStopReason:
    """Reason for stopping."""

    end_turn = "end_turn"
    max_tokens = "max_tokens"
    stop_sequence = "stop_sequence"


@dataclass
class ACPSessionState:
    """State of an ACP session."""

    id: str
    cwd: str
    created_at: Any = None
    messages: list[dict] = field(default_factory=list)
    model: dict | None = None


class ACPSessionManager:
    """Manages ACP sessions."""

    def __init__(self):
        self._sessions: dict[str, ACPSessionState] = {}

    def create(self, cwd: str = None, model: dict = None) -> ACPSessionState:
        """Create a new session."""
        session_id = f"session_{uuid.uuid4().hex[:8]}"
        session = ACPSessionState(
            id=session_id,
            cwd=cwd or ".",
            created_at=None,
            model=model,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> ACPSessionState | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def list(self) -> list[ACPSessionState]:
        """List all sessions."""
        return list(self._sessions.values())

    def delete(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


class ACPRequest:
    """An ACP JSON-RPC request."""

    def __init__(self, id: Any, method: str, params: dict = None):
        self.id = id
        self.method = method
        self.params = params or {}

    @classmethod
    def from_dict(cls, data: dict) -> "ACPRequest":
        """Create from dict."""
        return cls(
            id=data.get("id"),
            method=data.get("method", ""),
            params=data.get("params", {}),
        )

    def to_dict(self) -> dict:
        result = {"jsonrpc": "2.0", "id": self.id, "method": self.method}
        if self.params:
            result["params"] = self.params
        return result


class ACPResponse:
    """An ACP JSON-RPC response."""

    def __init__(self, id: Any, result: Any = None, error: ACPError = None):
        self.id = id
        self.result = result
        self.error = error

    def to_dict(self) -> dict:
        result = {"jsonrpc": "2.0", "id": self.id}
        if self.error:
            result["error"] = {
                "code": self.error.code,
                "message": self.error.message,
            }
        else:
            result["result"] = self.result
        return result


class ACPHandler:
    """Handles ACP requests."""

    def __init__(self, session_manager: ACPSessionManager, agent=None):
        self.session_manager = session_manager
        self.nanocode = agent
        self._initialized = False
        self._capabilities = ACPCapabilities()
        self._protocol_version = ACPProtocolVersion.CURRENT

    async def handle(self, request: ACPRequest) -> ACPResponse:
        """Handle an ACP request."""
        try:
            if request.method == "initialize":
                result = await self._handle_initialize(request.params)
                self._initialized = True
                return ACPResponse(request.id, result)

            if not self._initialized and request.method != "initialize":
                return ACPResponse(
                    request.id, error=ACPInvalidRequest("Not initialized")
                )

            if request.method == "ping":
                return ACPResponse(request.id, {"pong": True})

            elif request.method == "session/new":
                result = await self._handle_session_new(request.params)
                return ACPResponse(request.id, result)

            elif request.method == "session/delete":
                result = await self._handle_session_delete(request.params)
                return ACPResponse(request.id, result)

            elif request.method == "session/list":
                result = await self._handle_session_list()
                return ACPResponse(request.id, result)

            elif request.method == "session/prompt":
                result = await self._handle_session_prompt(request.params)
                return ACPResponse(request.id, result)

            elif request.method == "tools/list":
                result = await self._handle_tools_list()
                return ACPResponse(request.id, result)

            elif request.method == "resources/list":
                result = await self._handle_resources_list()
                return ACPResponse(request.id, result)

            else:
                return ACPResponse(request.id, error=ACPMethodNotFound())

        except ACPError as e:
            return ACPResponse(request.id, error=e)
        except Exception as e:
            return ACPResponse(request.id, error=ACPInternalError(str(e)))

    async def _handle_initialize(self, params: dict) -> dict:
        """Handle initialize request."""
        protocol_version = params.get("protocolVersion", 1)

        if (
            protocol_version < ACPProtocolVersion.MIN
            or protocol_version > ACPProtocolVersion.MAX
        ):
            raise ACPInvalidRequest(
                f"Protocol version {protocol_version} not supported"
            )

        self._protocol_version = protocol_version

        return {
            "protocol_version": {
                "major": ACPProtocolVersion.CURRENT,
                "minor": 0,
                "protocol_version": "2024-11-05",
            },
            "capabilities": {
                "prompts": True,
                "tools": True,
                "resources": True,
                "resources_subscribe": False,
                "notifications": False,
                "chat": False,
                "streaming": False,
            },
            "server_info": {
                "name": "nanocode",
                "version": "0.1.0",
                "description": "Agent Smith - Autonomous AI Agent",
            },
        }

    async def _handle_session_new(self, params: dict) -> dict:
        """Handle session/new request."""
        cwd = params.get("cwd", ".")
        model = params.get("model")

        session = self.session_manager.create(cwd=cwd, model=model)

        return {
            "session": {
                "id": session.id,
                "cwd": session.cwd,
            }
        }

    async def _handle_session_delete(self, params: dict) -> dict:
        """Handle session/delete request."""
        session_id = params.get("sessionId")

        if not session_id:
            raise ACPInvalidParams("sessionId is required")

        deleted = self.session_manager.delete(session_id)

        if not deleted:
            raise ACPInvalidRequest(f"Session {session_id} not found")

        return {"deleted": True}

    async def _handle_session_list(self) -> dict:
        """Handle session/list request."""
        sessions = self.session_manager.list()

        return {"sessions": [{"id": s.id, "cwd": s.cwd} for s in sessions]}

    async def _handle_session_prompt(self, params: dict) -> dict:
        """Handle session/prompt request."""
        session_id = params.get("sessionId")
        messages = params.get("messages", [])
        system_prompt = params.get("systemPrompt")

        if not session_id:
            raise ACPInvalidParams("sessionId is required")

        session = self.session_manager.get(session_id)
        if not session:
            raise ACPInvalidRequest(f"Session {session_id} not found")

        llm_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", [])

            text_content = ""
            for block in content:
                if block.get("type") == "text":
                    text_content += block.get("text", "")

            llm_messages.append(LLMMessage(role=role, content=text_content))

        if system_prompt:
            llm_messages.insert(0, LLMMessage(role="system", content=system_prompt))

        response_text = (
            "ACP prompt processed. Use nanocode directly for full functionality."
        )

        return {
            "session": {"id": session_id},
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": response_text}],
            },
            "stop_reason": "end_turn",
        }

    async def _handle_tools_list(self, params: dict = None) -> dict:
        """Handle tools/list request."""
        tools = []

        if self.nanocode:
            for tool in self.nanocode.tool_registry.list_tools():
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.schema if hasattr(tool, "schema") else {},
                    }
                )

        return {"tools": tools}

    async def _handle_resources_list(self, params: dict = None) -> dict:
        """Handle resources/list request."""
        return {"resources": []}


class ACPServer:
    """ACP Server that handles JSON-RPC over stdio."""

    def __init__(self, agent=None):
        self.session_manager = ACPSessionManager()
        self.handler = ACPHandler(self.session_manager, agent)
        self._running = False

    async def start(self):
        """Start the ACP server."""
        self._running = True

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        buffer = ""

        while self._running:
            try:
                line = await reader.readline()
                if not line:
                    break

                buffer += line.decode()

                if buffer.strip():
                    try:
                        request_data = json.loads(buffer)
                        request = ACPRequest.from_dict(request_data)
                        response = await self.handler.handle(request)

                        if response:
                            response_json = json.dumps(response.to_dict())
                            sys.stdout.write(
                                f"Content-Length: {len(response_json)}\r\n\r\n{response_json}"
                            )
                            sys.stdout.flush()

                    except json.JSONDecodeError as e:
                        error = ACPParseError(str(e))
                        response = ACPResponse(None, error=error)
                        response_json = json.dumps(response.to_dict())
                        sys.stdout.write(
                            f"Content-Length: {len(response_json)}\r\n\r\n{response_json}"
                        )
                        sys.stdout.flush()

                    buffer = ""

            except Exception as e:
                error = ACPInternalError(str(e))
                response = ACPResponse(None, error=error)
                response_json = json.dumps(response.to_dict())
                sys.stdout.write(
                    f"Content-Length: {len(response_json)}\r\n\r\n{response_json}"
                )
                sys.stdout.flush()
                buffer = ""

    def stop(self):
        """Stop the server."""
        self._running = False


async def run_acp_server(agent=None):
    """Run the ACP server."""
    server = ACPServer(agent)
    await server.start()
