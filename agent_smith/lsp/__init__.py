"""LSP (Language Server Protocol) client integration."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class MessageType(Enum):
    """LSP message types."""

    ERROR = 1
    WARNING = 2
    INFO = 3
    LOG = 4


@dataclass
class Diagnostic:
    """LSP diagnostic."""

    range: dict
    message: str
    severity: int = 1
    code: Optional[str] = None
    source: Optional[str] = None


@dataclass
class CompletionItem:
    """LSP completion item."""

    label: str
    kind: int
    detail: Optional[str] = None
    documentation: Optional[str] = None
    insert_text: Optional[str] = None


@dataclass
class Location:
    """LSP location."""

    uri: str
    range: dict


@dataclass
class SymbolInformation:
    """LSP symbol information."""

    name: str
    kind: int
    location: Location


@dataclass
class Hover:
    """LSP hover result."""

    contents: Any
    range: Optional[dict] = None


@dataclass
class LSPServerInfo:
    """LSP server information."""

    id: str
    name: str
    extensions: list[str]
    command: list[str]
    env: dict = field(default_factory=dict)
    initialization_options: dict = field(default_factory=dict)


class LSPClient:
    """LSP client for language server communication."""

    def __init__(self, process: asyncio.subprocess.Process, server_id: str = None):
        self.process = process
        self.server_id = server_id
        self.request_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._notification_handler = None
        self._read_task = None
        self._capabilities = {}
        self._open_files: dict[str, int] = {}

    @classmethod
    async def spawn(
        cls, command: list[str], cwd: str = None, env: dict = None, server_id: str = None
    ) -> "LSPClient":
        """Spawn an LSP server process."""
        process_env = {**os.environ, **env} if env else None
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=process_env,
        )
        client = cls(process, server_id)
        client._read_task = asyncio.create_task(client._read_messages())
        return client

    async def _read_messages(self):
        """Read messages from LSP server."""
        reader = self.process.stdout
        while True:
            try:
                line = await reader.readline()
                if not line:
                    break

                content = line.decode().strip()
                if not content:
                    continue

                if content.startswith("Content-Length:"):
                    continue

                if content.startswith("{"):
                    message = json.loads(content)
                    await self._handle_message(message)
            except Exception as e:
                print(f"LSP read error: {e}")
                break

    async def _handle_message(self, message: dict):
        """Handle incoming LSP message."""
        msg_id = message.get("id")
        if msg_id in self._pending_requests:
            future = self._pending_requests.pop(msg_id)
            if "result" in message:
                future.set_result(message["result"])
            elif "error" in message:
                future.set_exception(Exception(message["error"]))
        elif message.get("method") == "textDocument/publishDiagnostics":
            if self._notification_handler:
                await self._notification_handler(message)
        elif self._notification_handler:
            await self._notification_handler(message)

    def set_notification_handler(self, handler):
        """Set handler for notifications."""
        self._notification_handler = handler

    async def send_request(self, method: str, params: dict = None) -> Any:
        """Send a request and wait for response."""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }

        future = asyncio.Future()
        self._pending_requests[self.request_id] = future

        await self._send(request)

        return await asyncio.wait_for(future, timeout=30.0)

    async def send_notification(self, method: str, params: dict = None):
        """Send a notification (no response)."""
        await self._send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
        )

    async def _send(self, message: dict):
        """Send a JSON-RPC message."""
        content = json.dumps(message)
        body = f"Content-Length: {len(content)}\r\n\r\n{content}"
        self.process.stdin.write(body.encode())
        await self.process.stdin.drain()

    async def initialize(
        self, root_path: str, capabilities: dict = None, initialization_options: dict = None
    ) -> dict:
        """Initialize the LSP session."""
        params = {
            "processId": os.getpid(),
            "rootUri": root_path if root_path.startswith("file://") else f"file://{root_path}",
            "capabilities": capabilities
            or {
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
            },
        }
        if initialization_options:
            params["initializationOptions"] = initialization_options

        result = await self.send_request("initialize", params)
        self._capabilities = result.get("capabilities", {})
        return result

    async def initialized(self):
        """Send initialized notification."""
        await self.send_notification("initialized", {})

    async def shutdown(self):
        """Shutdown the LSP session."""
        try:
            await self.send_request("shutdown")
        except Exception:
            pass
        await self.send_notification("exit")
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except Exception:
            self.process.kill()

    async def text_document__did_open(
        self, uri: str, language_id: str, text: str, version: int = 1
    ):
        """Notify server that a document was opened."""
        self._open_files[uri] = version
        await self.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": version,
                    "text": text,
                }
            },
        )

    async def text_document__did_change(self, uri: str, text: str, version: int = None):
        """Notify server that a document was changed."""
        if version is None:
            version = self._open_files.get(uri, 0) + 1
        self._open_files[uri] = version
        await self.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {
                    "uri": uri,
                    "version": version,
                },
                "contentChanges": [{"text": text}],
            },
        )

    async def text_document__did_save(self, uri: str, text: str = None):
        """Notify server that a document was saved."""
        params = {"textDocument": {"uri": uri}}
        if text:
            params["textDocument"]["text"] = text
        await self.send_notification("textDocument/didSave", params)

    async def text_document__did_close(self, uri: str):
        """Notify server that a document was closed."""
        await self.send_notification("textDocument/didClose", {"textDocument": {"uri": uri}})
        self._open_files.pop(uri, None)

    async def text_document__completion(
        self, uri: str, line: int, character: int
    ) -> list[CompletionItem]:
        """Request completions at a position."""
        result = await self.send_request(
            "textDocument/completion",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )

        if result is None:
            return []
        if isinstance(result, list):
            return [CompletionItem(**item) for item in result]
        elif isinstance(result, dict) and result.get("items"):
            return [CompletionItem(**item) for item in result["items"]]
        return []

    async def text_document__definition(
        self, uri: str, line: int, character: int
    ) -> list[Location]:
        """Request definition at a position."""
        result = await self.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )

        if result is None:
            return []
        if isinstance(result, list):
            return [Location(**item) for item in result]
        return [Location(**result)]

    async def text_document__references(
        self, uri: str, line: int, character: int
    ) -> list[Location]:
        """Request references at a position."""
        result = await self.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": True},
            },
        )

        if result is None:
            return []
        return [Location(**item) for item in result]

    async def text_document__hover(self, uri: str, line: int, character: int) -> Hover:
        """Request hover information."""
        result = await self.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )

        if result is None:
            return Hover(contents="")
        return Hover(**result)

    async def text_document__symbol(self, uri: str) -> list[SymbolInformation]:
        """Request document symbols."""
        result = await self.send_request(
            "textDocument/documentSymbol",
            {
                "textDocument": {"uri": uri},
            },
        )

        if result is None:
            return []
        return [SymbolInformation(**item) for item in result]

    async def workspace__symbol(self, query: str) -> list[SymbolInformation]:
        """Request workspace symbols."""
        result = await self.send_request(
            "workspace/symbol",
            {
                "query": query,
            },
        )

        if result is None:
            return []
        return [SymbolInformation(**item) for item in result]

    async def text_document__implementation(
        self, uri: str, line: int, character: int
    ) -> list[Location]:
        """Request implementation at a position."""
        result = await self.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )

        if result is None:
            return []
        if isinstance(result, list):
            return [Location(**item) for item in result]
        return [Location(**result)]

    async def text_document__diagnostics(self, uri: str) -> list[Diagnostic]:
        """Request diagnostics for a document."""
        try:
            result = await self.send_request(
                "textDocument/diagnostics",
                {
                    "textDocument": {"uri": uri},
                },
            )
        except Exception:
            return []

        if result is None:
            return []

        diagnostics = result if isinstance(result, list) else result.get("result", [])
        return [Diagnostic(**diag) for diag in diagnostics]


class LSPServerManager:
    """Manager for LSP server instances."""

    DEFAULT_SERVERS = [
        LSPServerInfo(
            id="pyright",
            name="Pyright",
            extensions=[".py"],
            command=["pyright", "--langserver", "-v"],
        ),
        LSPServerInfo(
            id="typescript",
            name="TypeScript",
            extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs"],
            command=["typescript-language-server", "--stdio"],
        ),
        LSPServerInfo(
            id="deno",
            name="Deno",
            extensions=[".ts", ".tsx", ".js", ".jsx"],
            command=["deno", "lsp"],
        ),
        LSPServerInfo(
            id="gopls",
            name="Go",
            extensions=[".go"],
            command=["gopls", "langserver"],
        ),
        LSPServerInfo(
            id="rust-analyzer",
            name="Rust",
            extensions=[".rs"],
            command=["rust-analyzer"],
        ),
        LSPServerInfo(
            id="clangd",
            name="Clangd",
            extensions=[".c", ".cpp", ".h", ".hpp"],
            command=["clangd"],
        ),
        LSPServerInfo(
            id="jedi-language-server",
            name="Jedi",
            extensions=[".py"],
            command=["jedi-language-server"],
        ),
        LSPServerInfo(
            id="rust-analyzer",
            name="Ruby",
            extensions=[".rb"],
            command=["solargraph", "langserver"],
        ),
        LSPServerInfo(
            id="omnisharp",
            name="C#",
            extensions=[".cs"],
            command=["omnisharp", "--languageserver"],
        ),
    ]

    def __init__(self):
        self._servers: dict[str, LSPClient] = {}
        self._server_info: dict[str, LSPServerInfo] = {}
        self._file_to_server: dict[str, str] = {}
        self._disabled: set[str] = set()

    def get_default_servers(self) -> list[LSPServerInfo]:
        """Get list of available default servers."""
        available = []
        for server in self.DEFAULT_SERVERS:
            if shutil.which(server.command[0]):
                available.append(server)
        return available

    def configure_server(self, server_id: str, command: list[str] = None, disabled: bool = False):
        """Configure an LSP server."""
        if disabled:
            self._disabled.add(server_id)
            return

        self._disabled.discard(server_id)

        if command:
            for default_server in self.DEFAULT_SERVERS:
                if default_server.id == server_id:
                    self._server_info[server_id] = LSPServerInfo(
                        id=server_id,
                        name=default_server.name,
                        extensions=default_server.extensions,
                        command=command,
                    )
                    return

            self._server_info[server_id] = LSPServerInfo(
                id=server_id,
                name=server_id,
                extensions=[],
                command=command,
            )

    async def start_server(
        self, name: str, command: list[str], cwd: str = None, env: dict = None
    ) -> LSPClient:
        """Start an LSP server."""
        if name in self._disabled:
            return None
        client = await LSPClient.spawn(command, cwd, env, server_id=name)
        await client.initialize(cwd or os.getcwd())
        await client.initialized()
        self._servers[name] = client
        return client

    def get_server(self, name: str) -> Optional[LSPClient]:
        """Get an LSP server by name."""
        return self._servers.get(name)

    def get_server_for_file(self, file_path: str) -> Optional[tuple[LSPClient, LSPServerInfo]]:
        """Get an appropriate LSP server for a file."""
        ext = Path(file_path).suffix

        for server_id, info in self._server_info.items():
            if server_id in self._disabled:
                continue
            if ext in info.extensions:
                client = self._servers.get(server_id)
                if client:
                    return (client, info)

        for default_server in self.DEFAULT_SERVERS:
            if default_server.id in self._disabled:
                continue
            if ext in default_server.extensions:
                client = self._servers.get(default_server.id)
                if client:
                    return (client, default_server)

        return None

    async def auto_start_for_file(self, file_path: str, cwd: str = None) -> Optional[LSPClient]:
        """Auto-start an appropriate LSP server for a file."""
        ext = Path(file_path).suffix

        for default_server in self.DEFAULT_SERVERS:
            if default_server.id in self._disabled:
                continue
            if ext in default_server.extensions:
                if default_server.id not in self._servers:
                    await self.start_server(
                        default_server.id,
                        default_server.command,
                        cwd=cwd,
                    )
                return self._servers.get(default_server.id)

        return None

    def stop_server(self, name: str):
        """Stop an LSP server."""
        if name in self._servers:
            try:
                self._servers[name].process.terminate()
            except Exception:
                pass
            del self._servers[name]

    async def stop_all(self):
        """Stop all LSP servers."""
        for server in list(self._servers.values()):
            try:
                await server.shutdown()
            except Exception:
                pass
        self._servers.clear()

    def get_status(self) -> list[dict]:
        """Get status of all LSP servers."""
        status = []
        for name, client in self._servers.items():
            status.append(
                {
                    "id": name,
                    "status": "running" if client.process.returncode is None else "stopped",
                }
            )
        return status


def file_uri_to_path(uri: str) -> str:
    """Convert file:// URI to path."""
    if uri.startswith("file://"):
        if uri.startswith("file:///"):
            return uri[7:]
        return uri.replace("file://", "")
    return uri


def path_to_file_uri(path: str) -> str:
    """Convert path to file:// URI."""
    return f"file://{os.path.abspath(path)}"
