"""MCP (Model Context Protocol) integration."""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass
import httpx


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


class MCPClient:
    """MCP client for connecting to MCP servers."""

    def __init__(self, base_url: str, headers: dict = None):
        self.base_url = base_url
        self.headers = headers or {}
        self._session_id: Optional[str] = None

    async def initialize(self) -> dict:
        """Initialize connection to MCP server."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {},
                            "resources": {},
                            "prompts": {},
                        },
                        "clientInfo": {
                            "name": "agent",
                            "version": "0.1.0",
                        },
                    },
                },
                headers=self.headers,
                timeout=30.0,
            )
            return response.json()

    async def list_tools(self) -> list[MCPTool]:
        """List available tools from MCP server."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                },
                headers=self.headers,
                timeout=30.0,
            )
            data = response.json()
            return [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                )
                for t in data.get("result", {}).get("tools", [])
            ]

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool on the MCP server."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments,
                    },
                },
                headers=self.headers,
                timeout=120.0,
            )
            data = response.json()
            return data.get("result", {})

    async def list_resources(self) -> list[MCPResource]:
        """List available resources."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "resources/list",
                },
                headers=self.headers,
                timeout=30.0,
            )
            data = response.json()
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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "resources/read",
                    "params": {"uri": uri},
                },
                headers=self.headers,
                timeout=30.0,
            )
            data = response.json()
            contents = data.get("result", {}).get("contents", [])
            if contents:
                return contents[0].get("text", "")
            return ""


class MCPManager:
    """Manager for multiple MCP server connections."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}

    def add_server(self, name: str, base_url: str, headers: dict = None):
        """Add an MCP server connection."""
        self._clients[name] = MCPClient(base_url, headers)

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
            entries.append({
                "name": name,
                "type": "directory" if os.path.isdir(entry_path) else "file",
            })
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
            {"name": "git_status", "description": "Get git status", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "git_log", "description": "Get git log", "inputSchema": {"type": "object", "properties": {"count": {"type": "integer"}}}},
            {"name": "git_diff", "description": "Get git diff", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
        ]
