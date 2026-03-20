"""Web UI templates for the admin console.

This module provides comprehensive HTML templates for a full-featured
web interface similar to opencode's web application.
"""

import json


def get_base_html(title: str = "Agent Smith") -> str:
    """Get the base HTML template with navigation."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        :root {{
            --primary: #1a1a2e;
            --secondary: #16213e;
            --accent: #0f3460;
            --light: #e8e8e8;
            --dark: #1a1a2e;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
        }}
        .navbar {{
            background: var(--primary) !important;
        }}
        .sidebar {{
            min-height: calc(100vh - 56px);
            background: white;
            border-right: 1px solid #eee;
        }}
        .sidebar .nav-link {{
            color: #333;
            padding: 0.75rem 1rem;
            border-radius: 0;
        }}
        .sidebar .nav-link:hover {{
            background: #f8f9fa;
        }}
        .sidebar .nav-link.active {{
            background: var(--primary);
            color: white;
        }}
        .card {{
            border: none;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 1rem;
        }}
        .stat-card {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
        }}
        .stat-card .stat-value {{
            font-size: 2rem;
            font-weight: bold;
        }}
        .table {{
            background: white;
        }}
        .btn-primary {{
            background: var(--primary);
            border-color: var(--primary);
        }}
        .btn-primary:hover {{
            background: var(--secondary);
            border-color: var(--secondary);
        }}
        .message-user {{
            background: #e3f2fd;
            border-radius: 12px 12px 0 12px;
            padding: 12px 16px;
            margin-left: 2rem;
        }}
        .message-assistant {{
            background: white;
            border: 1px solid #eee;
            border-radius: 12px 12px 12px 0;
            padding: 12px 16px;
            margin-right: 2rem;
        }}
        .file-tree {{ font-size: 0.875rem; }}
        .file-tree .folder {{ color: #ffc107; }}
        .file-tree .file {{ color: #6c757d; }}
        .code-block {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 1rem;
            border-radius: 8px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.875rem;
            overflow-x: auto;
        }}
        .badge-status {{
            font-size: 0.75rem;
        }}
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="bi bi-robot"></i> Agent Smith
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="/"><i class="bi bi-house"></i> Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/chat"><i class="bi bi-chat-dots"></i> Chat</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/sessions"><i class="bi bi-chat-square-text"></i> Sessions</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/files"><i class="bi bi-folder"></i> Files</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/usage"><i class="bi bi-graph-up"></i> Usage</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/config"><i class="bi bi-gear"></i> Config</a>
                    </li>
                </ul>
                <div class="d-flex">
                    <a class="btn btn-sm btn-outline-light" href="/keys">
                        <i class="bi bi-key"></i> API Keys
                    </a>
                </div>
            </div>
        </div>
    </nav>
    <div class="container-fluid">
        <div class="row">
            <nav class="col-md-2 d-md-block sidebar collapse">
                <div class="position-sticky pt-3">
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link" href="/">
                                <i class="bi bi-speedometer2"></i> Overview
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/chat">
                                <i class="bi bi-chat-dots"></i> New Chat
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/sessions">
                                <i class="bi bi-history"></i> History
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/files">
                                <i class="bi bi-folder2-open"></i> Files
                            </a>
                        </li>
                    </ul>
                    <hr>
                    <h6 class="sidebar-heading d-flex justify-content-between align-items-center px-3 mt-4 mb-1 text-muted">
                        <span>Tools</span>
                    </h6>
                    <ul class="nav flex-column mb-2">
                        <li class="nav-item">
                            <a class="nav-link" href="/tools">
                                <i class="bi bi-plug"></i> Available Tools
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/skills">
                                <i class="bi bi-lightning"></i> Skills
                            </a>
                        </li>
                    </ul>
                    <hr>
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link" href="/settings">
                                <i class="bi bi-gear"></i> Settings
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>
            <main class="col-md-10 ms-sm-auto px-md-4 py-3">
"""


