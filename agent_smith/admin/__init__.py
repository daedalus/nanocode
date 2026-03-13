"""Admin console for local management and monitoring.

This module provides a local web-based admin console for:
- Dashboard with usage statistics
- Session management
- Configuration management
- API key management
- Usage analytics
"""

import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from aiohttp import web
import aiohttp_jinja2
import jinja2

from agent_smith.config import Config, get_config
from agent_smith.storage import get_storage


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
        self._setup_routes()
        self._setup_templates()

    def _setup_templates(self):
        """Setup Jinja2 templates."""
        template_dir = Path(__file__).parent / "templates"
        if not template_dir.exists():
            template_dir = Path(__file__).parent / "admin" / "templates"
        
        if template_dir.exists():
            loader = jinja2.FileSystemLoader(str(template_dir))
            self.app["templating"] = aiohttp_jinja2.setup(self.app, loader=loader)
        else:
            self._create_default_templates()

    def _create_default_templates(self):
        """Create inline templates when template files don't exist."""
        self._dashboard_template = self._get_dashboard_html()
        self._sessions_template = self._get_sessions_html()
        self._usage_template = self._get_usage_html()
        self._config_template = self._get_config_html()
        self._keys_template = self._get_keys_html()

    def _setup_routes(self):
        """Setup admin routes."""
        self.app.router.add_get("/", self.handle_dashboard)
        self.app.router.add_get("/dashboard", self.handle_dashboard)
        self.app.router.add_get("/sessions", self.handle_sessions)
        self.app.router.add_get("/sessions/{session_id}", self.handle_session_detail)
        self.app.router.add_post("/sessions/{session_id}/delete", self.handle_delete_session)
        self.app.router.add_get("/usage", self.handle_usage)
        self.app.router.add_get("/config", self.handle_config)
        self.app.router.add_post("/config/save", self.handle_config_save)
        self.app.router.add_get("/keys", self.handle_keys)
        self.app.router.add_post("/keys/add", self.handle_add_key)
        self.app.router.add_post("/keys/delete", self.handle_delete_key)
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
                        }
                        for s in sessions
                    ]
                except Exception:
                    pass

            context = {
                "title": "Agent Smith Admin",
                "stats": stats,
                "recent_sessions": recent_sessions,
                "config": self.config._config,
            }
            
            if hasattr(self, "_dashboard_template"):
                return web.Response(text=self._dashboard_template.render(context), content_type="text/html")
            
            return aiohttp_jinja2.render_template("dashboard.html", request, context)
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

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
                    sessions = all_sessions[offset:offset + limit]
                except Exception:
                    pass

            context = {
                "title": "Sessions - Admin",
                "sessions": sessions,
                "page": page,
                "total": total,
                "pages": (total + limit - 1) // limit,
            }
            
            if hasattr(self, "_sessions_template"):
                return web.Response(text=self._sessions_template.render(context), content_type="text/html")
            
            return aiohttp_jinja2.render_template("sessions.html", request, context)
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_session_detail(self, request):
        """Session detail view."""
        session_id = request.match_info["session_id"]
        
        try:
            storage = await get_storage()
            session = None
            messages = []
            
            if storage:
                try:
                    session = await storage.get_session(session_id)
                    if session:
                        messages = await storage.get_messages(session_id)
                except Exception:
                    pass

            if not session:
                return web.Response(text="Session not found", status=404)

            context = {
                "title": f"Session {session_id[:8]} - Admin",
                "session": session,
                "messages": messages[:100],
            }
            return aiohttp_jinja2.render_template("session_detail.html", request, context)
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

    async def handle_usage(self, request):
        """Usage analytics."""
        stats = await self._get_usage_stats()
        
        context = {
            "title": "Usage - Admin",
            "stats": stats,
        }
        
        if hasattr(self, "_usage_template"):
            return web.Response(text=self._usage_template.render(context), content_type="text/html")
        
        return aiohttp_jinja2.render_template("usage.html", request, context)

    async def handle_config(self, request):
        """Configuration editor."""
        context = {
            "title": "Configuration - Admin",
            "config": json.dumps(self.config._config, indent=2),
            "config_path": self.config._config_path,
        }
        
        if hasattr(self, "_config_template"):
            return web.Response(text=self._config_template.render(context), content_type="text/html")
        
        return aiohttp_jinja2.render_template("config.html", request, context)

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
        
        context = {
            "title": "API Keys - Admin",
            "keys": keys,
        }
        
        if hasattr(self, "_keys_template"):
            return web.Response(text=self._keys_template.render(context), content_type="text/html")
        
        return aiohttp_jinja2.render_template("keys.html", request, context)

    async def handle_add_key(self, request):
        """Add API key."""
        try:
            data = await request.post()
            name = data.get("name", "default")
            key = data.get("key", "")
            
            if key:
                self._save_api_key(name, key)
            
            return web.HTTPFound("/keys")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def handle_delete_key(self, request):
        """Delete API key."""
        try:
            data = await request.post()
            name = data.get("name", "")
            
            if name:
                self._delete_api_key(name)
            
            return web.HTTPFound("/keys")
        except Exception as e:
            return web.Response(text=f"Error: {str(e)}", status=500)

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
                if api_key and api_key != "${" + name.upper() + "_API_KEY}":
                    keys.append({
                        "name": name,
                        "key": api_key[:8] + "..." if len(api_key) > 8 else "***",
                        "full_key": api_key,
                    })
        
        return keys

    def _save_api_key(self, name: str, key: str):
        """Save API key to config."""
        self.config.set(f"llm.providers.{name}.api_key", key)

    def _delete_api_key(self, name: str):
        """Delete API key from config."""
        self.config.set(f"llm.providers.{name}.api_key", "")

    def _get_dashboard_html(self) -> jinja2.Template:
        """Get dashboard template."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
        .header { background: #1a1a2e; color: white; padding: 1rem 2rem; }
        .header h1 { margin: 0; font-size: 1.5rem; }
        .nav { background: #16213e; padding: 0.5rem 2rem; }
        .nav a { color: #ccc; text-decoration: none; margin-right: 1.5rem; }
        .nav a:hover { color: white; }
        .container { padding: 2rem; max-width: 1200px; margin: 0 auto; }
        .card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .card h2 { margin-top: 0; color: #333; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
        .stat { background: #f8f9fa; padding: 1rem; border-radius: 6px; text-align: center; }
        .stat-value { font-size: 2rem; font-weight: bold; color: #1a1a2e; }
        .stat-label { color: #666; font-size: 0.875rem; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; }
        .btn { padding: 0.5rem 1rem; border: none; border-radius: 4px; cursor: pointer; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-primary { background: #007bff; color: white; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Agent Smith Admin</h1>
    </div>
    <div class="nav">
        <a href="/dashboard">Dashboard</a>
        <a href="/sessions">Sessions</a>
        <a href="/usage">Usage</a>
        <a href="/config">Config</a>
        <a href="/keys">API Keys</a>
    </div>
    <div class="container">
        <div class="card">
            <h2>Overview</h2>
            <div class="stats-grid">
                <div class="stat">
                    <div class="stat-value">{{ stats.total_sessions }}</div>
                    <div class="stat-label">Total Sessions</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ stats.total_messages }}</div>
                    <div class="stat-label">Total Messages</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ "%.0f"|format(stats.total_tokens_in) }}</div>
                    <div class="stat-label">Tokens In</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ "%.0f"|format(stats.total_tokens_out) }}</div>
                    <div class="stat-label">Tokens Out</div>
                </div>
                <div class="stat">
                    <div class="stat-value">${{ "%.4f"|format(stats.total_cost) }}</div>
                    <div class="stat-label">Total Cost</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>Recent Sessions</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Created</th>
                        <th>Messages</th>
                    </tr>
                </thead>
                <tbody>
                    {% for session in recent_sessions %}
                    <tr>
                        <td><a href="/sessions/{{ session.id }}">{{ session.id[:8] }}...</a></td>
                        <td>{{ session.created_at[:19] if session.created_at else '-' }}</td>
                        <td>{{ session.message_count }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
        return jinja2.Template(html)

    def _get_sessions_html(self) -> jinja2.Template:
        """Get sessions template."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
        .header { background: #1a1a2e; color: white; padding: 1rem 2rem; }
        .nav { background: #16213e; padding: 0.5rem 2rem; }
        .nav a { color: #ccc; text-decoration: none; margin-right: 1.5rem; }
        .nav a:hover { color: white; }
        .container { padding: 2rem; max-width: 1200px; margin: 0 auto; }
        .card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; }
        .btn { padding: 0.5rem 1rem; border: none; border-radius: 4px; cursor: pointer; }
        .btn-danger { background: #dc3545; color: white; }
        .pagination { margin-top: 1rem; }
    </style>
</head>
<body>
    <div class="header"><h1>🤖 Agent Smith - Sessions</h1></div>
    <div class="nav">
        <a href="/dashboard">Dashboard</a>
        <a href="/sessions">Sessions</a>
        <a href="/usage">Usage</a>
        <a href="/config">Config</a>
        <a href="/keys">API Keys</a>
    </div>
    <div class="container">
        <div class="card">
            <h2>All Sessions ({{ total }})</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Created</th>
                        <th>Messages</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for session in sessions %}
                    <tr>
                        <td><a href="/sessions/{{ session.id }}">{{ session.id[:8] }}...</a></td>
                        <td>{{ session.created_at[:19] if session.created_at else '-' }}</td>
                        <td>{{ session.message_count }}</td>
                        <td>
                            <form action="/sessions/{{ session.id }}/delete" method="post" style="display:inline;">
                                <button type="submit" class="btn btn-danger" onclick="return confirm('Delete this session?')">Delete</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            <div class="pagination">
                {% if page > 1 %}<a href="?page={{ page - 1 }}">Previous</a>{% endif %}
                Page {{ page }} of {{ pages }}
                {% if page < pages %}<a href="?page={{ page + 1 }}">Next</a>{% endif %}
            </div>
        </div>
    </div>
</body>
</html>"""
        return jinja2.Template(html)

    def _get_usage_html(self) -> jinja2.Template:
        """Get usage template."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
        .header { background: #1a1a2e; color: white; padding: 1rem 2rem; }
        .nav { background: #16213e; padding: 0.5rem 2rem; }
        .nav a { color: #ccc; text-decoration: none; margin-right: 1.5rem; }
        .container { padding: 2rem; max-width: 1200px; margin: 0 auto; }
        .card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
        .stat { background: #f8f9fa; padding: 1rem; border-radius: 6px; text-align: center; }
        .stat-value { font-size: 2rem; font-weight: bold; color: #1a1a2e; }
        .stat-label { color: #666; font-size: 0.875rem; }
    </style>
</head>
<body>
    <div class="header"><h1>🤖 Agent Smith - Usage</h1></div>
    <div class="nav">
        <a href="/dashboard">Dashboard</a>
        <a href="/sessions">Sessions</a>
        <a href="/usage">Usage</a>
        <a href="/config">Config</a>
        <a href="/keys">API Keys</a>
    </div>
    <div class="container">
        <div class="card">
            <h2>Usage Summary</h2>
            <div class="stats-grid">
                <div class="stat"><div class="stat-value">{{ stats.total_sessions }}</div><div class="stat-label">Sessions</div></div>
                <div class="stat"><div class="stat-value">{{ stats.total_messages }}</div><div class="stat-label">Messages</div></div>
                <div class="stat"><div class="stat-value">{{ "%.0f"|format(stats.total_tokens_in) }}</div><div class="stat-label">Tokens In</div></div>
                <div class="stat"><div class="stat-value">{{ "%.0f"|format(stats.total_tokens_out) }}</div><div class="stat-label">Tokens Out</div></div>
                <div class="stat"><div class="stat-value">${{ "%.4f"|format(stats.total_cost) }}</div><div class="stat-label">Cost</div></div>
            </div>
        </div>
    </div>
</body>
</html>"""
        return jinja2.Template(html)

    def _get_config_html(self) -> jinja2.Template:
        """Get config template."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
        .header { background: #1a1a2e; color: white; padding: 1rem 2rem; }
        .nav { background: #16213e; padding: 0.5rem 2rem; }
        .nav a { color: #ccc; text-decoration: none; margin-right: 1.5rem; }
        .container { padding: 2rem; max-width: 1200px; margin: 0 auto; }
        .card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        textarea { width: 100%; height: 400px; font-family: monospace; padding: 1rem; border: 1px solid #ddd; border-radius: 4px; }
        .btn { padding: 0.75rem 1.5rem; border: none; border-radius: 4px; cursor: pointer; background: #007bff; color: white; }
        .btn:hover { background: #0056b3; }
        .path { color: #666; font-size: 0.875rem; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <div class="header"><h1>🤖 Agent Smith - Configuration</h1></div>
    <div class="nav">
        <a href="/dashboard">Dashboard</a>
        <a href="/sessions">Sessions</a>
        <a href="/usage">Usage</a>
        <a href="/config">Config</a>
        <a href="/keys">API Keys</a>
    </div>
    <div class="container">
        <div class="card">
            <h2>Edit Configuration</h2>
            <p class="path">Config file: {{ config_path }}</p>
            <form action="/config/save" method="post">
                <textarea name="config">{{ config }}</textarea>
                <br><br>
                <button type="submit" class="btn">Save Configuration</button>
            </form>
        </div>
    </div>
</body>
</html>"""
        return jinja2.Template(html)

    def _get_keys_html(self) -> jinja2.Template:
        """Get keys template."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
        .header { background: #1a1a2e; color: white; padding: 1rem 2rem; }
        .nav { background: #16213e; padding: 0.5rem 2rem; }
        .nav a { color: #ccc; text-decoration: none; margin-right: 1.5rem; }
        .container { padding: 2rem; max-width: 1200px; margin: 0 auto; }
        .card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #eee; }
        .btn { padding: 0.5rem 1rem; border: none; border-radius: 4px; cursor: pointer; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-primary { background: #007bff; color: white; }
        input { padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; margin-right: 0.5rem; }
    </style>
</head>
<body>
    <div class="header"><h1>🤖 Agent Smith - API Keys</h1></div>
    <div class="nav">
        <a href="/dashboard">Dashboard</a>
        <a href="/sessions">Sessions</a>
        <a href="/usage">Usage</a>
        <a href="/config">Config</a>
        <a href="/keys">API Keys</a>
    </div>
    <div class="container">
        <div class="card">
            <h2>Add API Key</h2>
            <form action="/keys/add" method="post">
                <input type="text" name="name" placeholder="Provider name (e.g., openai)" required>
                <input type="password" name="key" placeholder="API key" required>
                <button type="submit" class="btn btn-primary">Add Key</button>
            </form>
        </div>
        <div class="card">
            <h2>Stored Keys</h2>
            <table>
                <thead>
                    <tr>
                        <th>Provider</th>
                        <th>Key</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for key in keys %}
                    <tr>
                        <td>{{ key.name }}</td>
                        <td>{{ key.key }}</td>
                        <td>
                            <form action="/keys/delete" method="post" style="display:inline;">
                                <input type="hidden" name="name" value="{{ key.name }}">
                                <button type="submit" class="btn btn-danger" onclick="return confirm('Delete this key?')">Delete</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
        return jinja2.Template(html)

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
