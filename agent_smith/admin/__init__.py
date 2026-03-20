"""Admin console for local management and monitoring.

This module provides a local web-based admin console for:
- Dashboard with usage statistics
- Session management
- Configuration management
- API key management
- Usage analytics
- Full-featured web UI with chat, files browser, etc.
"""

import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from aiohttp import web

from nanocode.config import Config, get_config
from nanocode.storage import get_storage


@dataclass
class UsageStats:
    """Usage statistics."""

    total_sessions: int = 0
    total_messages: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost: float = 0.0
    sessions_by_date: dict = field(default_factory=dict)
    tokens_by_model: dict = field(default_factory=dict)


class AdminConsole:
    """Local admin console web interface."""

    def __init__(self, config: Config, host: str = "127.0.0.1", port: int = 7890):
        self.config = config
        self.host = host
        self.port = port
        self.app = web.Application()
        self._web_module = None
        self._setup_routes()

    @property
    def _web(self):
        """Lazy load web module."""
        if self._web_module is None:
            from nanocode.admin import web_templates

            self._web_module = web_templates
        return self._web_module

    def _setup_routes(self):
        """Setup admin routes."""
        self.app.router.add_get("/", self.handle_dashboard)
        self.app.router.add_get("/dashboard", self.handle_dashboard)
        self.app.router.add_get("/chat", self.handle_chat)
        self.app.router.add_get("/sessions", self.handle_sessions)
        self.app.router.add_get("/sessions/{session_id}", self.handle_session_detail)
        self.app.router.add_post("/sessions/{session_id}/delete", self.handle_delete_session)
        self.app.router.add_get("/files", self.handle_files)
        self.app.router.add_get("/usage", self.handle_usage)
        self.app.router.add_get("/config", self.handle_config)
        self.app.router.add_post("/config/save", self.handle_config_save)
        self.app.router.add_get("/keys", self.handle_keys)
        self.app.router.add_post("/keys/add", self.handle_add_key)
        self.app.router.add_post("/keys/delete", self.handle_delete_key)
        self.app.router.add_get("/settings", self.handle_settings)
        self.app.router.add_get("/tools", self.handle_tools)
        self.app.router.add_get("/skills", self.handle_skills)
        self.app.router.add_post("/api/chat", self.handle_api_chat)
        self.app.router.add_get("/health", self.handle_health)

    async def handle_health(self, request):
        """Health check endpoint."""
        return web.json_response({"status": "ok", "service": "admin"})

    async def handle_dashboard(self, request):
        """Dashboard overview."""
        try:
            storage = await get_storage()
            stats = await self._get_usage_stats()

            recent_sessions = []
            if storage:
                try:
                    sessions = await storage.list_sessions(limit=10)
                    recent_sessions = [
                        {
                            "id": s.get("id", "unknown"),
                            "created_at": s.get("created_at", ""),
                            "message_count": s.get("message_count", 0),
                            "status": s.get("status", "active"),
                        }
                        for s in sessions
                    ]
                except Exception:
                    pass

            html = self._web.get_dashboard_html(stats.__dict__, recent_sessions)
            return web.Response(text=html, content_type="text/html")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_chat(self, request):
        """Chat interface."""
        session_id = request.query.get("session")
        messages = []
        if session_id:
            storage = await get_storage()
            if storage:
                try:
                    messages = await storage.get_messages(session_id)
                except Exception:
                    pass

        html = self._web.get_chat_html(session_id, messages)
        return web.Response(text=html, content_type="text/html")

    async def handle_sessions(self, request):
        """List all sessions."""
        try:
            storage = await get_storage()
            page = int(request.query.get("page", 1))
            limit = 50
            offset = (page - 1) * limit

            sessions = []
            total = 0
            if storage:
                try:
                    all_sessions = await storage.list_sessions(limit=1000)
                    total = len(all_sessions)
                    sessions = all_sessions[offset : offset + limit]
                except Exception:
                    pass

            html = self._web.get_sessions_html(sessions, page, total)
            return web.Response(text=html, content_type="text/html")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_session_detail(self, request):
        """Session detail view."""
        session_id = request.match_info["session_id"]

        try:
            storage = await get_storage()
            session = None

            if storage:
                try:
                    session = await storage.get_session(session_id)
                except Exception:
                    pass

            if not session:
                return web.Response(text="Session not found", status=404)

            html = self._web.get_sessions_html([session], 1, 1)
            return web.Response(text=html, content_type="text/html")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_delete_session(self, request):
        """Delete a session."""
        session_id = request.match_info["session_id"]

        try:
            storage = await get_storage()
            if storage:
                await storage.delete_session(session_id)
            return web.HTTPFound("/sessions")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_files(self, request):
        """Files browser."""
        path = request.query.get("path", "")

        try:
            root = Path.cwd()
            if path:
                search_path = root / path
            else:
                search_path = root

            files = []
            if search_path.exists() and search_path.is_dir():
                for item in sorted(search_path.iterdir()):
                    if item.name.startswith("."):
                        continue
                    if item.name in ["node_modules", "__pycache__", ".git", "venv", ".venv"]:
                        continue

                    stat = item.stat()
                    files.append(
                        {
                            "name": item.name,
                            "path": str(item.relative_to(root)),
                            "is_dir": item.is_dir(),
                            "size": (
                                f"{stat.st_size:,}"
                                if stat.st_size < 1024 * 1024
                                else f"{stat.st_size//1024//1024}MB"
                            ),
                            "modified": stat.st_mtime,
                        }
                    )

            html = self._web.get_files_html(files, path)
            return web.Response(text=html, content_type="text/html")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_usage(self, request):
        """Usage analytics."""
        stats = await self._get_usage_stats()

        html = self._web.get_usage_html(stats.__dict__)
        return web.Response(text=html, content_type="text/html")

    async def handle_config(self, request):
        """Configuration editor."""
        html = self._web.get_config_html(self.config._config, self.config._config_path)
        return web.Response(text=html, content_type="text/html")

    async def handle_config_save(self, request):
        """Save configuration."""
        try:
            data = await request.post()
            new_config = json.loads(data.get("config", "{}"))
            self.config._config = new_config

            with open(self.config._config_path, "w") as f:
                json.dump(new_config, f, indent=2)

            return web.HTTPFound("/config")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_keys(self, request):
        """API key management."""
        keys = self._get_api_keys()

        html = self._web.get_keys_html(keys)
        return web.Response(text=html, content_type="text/html")

    async def handle_add_key(self, request):
        """Add API key."""
        try:
            data = await request.post()
            name = data.get("name", "default")
            key = data.get("key", "")

            if key:
                self.config.set(f"llm.providers.{name}.api_key", key)

            return web.HTTPFound("/keys")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_delete_key(self, request):
        """Delete API key."""
        try:
            data = await request.post()
            name = data.get("name", "")

            if name:
                self.config.set(f"llm.providers.{name}.api_key", "")

            return web.HTTPFound("/keys")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_settings(self, request):
        """Settings page."""
        html = self._web.get_settings_html()
        return web.Response(text=html, content_type="text/html")

    async def handle_tools(self, request):
        """Tools page."""
        tools = []
        try:
            from nanocode.tools import ToolRegistry

            registry = ToolRegistry()
            for tool in registry.list_tools():
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                    }
                )
        except Exception:
            pass

        html = self._web.get_tools_html(tools)
        return web.Response(text=html, content_type="text/html")

    async def handle_skills(self, request):
        """Skills page."""
        html = self._web.get_tools_html(
            [{"name": "skills", "description": "Custom skills loaded from .agent/skills"}]
        )
        return web.Response(text=html, content_type="text/html")

    async def handle_api_chat(self, request):
        """Chat API endpoint."""
        try:
            data = await request.json()
            message = data.get("message", "")

            return web.json_response(
                {
                    "message": "Chat API not fully implemented yet",
                    "echo": message,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _get_usage_stats(self) -> UsageStats:
        """Get usage statistics."""
        stats = UsageStats()

        try:
            storage = await get_storage()
            if storage:
                sessions = await storage.list_sessions(limit=10000)
                stats.total_sessions = len(sessions)

                for session in sessions:
                    stats.total_messages += session.get("message_count", 0)

                    messages = await storage.get_messages(session.get("id", ""))
                    for msg in messages:
                        if isinstance(msg, dict):
                            tokens_in = msg.get("tokens_in", 0)
                            tokens_out = msg.get("tokens_out", 0)
                            cost = msg.get("cost", 0.0)

                            stats.total_tokens_in += tokens_in
                            stats.total_tokens_out += tokens_out
                            stats.total_cost += cost

                            model = msg.get("model", "unknown")
                            if model not in stats.tokens_by_model:
                                stats.tokens_by_model[model] = {"in": 0, "out": 0, "cost": 0.0}
                            stats.tokens_by_model[model]["in"] += tokens_in
                            stats.tokens_by_model[model]["out"] += tokens_out
                            stats.tokens_by_model[model]["cost"] += cost

                            created_at = msg.get("created_at", "")
                            if created_at:
                                date = created_at[:10]
                                if date not in stats.sessions_by_date:
                                    stats.sessions_by_date[date] = {"messages": 0, "tokens": 0}
                                stats.sessions_by_date[date]["messages"] += 1
                                stats.sessions_by_date[date]["tokens"] += tokens_in + tokens_out
        except Exception:
            pass

        return stats

    def _get_api_keys(self) -> list[dict]:
        """Get stored API keys (masked)."""
        keys = []
        providers = self.config.providers

        for name, provider_config in providers.items():
            if isinstance(provider_config, dict):
                api_key = provider_config.get("api_key", "")
                if api_key and not api_key.startswith("${"):
                    keys.append(
                        {
                            "name": name,
                            "key": api_key[:8] + "..." if len(api_key) > 8 else "***",
                            "full_key": api_key,
                        }
                    )

        return keys

    async def start(self):
        """Start the admin server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        print(f"Admin console started at http://{self.host}:{self.port}")
        return runner

    async def stop(self, runner):
        """Stop the admin server."""
        if runner:
            await runner.cleanup()


_admin_console: Optional[AdminConsole] = None


def get_admin_console(config: Config = None) -> AdminConsole:
    """Get or create the admin console instance."""
    global _admin_console
    if _admin_console is None:
        config = config or get_config()
        _admin_console = AdminConsole(config)
    return _admin_console


async def start_admin_console(config: Config = None, host: str = None, port: int = None):
    """Start the admin console server."""
    config = config or get_config()
    host = host or config.get("admin.host", "127.0.0.1")
    port = port or config.get("admin.port", 7890)

    console = AdminConsole(config, host, port)
    runner = await console.start()
    return runner


async def stop_admin_console(runner):
    """Stop the admin console server."""
    if runner:
        await runner.cleanup()
