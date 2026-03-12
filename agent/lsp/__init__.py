"""LSP (Language Server Protocol) client integration."""

import asyncio
import json
from typing import Any, Optional
from dataclasses import dataclass
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


@dataclass
class CompletionItem:
    """LSP completion item."""
    label: str
    kind: int
    detail: Optional[str] = None
    documentation: Optional[str] = None
    insert_text: Optional[str] = None


class LSPClient:
    """LSP client for language server communication."""

    def __init__(self, process: asyncio.subprocess.Process):
        self.process = process
        self.request_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._notification_handler = None
        self._read_task = None

    @classmethod
    async def spawn(cls, command: list[str], cwd: str = None) -> "LSPClient":
        """Spawn an LSP server process."""
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        client = cls(process)
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
        await self._send({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        })

    async def _send(self, message: dict):
        """Send a JSON-RPC message."""
        content = json.dumps(message)
        body = f"Content-Length: {len(content)}\r\n\r\n{content}"
        self.process.stdin.write(body.encode())
        await self.process.stdin.drain()

    async def initialize(self, root_path: str, capabilities: dict = None) -> dict:
        """Initialize the LSP session."""
        return await self.send_request("initialize", {
            "processId": asyncio.get_event_loop().get_debug(),
            "rootUri": root_path,
            "capabilities": capabilities or {},
        })

    async def initialized(self):
        """Send initialized notification."""
        await self.send_notification("initialized", {})

    async def shutdown(self):
        """Shutdown the LSP session."""
        await self.send_request("shutdown")
        await self.send_notification("exit")
        self.process.terminate()

    async def text_document__did_open(self, uri: str, language_id: str, text: str, version: int = 1):
        """Notify server that a document was opened."""
        await self.send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": version,
                "text": text,
            }
        })

    async def text_document__did_change(self, uri: str, text: str, version: int = 2):
        """Notify server that a document was changed."""
        await self.send_notification("textDocument/didChange", {
            "textDocument": {
                "uri": uri,
                "version": version,
            },
            "contentChanges": [{"text": text}],
        })

    async def text_document__did_save(self, uri: str, text: str = None):
        """Notify server that a document was saved."""
        params = {"textDocument": {"uri": uri}}
        if text:
            params["textDocument"]["text"] = text
        await self.send_notification("textDocument/didSave", params)

    async def text_document__completion(self, uri: str, line: int, character: int) -> list[CompletionItem]:
        """Request completions at a position."""
        result = await self.send_request("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        
        if isinstance(result, list):
            return [CompletionItem(**item) for item in result]
        elif result.get("items"):
            return [CompletionItem(**item) for item in result["items"]]
        return []

    async def text_document__definition(self, uri: str, line: int, character: int) -> list[dict]:
        """Request definition at a position."""
        return await self.send_request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })

    async def text_document__hover(self, uri: str, line: int, character: int) -> dict:
        """Request hover information."""
        return await self.send_request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })

    async def text_document__diagnostics(self, uri: str) -> list[Diagnostic]:
        """Request diagnostics for a document."""
        result = await self.send_request("textDocument/diagnostics", {
            "textDocument": {"uri": uri},
        })
        
        if isinstance(result, dict) and "result" in result:
            result = result["result"]
        
        if not result:
            return []
        
        return [Diagnostic(**diag) for diag in result]


class LSPServerManager:
    """Manager for LSP server instances."""

    def __init__(self):
        self._servers: dict[str, LSPClient] = {}

    async def start_server(self, name: str, command: list[str], cwd: str = None):
        """Start an LSP server."""
        client = await LSPClient.spawn(command, cwd)
        self._servers[name] = client
        return client

    def get_server(self, name: str) -> Optional[LSPClient]:
        """Get an LSP server by name."""
        return self._servers.get(name)

    def stop_server(self, name: str):
        """Stop an LSP server."""
        if name in self._servers:
            self._servers[name].process.terminate()
            del self._servers[name]

    async def stop_all(self):
        """Stop all LSP servers."""
        for server in list(self._servers.values()):
            await server.shutdown()
        self._servers.clear()


class PyrightLSP:
    """Pyright language server helper."""

    @staticmethod
    async def get_completions(client: LSPClient, file_path: str, line: int, character: int) -> list[CompletionItem]:
        """Get Python completions."""
        return await client.text_document__completion(f"file://{file_path}", line, character)

    @staticmethod
    async def get_diagnostics(client: LSPClient, file_path: str) -> list[Diagnostic]:
        """Get Python diagnostics."""
        return await client.text_document__diagnostics(f"file://{file_path}")

    @staticmethod
    async def get_definition(client: LSPClient, file_path: str, line: int, character: int) -> list[dict]:
        """Get Python definition."""
        return await client.text_document__definition(f"file://{file_path}", line, character)
