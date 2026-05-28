"""MCP (Model Context Protocol) integration."""

import asyncio
import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

ServerRequestHandler = Callable[[dict], Awaitable[dict | None]]


@dataclass
class MCPResource:
    """MCP resource."""

    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"


@dataclass
class MCPTool:
    """MCP tool definition."""

    name: str
    description: str
    input_schema: dict


class MCPProtocol:
    """MCP protocol handler."""

    JSONRPC_VERSION = "2.0"

    def create_request(self, method: str, params: dict = None) -> dict:
        """Create a JSON-RPC request."""
        request = {"jsonrpc": self.JSONRPC_VERSION, "id": id(self), "method": method}
        if params:
            request["params"] = params
        return request


class MCPConnection(ABC):
    """Base class for MCP connections."""

    def __init__(self):
        self._request_handler: ServerRequestHandler | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._request_id = 0
        self._reader_task: asyncio.Task | None = None

    def set_request_handler(self, handler: ServerRequestHandler):
        """Set handler for server-initiated requests (e.g. sampling/createMessage, roots/list)."""
        self._request_handler = handler

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _dispatch_message(self, msg: dict):
        """Dispatch an incoming JSON-RPC message (response or server request)."""
        msg_id = msg.get("id")

        if msg_id is not None and msg_id in self._pending:
            future = self._pending.pop(msg_id)
            if "error" in msg:
                future.set_exception(
                    Exception(msg["error"].get("message", "RPC error"))
                )
            else:
                future.set_result(msg.get("result", {}))

        elif "method" in msg:
            is_notification = msg_id is None
            if not is_notification:
                if msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    future.set_exception(
                        Exception(
                            f"Unexpected server request (method={msg['method']}) collided with pending request ID"
                        )
                    )
            if self._request_handler:
                asyncio.ensure_future(self._handle_server_request(msg))
            elif not is_notification:
                await self._send_raw(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {msg.get('method')}",
                        },
                    }
                )

    async def _handle_server_request(self, msg: dict):
        """Handle a server-initiated request and send response."""
        try:
            response_body = await self._request_handler(msg)
            if response_body is not None and msg.get("id") is not None:
                await self._send_raw(
                    {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "result": response_body,
                    }
                )
        except Exception as e:
            logger.error(
                "Error handling server request %s: %s", msg.get("method"), e
            )
            if msg.get("id") is not None:
                await self._send_raw(
                    {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "error": {"code": -1, "message": str(e)},
                    }
                )

    @abstractmethod
    async def _send_raw(self, msg: dict):
        """Send raw JSON-RPC message."""
        pass

    @abstractmethod
    async def send(self, request: dict) -> dict:
        """Send a request and return response."""
        pass

    @abstractmethod
    async def initialize(self) -> dict:
        """Initialize the connection."""
        pass

    @abstractmethod
    async def list_tools(self) -> list[MCPTool]:
        """List available tools."""
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool."""
        pass

    @abstractmethod
    async def close(self):
        """Close the connection."""
        pass


class MCPStdioConnection(MCPConnection):
    """MCP connection over stdio."""

    def __init__(self, command: str, args: list[str] = None, env: dict = None):
        super().__init__()
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: subprocess.Popen | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()

    async def _reader_loop(self):
        """Background task reading JSON-RPC messages from process stdout."""
        try:
            while self._process and self._process.stdout and not self._process.stdout.closed:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except json.JSONDecodeError:
                    logger.debug("Ignoring non-JSON stdout line")
                    continue
                await self._dispatch_message(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MCP reader loop error")
        finally:
            self._reader_task = None

    async def start(self):
        """Start the stdio process."""
        full_env = os.environ.copy()
        full_env.update(self.env)

        self._process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env,
            text=True,
            bufsize=1,
        )

        loop = asyncio.get_event_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        transport, _ = await loop.connect_write_pipe(
            lambda: protocol, self._process.stdin
        )
        self._writer = asyncio.StreamWriter(transport, protocol, None, loop)

    async def _send_raw(self, msg: dict):
        if not self._writer:
            await self.start()
        line = json.dumps(msg).encode() + b"\n"
        async with self._write_lock:
            self._writer.write(line)
            await self._writer.drain()

    async def send(self, request: dict) -> dict:
        """Send a request and return response."""
        if not self._writer:
            await self.start()

        request_id = self._next_id()
        request["id"] = request_id
        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        async with self._write_lock:
            self._writer.write(json.dumps(request).encode() + b"\n")
            await self._writer.drain()

        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

        try:
            return await asyncio.wait_for(future, timeout=60.0)
        except TimeoutError:
            self._pending.pop(request_id, None)
            return {"error": "Timeout waiting for MCP response"}

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool."""
        response = await self.send(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return response

    async def list_tools(self) -> list[MCPTool]:
        """List available tools."""
        response = await self.send(
            {"jsonrpc": "2.0", "method": "tools/list", "params": {}}
        )

        tools = []
        if result := response:
            for t in result.get("tools", []):
                tools.append(
                    MCPTool(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                    )
                )
        return tools

    def _make_capabilities(self) -> dict:
        """Build capabilities dict, including sampling if handler is set."""
        caps = {"tools": {}, "resources": {}, "prompts": {}}
        if self._request_handler:
            caps["sampling"] = {}
        return caps

    async def initialize(self) -> dict:
        """Initialize the connection."""
        result = await self.send(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": self._make_capabilities(),
                    "clientInfo": {"name": "nanocode", "version": "0.1.0"},
                },
            }
        )
        await self._send_raw(
            {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        )
        return result

    async def close(self):
        """Close the connection."""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._writer = None
        self._reader = None


class MCPSSEConnection(MCPConnection):
    """MCP connection over Server-Sent Events (HTTP)."""

    def __init__(self, url: str, headers: dict = None):
        super().__init__()
        self.url = url
        self.headers = headers or {}

    async def _sse_listener(self, client: httpx.AsyncClient):
        """Background task listening for SSE events from the server."""
        try:
            async with client.stream("GET", self.url, headers=self.headers, timeout=None) as response:
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            msg = json.loads(data)
                            await self._dispatch_message(msg)
                        except json.JSONDecodeError:
                            logger.debug("Ignoring non-JSON SSE data")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MCP SSE listener error")

    async def _send_raw(self, msg: dict):
        async with httpx.AsyncClient() as client:
            await client.post(
                self.url,
                json=msg,
                headers=self.headers,
                timeout=30.0,
            )

    async def send(self, request: dict) -> dict:
        """Send a request."""
        request_id = self._next_id()
        request["id"] = request_id
        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._sse_listener())

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                json=request,
                headers=self.headers,
                timeout=30.0,
            )

        data = response.json()
        if "result" in data:
            self._pending.pop(request_id, None)
            return data["result"]
        if "error" in data:
            self._pending.pop(request_id, None)
            return {"error": data["error"].get("message", "RPC error")}

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except TimeoutError:
            self._pending.pop(request_id, None)
            return {"error": "Timeout waiting for MCP response"}

    def _make_capabilities(self) -> dict:
        """Build capabilities dict, including sampling if handler is set."""
        caps = {"tools": {}, "resources": {}, "prompts": {}}
        if self._request_handler:
            caps["sampling"] = {}
        return caps

    async def initialize(self) -> dict:
        """Initialize the connection."""
        result = await self.send(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": self._make_capabilities(),
                    "clientInfo": {"name": "nanocode", "version": "0.1.0"},
                },
            }
        )
        await self._send_raw(
            {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        )
        return result

    async def list_tools(self) -> list[MCPTool]:
        """List available tools."""
        response = await self.send(
            {"jsonrpc": "2.0", "method": "tools/list", "params": {}}
        )

        tools = []
        if result := response:
            for t in result.get("tools", []):
                tools.append(
                    MCPTool(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                    )
                )
        return tools

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool."""
        response = await self.send(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return response

    async def close(self):
        """Close the connection."""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None


class SamplingHandler:
    """Handles MCP sampling/createMessage requests by calling an LLM.

    When an MCP server sends a sampling/createMessage request, this handler
    converts the request to a local LLM call and returns the result.
    """

    def __init__(
        self,
        server_name: str,
        config: dict,
        call_llm: Callable[..., Awaitable[Any]],
    ):
        self.server_name = server_name
        self.call_llm = call_llm
        self.max_rpm = config.get("max_rpm", 10)
        self.timeout = config.get("timeout", 30)
        self.max_tokens_cap = config.get("max_tokens_cap", 4096)
        self.max_tool_rounds = config.get("max_tool_rounds", 5)
        self.model_override = config.get("model")
        self.allowed_models = config.get("allowed_models", [])

        self._rate_timestamps: list[float] = []
        self._rate_lock = asyncio.Lock()
        self._tool_loop_count = 0
        self.metrics = {
            "requests": 0,
            "errors": 0,
            "tokens_used": 0,
            "tool_use_count": 0,
        }

    def _check_rate_limit(self) -> bool:
        """Check if request is within rate limit. Returns True if allowed."""
        now = time.time()
        window_start = now - 60
        self._rate_timestamps = [t for t in self._rate_timestamps if t > window_start]
        return len(self._rate_timestamps) < self.max_rpm

    def _resolve_model(self, params: dict) -> str | None:
        """Resolve model from config override or server preferences."""
        if self.model_override:
            return self.model_override
        prefs = params.get("modelPreferences", {})
        hints = prefs.get("hints", [])
        if hints:
            return hints[0].get("name")
        return None

    def _convert_messages(self, mcp_messages: list[dict]) -> list[dict]:
        """Convert MCP SamplingMessages to OpenAI-format messages."""
        result = []
        for msg in mcp_messages:
            role = msg.get("role", "user")
            content = msg.get("content", {})

            content_list = content if isinstance(content, list) else [content]

            converted_parts = []
            tool_call_id = None
            has_tool_calls = False
            tool_calls = []

            for part in content_list:
                if isinstance(part, str):
                    converted_parts.append({"type": "text", "text": part})
                elif isinstance(part, dict):
                    ptype = part.get("type", "")
                    if ptype == "text" or "text" in part:
                        converted_parts.append(
                            {"type": "text", "text": part.get("text", "")}
                        )
                    elif ptype == "image" or "data" in part:
                        mime_type = part.get("mimeType", "image/png")
                        data = part.get("data", "")
                        converted_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{data}"
                                },
                            }
                        )
                    elif ptype == "tool_use" or "name" in part:
                        has_tool_calls = True
                        tool_call_id = part.get("id", "")
                        tool_calls.append(
                            {
                                "id": part.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": part.get("name", ""),
                                    "arguments": json.dumps(
                                        part.get("input", {})
                                    ),
                                },
                            }
                        )
                    elif ptype == "tool_result" or "tool_use_id" in part:
                        tool_call_id = part.get("tool_use_id", "")
                        inner_content = part.get("content", "")
                        if isinstance(inner_content, list):
                            for ic in inner_content:
                                if isinstance(ic, dict) and ic.get("type") == "text":
                                    converted_parts.append(
                                        {"type": "text", "text": ic["text"]}
                                    )
                        elif isinstance(inner_content, str):
                            converted_parts.append(
                                {"type": "text", "text": inner_content}
                            )

            if has_tool_calls:
                result.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": tool_calls,
                    }
                )
            elif tool_call_id:
                text = ""
                for cp in converted_parts:
                    if cp.get("type") == "text":
                        text += cp.get("text", "")
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": text or "",
                    }
                )
            else:
                text = ""
                for cp in converted_parts:
                    if cp.get("type") == "text":
                        text += cp.get("text", "")
                result.append({"role": role, "content": text or ""})

        return result

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to OpenAI function-calling format."""
        converted = []
        for tool in tools:
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema", {}),
                    },
                }
            )
        return converted

    def _sanitize_error(self, msg: str) -> str:
        """Strip sensitive info from error messages."""
        import re
        msg = re.sub(r"(sk-[a-zA-Z0-9]{10,})", "sk-...", msg)
        msg = re.sub(r"(api[_-]?key['\"]?\s*[:=]\s*)['\"][^'\"]+['\"]", r"\1***", msg)
        return msg[:200]

    async def _handle_sampling(self, msg: dict) -> dict | None:
        """Wrap __call__ for use as a ServerRequestHandler (extracts params from JSON-RPC)."""
        if msg.get("method") == "sampling/createMessage":
            return await self(msg.get("params", {}))
        return None

    async def __call__(self, params: dict) -> dict:
        """Handle a sampling/createMessage request."""
        self.metrics["requests"] += 1

        if not self._check_rate_limit():
            self.metrics["errors"] += 1
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": "Rate limit exceeded. Try again later.",
                    }
                ],
            }

        model = self._resolve_model(params)
        if self.allowed_models and model and model not in self.allowed_models:
            self.metrics["errors"] += 1
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": f"Model '{model}' not in allowed_models for this server.",
                    }
                ],
            }

        messages = self._convert_messages(params.get("messages", []))
        system_prompt = params.get("systemPrompt")

        max_tokens = params.get("maxTokens")
        if max_tokens is not None:
            max_tokens = min(max_tokens, self.max_tokens_cap)
        else:
            max_tokens = self.max_tokens_cap

        temperature = params.get("temperature")
        tools = params.get("tools")
        converted_tools = self._convert_tools(tools) if tools else None

        try:
            response = await asyncio.wait_for(
                self.call_llm(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=converted_tools,
                ),
                timeout=self.timeout,
            )
        except TimeoutError:
            self.metrics["errors"] += 1
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": "LLM call timed out.",
                    }
                ],
            }
        except Exception as e:
            self.metrics["errors"] += 1
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": self._sanitize_error(str(e)),
                    }
                ],
            }

        content_text = response.content or ""
        if hasattr(response, "usage") and response.usage:
            self.metrics["tokens_used"] += getattr(response.usage, "total_tokens", 0)

        if response.has_tool_calls and self.max_tool_rounds > 0:
            self._tool_loop_count += 1
            if self._tool_loop_count > self.max_tool_rounds:
                self.metrics["errors"] += 1
                return {
                    "isError": True,
                    "content": [
                        {
                            "type": "text",
                            "text": "Tool use loop limit exceeded.",
                        }
                    ],
                }

            self.metrics["tool_use_count"] += len(response.tool_calls)
            tool_use_contents = []
            for tc in response.tool_calls:
                tool_use_contents.append(
                    {
                        "type": "tool_use",
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            return {
                "role": "assistant",
                "content": tool_use_contents,
                "model": model or "unknown",
                "stopReason": "toolUse",
            }

        self._tool_loop_count = 0
        stop_reason_map = {
            "stop": "endTurn",
            "length": "maxTokens",
            "tool_calls": "toolUse",
        }
        mcp_stop = stop_reason_map.get(
            response.finish_reason or "stop", "endTurn"
        )

        return {
            "role": "assistant",
            "content": {"type": "text", "text": content_text},
            "model": model or "unknown",
            "stopReason": mcp_stop,
        }


class MCPClient:
    """MCP client for connecting to MCP servers."""

    def __init__(self, connection: MCPConnection):
        self._connection = connection

    @property
    def connection(self) -> MCPConnection:
        return self._connection

    async def initialize(self) -> dict:
        """Initialize connection to MCP server."""
        return await self._connection.initialize()

    async def list_tools(self) -> list[MCPTool]:
        """List available tools from MCP server."""
        return await self._connection.list_tools()

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool on the MCP server."""
        return await self._connection.call_tool(name, arguments)

    async def list_resources(self) -> list[MCPResource]:
        """List available resources."""
        response = await self._connection.send(
            {"jsonrpc": "2.0", "method": "resources/list"}
        )
        data = response
        return [
            MCPResource(
                uri=r["uri"],
                name=r["name"],
                description=r.get("description", ""),
                mime_type=r.get("mimeType", "text/plain"),
            )
            for r in data.get("resources", [])
        ]

    async def read_resource(self, uri: str) -> str:
        """Read a resource."""
        response = await self._connection.send(
            {
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        contents = response.get("contents", [])
        if contents:
            return contents[0].get("text", "")
        return ""

    async def close(self):
        """Close the connection."""
        await self._connection.close()


class MCPManager:
    """Manager for multiple MCP server connections."""

    def __init__(self, call_llm: Callable[..., Awaitable[Any]] = None):
        self._clients: dict[str, MCPClient] = {}
        self._call_llm = call_llm

    def add_server(self, name: str, server_config: dict):
        """Add an MCP server connection.

        Args:
            name: Server name
            server_config: Configuration dict with:
                - type: "stdio" or "sse" (default: "sse")
                - url: URL for SSE connections
                - command: Command for stdio connections
                - args: Args for stdio connections
                - env: Environment vars for stdio connections
                - headers: Headers for SSE connections
                - sampling: Sampling config dict (optional)
        """
        server_type = server_config.get("type", "sse")

        if server_type == "stdio":
            connection = MCPStdioConnection(
                command=server_config["command"],
                args=server_config.get("args", []),
                env=server_config.get("env", {}),
            )
        else:
            connection = MCPSSEConnection(
                url=server_config["url"],
                headers=server_config.get("headers", {}),
            )

        sampling_config = server_config.get("sampling", {})
        if sampling_config.get("enabled", True) and self._call_llm:
            handler = SamplingHandler(name, sampling_config, self._call_llm)
            connection.set_request_handler(handler._handle_sampling)

        self._clients[name] = MCPClient(connection)

    async def connect_all(self):
        """Initialize all connected servers."""
        for name, client in self._clients.items():
            try:
                await client.initialize()
                logger.info("Connected to MCP server: %s", name)
            except Exception as e:
                logger.warning("Failed to connect to MCP server %s: %s", name, e)

    async def disconnect_all(self):
        """Disconnect all servers."""
        self._clients.clear()

    def get_client(self, name: str) -> MCPClient | None:
        """Get an MCP client by name."""
        return self._clients.get(name)

    def list_servers(self) -> list[str]:
        """List connected server names."""
        return list(self._clients.keys())

    def get_all_tools(self) -> list[tuple[str, MCPTool]]:
        """Get all tools from all servers."""
        tools = []
        for name, client in self._clients.items():
            try:
                server_tools = asyncio.run(client.list_tools())
                for tool in server_tools:
                    tools.append((f"{name}:{tool.name}", tool))
            except Exception:
                pass
        return tools


class FilesystemMCPServer:
    """Built-in filesystem MCP server."""

    def __init__(self, root_path: str = "."):
        self.root_path = root_path

    async def list_directory(self, path: str = ".") -> list[dict]:
        """List directory contents."""
        import os

        full_path = os.path.join(self.root_path, path)
        entries = []
        for name in os.listdir(full_path):
            entry_path = os.path.join(full_path, name)
            entries.append(
                {
                    "name": name,
                    "type": "directory" if os.path.isdir(entry_path) else "file",
                }
            )
        return entries

    async def read_file(self, path: str) -> str:
        """Read a file."""
        full_path = os.path.join(self.root_path, path)
        with open(full_path) as f:
            return f.read()

    async def write_file(self, path: str, content: str):
        """Write a file."""
        import os

        full_path = os.path.join(self.root_path, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

    async def get_tool_definitions(self) -> list[dict]:
        """Get tool definitions."""
        return [
            {
                "name": "filesystem_list",
                "description": "List directory contents",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {
                "name": "filesystem_read",
                "description": "Read a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {
                "name": "filesystem_write",
                "description": "Write a file. REQUIRES read tool first to unlock the file for writing.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
        ]


class GitMCPServer:
    """Built-in git MCP server."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path

    async def run_git(self, *args) -> str:
        """Run a git command."""
        import subprocess

        result = subprocess.run(
            ["git"] + list(args),
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        return result.stdout + result.stderr

    async def status(self) -> str:
        """Get git status."""
        return await self.run_git("status", "--short")

    async def log(self, count: int = 10) -> str:
        """Get git log."""
        return await self.run_git("log", f"-{count}", "--oneline")

    async def diff(self, path: str = None) -> str:
        """Get git diff."""
        args = ["diff"]
        if path:
            args.append(path)
        return await self.run_git(*args)

    async def get_tool_definitions(self) -> list[dict]:
        """Get tool definitions."""
        return [
            {
                "name": "git_status",
                "description": "Get git status",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "git_log",
                "description": "Get git log",
                "inputSchema": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                },
            },
            {
                "name": "git_diff",
                "description": "Get git diff",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        ]