def get_footer_html() -> str:
    """Get the footer HTML."""
    return """
            </main>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Enable tooltips
        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
        var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl)
        })
    </script>
</body>
</html>"""


def render_page(content: str, title: str = "Agent Smith") -> str:
    """Render a complete page."""
    return get_base_html(title) + content + get_footer_html()


def get_dashboard_html(stats: dict, recent_sessions: list) -> str:
    """Get dashboard page HTML."""
    sessions_html = ""
    for session in recent_sessions[:10]:
        sessions_html += f"""
        <tr>
            <td><a href="/sessions/{session.get('id', '')}">{session.get('id', '')[:8]}...</a></td>
            <td>{session.get('created_at', '')[:19] if session.get('created_at') else '-'}</td>
            <td>{session.get('message_count', 0)}</td>
            <td>
                <a href="/chat?session={session.get('id', '')}" class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-chat"></i>
                </a>
            </td>
        </tr>"""

    content = f"""
    <div class="py-2">
        <h2 class="mb-4"><i class="bi bi-speedometer2"></i> Dashboard</h2>
        
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">{stats.get('total_sessions', 0)}</div>
                        <div>Total Sessions</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">{stats.get('total_messages', 0)}</div>
                        <div>Messages</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">{stats.get('total_tokens_in', 0):,.0f}</div>
                        <div>Tokens In</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">${stats.get('total_cost', 0):.4f}</div>
                        <div>Total Cost</div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-8">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0"><i class="bi bi-clock-history"></i> Recent Sessions</h5>
                        <a href="/sessions" class="btn btn-sm btn-primary">View All</a>
                    </div>
                    <div class="card-body">
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Created</th>
                                    <th>Messages</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sessions_html if sessions_html else '<tr><td colspan="4" class="text-center text-muted">No sessions yet</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0"><i class="bi bi-lightning"></i> Quick Actions</h5>
                    </div>
                    <div class="card-body">
                        <div class="d-grid gap-2">
                            <a href="/chat" class="btn btn-primary">
                                <i class="bi bi-chat-dots"></i> New Chat
                            </a>
                            <a href="/files" class="btn btn-outline-secondary">
                                <i class="bi bi-folder"></i> Browse Files
                            </a>
                            <a href="/usage" class="btn btn-outline-secondary">
                                <i class="bi bi-graph-up"></i> View Usage
                            </a>
                        </div>
                    </div>
                </div>
                
                <div class="card mt-3">
                    <div class="card-header">
                        <h5 class="mb-0"><i class="bi bi-gear"></i> System Status</h5>
                    </div>
                    <div class="card-body">
                        <ul class="list-unstyled mb-0">
                            <li class="mb-2"><i class="bi bi-check-circle text-success"></i> API Connected</li>
                            <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Storage Ready</li>
                            <li><i class="bi bi-check-circle text-success"></i> Tools Loaded</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(content, "Dashboard - Agent Smith")


def get_chat_html(session_id: str = None, messages: list = None) -> str:
    """Get chat page HTML."""
    messages_html = ""
    if messages:
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages_html += f'<div class="message-user mb-3">{content}</div>'
            else:
                messages_html += f'<div class="message-assistant mb-3">{content}</div>'

    content = f"""
    <div class="py-2">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0"><i class="bi bi-chat-dots"></i> Chat</h5>
                <div>
                    <select class="form-select form-select-sm d-inline-block w-auto">
                        <option>gpt-4o</option>
                        <option>claude-3-5-sonnet</option>
                        <option>gpt-5-nano</option>
                    </select>
                </div>
            </div>
            <div class="card-body" style="height: 60vh; overflow-y: auto;" id="messages">
                {messages_html if messages_html else '<div class="text-center text-muted py-5">Start a conversation...</div>'}
            </div>
            <div class="card-footer">
                <form id="chat-form" class="d-flex gap-2">
                    <input type="text" class="form-control" id="message-input" placeholder="Type your message..." autocomplete="off">
                    <button type="submit" class="btn btn-primary">
                        <i class="bi bi-send"></i>
                    </button>
                </form>
            </div>
        </div>
    </div>
    
    <script>
        const form = document.getElementById('chat-form');
        const input = document.getElementById('message-input');
        const messages = document.getElementById('messages');
        
        form.addEventListener('submit', async (e) => {{
            e.preventDefault();
            const message = input.value.trim();
            if (!message) return;
            
            // Add user message
            messages.innerHTML += `<div class="message-user mb-3">${{message}}</div>`;
            input.value = '';
            messages.scrollTop = messages.scrollHeight;
            
            // Send to API
            try {{
                const response = await fetch('/api/chat', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ message }})
                }});
                const data = await response.json();
                
                // Add assistant message
                messages.innerHTML += `<div class="message-assistant mb-3">${{data.response || data.message}}</div>`;
                messages.scrollTop = messages.scrollHeight;
            }} catch (err) {{
                messages.innerHTML += `<div class="message-assistant mb-3 text-danger">Error: ${{err}}</div>`;
            }}
        }});
    </script>
    """
    return render_page(content, "Chat - Agent Smith")


def get_sessions_html(sessions: list, page: int = 1, total: int = 0) -> str:
    """Get sessions list page HTML."""
    sessions_html = ""
    for session in sessions:
        sessions_html += f"""
        <tr>
            <td><a href="/sessions/{session.get('id', '')}">{session.get('id', '')[:12]}...</a></td>
            <td>{session.get('created_at', '')[:19] if session.get('created_at') else '-'}</td>
            <td>{session.get('message_count', 0)}</td>
            <td>
                <span class="badge bg-{ 'success' if session.get('status') == 'active' else 'secondary'}">
                    {session.get('status', 'unknown')}
                </span>
            </td>
            <td>
                <a href="/chat?session={session.get('id', '')}" class="btn btn-sm btn-outline-primary">
                    <i class="bi bi-chat"></i>
                </a>
                <a href="/sessions/{session.get('id', '')}" class="btn btn-sm btn-outline-secondary">
                    <i class="bi bi-eye"></i>
                </a>
            </td>
        </tr>"""

    content = f"""
    <div class="py-2">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2><i class="bi bi-chat-square-text"></i> Sessions</h2>
            <a href="/chat" class="btn btn-primary">
                <i class="bi bi-plus"></i> New Session
            </a>
        </div>
        
        <div class="card">
            <div class="card-body">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Created</th>
                            <th>Messages</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sessions_html if sessions_html else '<tr><td colspan="5" class="text-center text-muted">No sessions yet</td></tr>'}
                    </tbody>
                </table>
                
                <nav>
                    <ul class="pagination justify-content-center">
                        <li class="page-item disabled"><a class="page-link" href="#">Previous</a></li>
                        <li class="page-item active"><a class="page-link" href="#">{page}</a></li>
                        <li class="page-item disabled"><a class="page-link" href="#">Next</a></li>
                    </ul>
                </nav>
            </div>
        </div>
    </div>
    """
    return render_page(content, "Sessions - Agent Smith")


def get_files_html(files: list, current_path: str = "") -> str:
    """Get files browser page HTML."""
    files_html = ""
    for f in files:
        icon = "folder" if f.get("is_dir") else "file-earmark"
        name = f.get("name", "")
        path = f.get("path", "")
        files_html += f"""
        <tr>
            <td><a href="/files?path={path}" class="text-decoration-none">
                <i class="bi bi-{icon}"></i> {name}
            </a></td>
            <td>{f.get('size', '-')}</td>
            <td>{f.get('modified', '-')}</td>
        </tr>"""

    content = f"""
    <div class="py-2">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2><i class="bi bi-folder2-open"></i> Files</h2>
            <nav aria-label="breadcrumb">
                <ol class="breadcrumb">
                    <li class="breadcrumb-item"><a href="/files">Root</a></li>
                    {f'<li class="breadcrumb-item active">{current_path}</li>' if current_path else ''}
                </ol>
            </nav>
        </div>
        
        <div class="card">
            <div class="card-body">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Size</th>
                            <th>Modified</th>
                        </tr>
                    </thead>
                    <tbody>
                        {files_html if files_html else '<tr><td colspan="3" class="text-center text-muted">No files found</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page(content, "Files - Agent Smith")


def get_usage_html(stats: dict) -> str:
    """Get usage analytics page HTML."""
    tokens_by_model = stats.get("tokens_by_model", {})
    sessions_by_date = stats.get("sessions_by_date", {})

    content = f"""
    <div class="py-2">
        <h2 class="mb-4"><i class="bi bi-graph-up"></i> Usage Analytics</h2>
        
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">{stats.get('total_sessions', 0)}</div>
                        <div>Total Sessions</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">{stats.get('total_messages', 0):,}</div>
                        <div>Messages</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">{(stats.get('total_tokens_in', 0) + stats.get('total_tokens_out', 0)):,}</div>
                        <div>Total Tokens</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body text-center">
                        <div class="stat-value">${stats.get('total_cost', 0):.4f}</div>
                        <div>Total Cost</div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Usage by Date</h5>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-sm">
                                <thead>
                                    <tr>
                                        <th>Date</th>
                                        <th>Messages</th>
                                        <th>Tokens</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {''.join(f'<tr><td>{date}</td><td>{data.get("messages", 0)}</td><td>{data.get("tokens", 0):,}</td></tr>' for date, data in sorted(sessions_by_date.items(), reverse=True)[:10])}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Usage by Model</h5>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-sm">
                                <thead>
                                    <tr>
                                        <th>Model</th>
                                        <th>Tokens In</th>
                                        <th>Tokens Out</th>
                                        <th>Cost</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {''.join(f'<tr><td>{model}</td><td>{data.get("in", 0):,}</td><td>{data.get("out", 0):,}</td><td>${data.get("cost", 0):.4f}</td></tr>' for model, data in tokens_by_model.items())}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(content, "Usage - Agent Smith")


def get_config_html(config: dict, config_path: str) -> str:
    """Get configuration editor page HTML."""
    content = f"""
    <div class="py-2">
        <h2 class="mb-4"><i class="bi bi-gear"></i> Configuration</h2>
        
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0">Edit Configuration</h5>
                <span class="text-muted">{config_path}</span>
            </div>
            <div class="card-body">
                <form action="/config/save" method="post">
                    <div class="mb-3">
                        <textarea name="config" class="form-control font-monospace" rows="20" style="font-size: 0.875rem;">{json.dumps(config, indent=2)}</textarea>
                    </div>
                    <div class="d-flex gap-2">
                        <button type="submit" class="btn btn-primary">
                            <i class="bi bi-save"></i> Save
                        </button>
                        <a href="/config" class="btn btn-outline-secondary">
                            <i class="bi bi-arrow-clockwise"></i> Reset
                        </a>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(content, "Configuration - Agent Smith")


def get_keys_html(keys: list) -> str:
    """Get API keys management page HTML."""
    keys_html = ""
    for key in keys:
        keys_html += f"""
        <tr>
            <td><i class="bi bi-key"></i> {key.get('name', '')}</td>
            <td><code>{key.get('key', '')}</code></td>
            <td>
                <form method="post" action="/keys/delete" class="d-inline">
                    <input type="hidden" name="name" value="{key.get('name', '')}">
                    <button type="submit" class="btn btn-sm btn-outline-danger" onclick="return confirm('Delete this key?')">
                        <i class="bi bi-trash"></i>
                    </button>
                </form>
            </td>
        </tr>"""

    content = f"""
    <div class="py-2">
        <h2 class="mb-4"><i class="bi bi-key"></i> API Keys</h2>
        
        <div class="row">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Add API Key</h5>
                    </div>
                    <div class="card-body">
                        <form action="/keys/add" method="post">
                            <div class="mb-3">
                                <label class="form-label">Provider</label>
                                <select name="name" class="form-select">
                                    <option value="openai">OpenAI</option>
                                    <option value="anthropic">Anthropic</option>
                                    <option value="ollama">Ollama</option>
                                    <option value="google">Google</option>
                                </select>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">API Key</label>
                                <input type="password" name="key" class="form-control" required>
                            </div>
                            <button type="submit" class="btn btn-primary">
                                <i class="bi bi-plus"></i> Add Key
                            </button>
                        </form>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Environment Variables</h5>
                    </div>
                    <div class="card-body">
                        <p class="text-muted">You can also set API keys via environment variables:</p>
                        <div class="code-block">
<pre>OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OLLAMA_BASE_URL=http://localhost:11434</pre>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="card mt-4">
            <div class="card-header">
                <h5 class="mb-0">Stored Keys</h5>
            </div>
            <div class="card-body">
                <table class="table">
                    <thead>
                        <tr>
                            <th>Provider</th>
                            <th>Key</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {keys_html if keys_html else '<tr><td colspan="3" class="text-center text-muted">No API keys stored</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page(content, "API Keys - Agent Smith")


def get_settings_html() -> str:
    """Get settings page HTML."""
    content = """
    <div class="py-2">
        <h2 class="mb-4"><i class="bi bi-gear"></i> Settings</h2>
        
        <div class="row">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">LLM Provider</h5>
                    </div>
                    <div class="card-body">
                        <form>
                            <div class="mb-3">
                                <label class="form-label">Default Provider</label>
                                <select class="form-select">
                                    <option>OpenAI</option>
                                    <option>Anthropic</option>
                                    <option>Ollama</option>
                                    <option>LM Studio</option>
                                </select>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Default Model</label>
                                <select class="form-select">
                                    <option>gpt-4o</option>
                                    <option>gpt-3.5-turbo</option>
                                    <option>claude-3-5-sonnet</option>
                                </select>
                            </div>
                            <button type="submit" class="btn btn-primary">Save</button>
                        </form>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Context Settings</h5>
                    </div>
                    <div class="card-body">
                        <form>
                            <div class="mb-3">
                                <label class="form-label">Context Strategy</label>
                                <select class="form-select">
                                    <option>Sliding Window</option>
                                    <option>Summary</option>
                                    <option>Importance</option>
                                </select>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Max Tokens</label>
                                <input type="number" class="form-control" value="8000">
                            </div>
                            <button type="submit" class="btn btn-primary">Save</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="card mt-4">
            <div class="card-header">
                <h5 class="mb-0">About</h5>
            </div>
            <div class="card-body">
                <p><strong>Agent Smith</strong> - Autonomous AI Agent</p>
                <p class="text-muted">Version 0.1.0</p>
                <a href="https://github.com/daedalus/nanocode" class="btn btn-outline-secondary btn-sm">
                    <i class="bi bi-github"></i> GitHub
                </a>
            </div>
        </div>
    </div>
    """
    return render_page(content, "Settings - Agent Smith")


def get_tools_html(tools: list) -> str:
    """Get tools page HTML."""
    tools_html = ""
    for tool in tools:
        tools_html += f"""
        <div class="col-md-6">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title"><i class="bi bi-plug"></i> {tool.get('name', '')}</h5>
                    <p class="card-text text-muted">{tool.get('description', '')}</p>
                </div>
            </div>
        </div>"""

    content = f"""
    <div class="py-2">
        <h2 class="mb-4"><i class="bi bi-plug"></i> Available Tools</h2>
        
        <div class="row">
            {tools_html if tools_html else '<div class="col-12 text-center text-muted">No tools available</div>'}
        </div>
    </div>
    """
    return render_page(content, "Tools - Agent Smith")
