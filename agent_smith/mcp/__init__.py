"""MCP (Model Context Protocol) integration."""

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass
import httpx
import subprocess


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
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._lock = asyncio.Lock()

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
        transport, _ = await loop.connect_write_pipe(lambda: protocol, self._process.stdin)
        self._writer = asyncio.StreamWriter(transport, protocol, None, loop)

    async def send(self, request: dict) -> dict:
        """Send a request and return response."""
        if not self._writer:
            await self.start()

        self._request_id += 1
        request["id"] = self._request_id

        async with self._lock:
            self._writer.write(json.dumps(request).encode() + b"\n")
            await self._writer.drain()

            line = await self._reader.readline()
            if not line:
                return {"error": "No response from server"}

            return json.loads(line.decode())

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool."""
        response = await self.send(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return response.get("result", {})

    async def list_tools(self) -> list[MCPTool]:
        """List available tools."""
        response = await self.send({"jsonrpc": "2.0", "method": "tools/list", "params": {}})

        tools = []
        if result := response.get("result"):
            for t in result.get("tools", []):
                tools.append(
                    MCPTool(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                    )
                )
        return tools

    async def initialize(self) -> dict:
        """Initialize the connection."""
        response = await self.send(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "clientInfo": {"name": "nanocode", "version": "0.1.0"},
                },
            }
        )
        await self.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        return response

    async def close(self):
        """Close the connection."""
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
        self.url = url
        self.headers = headers or {}
        self._session_id: Optional[str] = None

    async def send(self, request: dict) -> dict:
        """Send a request."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                json=request,
                headers=self.headers,
                timeout=30.0,
            )
            return response.json()

    async def initialize(self) -> dict:
        """Initialize the connection."""
        response = await self.send(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "clientInfo": {"name": "nanocode", "version": "0.1.0"},
                },
            }
        )
        await self.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        return response

    async def list_tools(self) -> list[MCPTool]:
        """List available tools."""
        response = await self.send({"jsonrpc": "2.0", "method": "tools/list", "params": {}})

        tools = []
        if result := response.get("result"):
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
        return response.get("result", {})

    async def close(self):
        """Close the connection."""
        pass


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
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/list",
            }
        )
        data = response
        return [
            MCPResource(
                uri=r["uri"],
                name=r["name"],
                description=r.get("description", ""),
                mime_type=r.get("mimeType", "text/plain"),
            )
            for r in data.get("result", {}).get("resources", [])
        ]

    async def read_resource(self, uri: str) -> str:
        """Read a resource."""
        response = await self._connection.send(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        contents = response.get("result", {}).get("contents", [])
        if contents:
            return contents[0].get("text", "")
        return ""

    async def close(self):
        """Close the connection."""
        await self._connection.close()


class MCPManager:
    """Manager for multiple MCP server connections."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}

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

        self._clients[name] = MCPClient(connection)

    async def connect_all(self):
        """Initialize all connected servers."""
        for name, client in self._clients.items():
            try:
                await client.initialize()
                print(f"Connected to MCP server: {name}")
            except Exception as e:
                print(f"Failed to connect to MCP server {name}: {e}")

    async def disconnect_all(self):
        """Disconnect all servers."""
        self._clients.clear()

    def get_client(self, name: str) -> Optional[MCPClient]:
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
            except:
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
                "description": "Write a file",
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
                "inputSchema": {"type": "object", "properties": {"count": {"type": "integer"}}},
            },
            {
                "name": "git_diff",
                "description": "Get git diff",
                "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        ]
