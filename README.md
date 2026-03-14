# Autonomous Agent

A fully autonomous AI agent for console with advanced tool use, multi-provider LLM support, planning capabilities, and efficient context management.

Experimental. It might be buggy.

## Features

### Multi-Provider LLM Support
- **OpenAI** - GPT-4, GPT-4o, GPT-3.5 Turbo
- **Anthropic** - Claude 3.5 Sonnet, Claude 3
- **Ollama** - Local models (Llama3, Mistral, etc.)
- **LM Studio** - Any OpenAI-compatible local API
- Works with any OpenAI-compatible endpoint

### Models.dev Integration
- Access to 75+ providers and 2000+ models via [models.dev](https://models.dev)
- Model ID format: `provider/model` (e.g., `openai/gpt-4o`, `anthropic/claude-sonnet-4-5`)
- Automatic provider inference from model names
- Special **opencode** provider for free models (uses "public" key, filters paid models)

### Advanced Tool System
- Programmatic tool registration and execution
- Built-in tools: `bash`, `read`, `write`, `edit`, `glob`, `grep`, `ls`, `webfetch`, `websearch`, `todo`
- Tool result validation and error handling
- Parallel tool execution support
- MCP tool integration

### Multi-Agent System
- Build, Plan, General, and Explore agents with different permission levels
- Fine-grained permission controls: `allow`, `deny`, `ask`
- Agent switching support
- Subagent support for specialized tasks

### Permission System
- Tool execution control with allow/deny/ask actions
- Pattern-based permission rules
- Callback-based user approval prompts

### ACP (Agent Client Protocol)
- Protocol-compliant ACP server for IDE integration
- Works with Zed, VSCode, and other ACP clients
- JSON-RPC over stdio communication
- Session management: create, load, prompt

### HTTP Server
- REST API for remote agent operation
- Session management via HTTP endpoints
- Basic authentication support
- mDNS integration for service discovery

### mDNS Service Discovery
- Publish agent services on local network
- Auto-discover remote agents
- Uses `_agent-smith._tcp.local.` service type

### Retry Logic
- Exponential backoff for API calls
- Respects `retry-after` headers
- Handles HTTP 500, 503, and rate limit errors
- Context overflow errors are NOT retried
- Configurable via RetryConfig

### MCP (Model Context Protocol)
- Full MCP protocol client
- Two connection types: **stdio** and **SSE** (HTTP)
- Built-in servers: Filesystem, Git
- Connect to any MCP server

```yaml
mcp:
  servers:
    # Stdio-based server (local)
    filesystem:
      type: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      env:
        NODE_ENV: production
    
    # SSE-based server (remote)
    remote:
      type: sse
      url: http://localhost:8080/mcp
      headers:
        Authorization: Bearer token
```

### LSP (Language Server Protocol)
- Out-of-the-box LSP support for code intelligence
- Auto-detection of LSP servers based on file extensions
- Built-in support for: pyright, typescript, deno, gopls, rust-analyzer, clangd, jedi-language-server, omnisharp
- LSP tool operations: `definition`, `references`, `hover`, `completion`, `symbols`, `workspace_symbol`, `implementation`, `diagnostics`
- Configurable LSP servers in `config.yaml`

### Enhanced Context Management
- Message parts: text, reasoning, tool_call, tool_result
- Automatic compaction when context exceeds limits
- Scrap-based storage for large tool outputs
- Per-model context limits from models.dev
- Multi-part system prompts

### Multimodal Support
- Image understanding (vision models)
- Document extraction (PDF, DOCX, TXT)
- Audio hooks (TTS/STT ready)

### Efficient Context Management
- Token-aware message handling
- Three strategies: Sliding Window, Summary, Importance
- Automatic tool result truncation
- Context persistence

### Persistent Session Storage
- SQLite database for storing sessions, messages, and projects
- Automatic session history across restarts
- Works with the ContextManager for seamless persistence
- Configure via `config.yaml`:

```yaml
storage:
  enabled: true
  db_path: ~/.agent_smith/data/agent_smith.db
```

### Skills System
- Custom commands defined in `.agent/skills/<skill-name>/skill.md`
- Each skill is a markdown file with YAML frontmatter
- Skills are automatically discovered and registered as tools

Example skill file `.agent/skills/hello/skill.md`:
```markdown
---
name: hello
description: A simple hello world skill
---

# Hello Skill

This skill returns a greeting.
```

Use `/skills` CLI command to list available skills.

### File Watcher
- Real-time file system monitoring using the `watchdog` library
- Automatically invalidates file caches when files are modified externally
- Supports cross-platform file watching (Linux: inotify, macOS: FSEvents, Windows: ReadDirectoryChangesW)
- Configurable ignore patterns for directories and file types
- Events: `add`, `change`, `unlink` (create, modify, delete)

```yaml
file_watcher:
  enabled: true
  ignore:
    - .git
    - __pycache__
```

### GitHub Integration
- GitHub OAuth and Personal Access Token (PAT) authentication
- GitHub App authentication support
- Pull Request operations: list, create, view, merge, close
- Issue management: list, create, view
- Comment on issues and PRs
- Repository information lookup
- Uses PyGithub library

```yaml
github:
  token: ${GITHUB_TOKEN}  # Set via environment variable
  # app_id: ""              # For GitHub App auth
  # app_private_key: ""     # For GitHub App auth
  # installation_id: ""     # For GitHub App auth
```

The agent can use the `github` tool for GitHub operations:

### Snapshot/Revert
- Capture and rollback changes using Git
- Uses a separate git repository for snapshot tracking
- Creates lightweight snapshots using `git write-tree`

```yaml
snapshot:
  enabled: true
  prune_days: 7
```

CLI commands:
- `/snapshot` - Create a new snapshot
- `/snapshots` - List available snapshots
- `/revert <hash>` - Revert to a snapshot (use 'latest' for most recent)

## Installation

```bash
# Clone and install dependencies
pip install -r requirements.txt
```

## Configuration

Edit `config.yaml`:

```yaml
llm:
  default_provider: openai
  use_model_registry: true  # Use models.dev for model discovery
  default_model: "openai/gpt-4o"  # Model ID format: provider/model
  
  providers:
    openai:
      api_key: ${OPENAI_API_KEY}
      model: gpt-4o
    
    ollama:
      base_url: http://localhost:11434
      model: llama3

context:
  strategy: sliding_window
  max_tokens: 8000

planning:
  max_steps: 20
  max_retries: 3
  checkpoint_enabled: true

# LSP Configuration (optional - auto-detects available servers)
lsp:
  pyright:
    command: ["pyright", "--langserver", "-v"]
  typescript:
    command: ["typescript-language-server", "--stdio"]
```

#### Using the LSP Tool

The agent can use the `lsp` tool for code intelligence:

```python
# Via the agent's tool system
result = await tool_executor.execute("lsp", {
    "operation": "definition",
    "file_path": "/path/to/file.py",
    "line": 10,
    "character": 5,
})

# Other operations:
# - "references" - Find all references to a symbol
# - "hover" - Get hover information
# - "completion" - Get completions at position
# - "symbols" - List all symbols in a file
# - "workspace_symbol" - Search symbols across workspace
# - "implementation" - Find implementations
# - "diagnostics" - Get diagnostics/errors
```

## Usage

### Interactive Mode (CLI)

```bash
python3 main.py
```

### HTTP Server Mode

```bash
# Start HTTP server on default port (8080)
python3 main.py --serve

# With authentication
python3 main.py --serve --serve-auth "admin:password"

# With mDNS discovery
python3 main.py --serve --mdns

# Custom host and port
python3 main.py --serve --serve-host "0.0.0.0" --serve-port 8080
```

API endpoints:
- `GET /health` - Health check
- `GET /sessions` - List sessions
- `POST /sessions` - Create session
- `POST /sessions/{id}/prompt` - Send prompt

### Admin Console

```bash
# Start admin console on default port (7890)
python3 main.py --admin

# Custom host and port
python3 main.py --admin --admin-host "127.0.0.1" --admin-port 7890
```

The admin console provides a local web interface for:
- **Dashboard** - Overview with usage statistics and recent sessions
- **Sessions** - Browse and manage conversation sessions
- **Usage** - View token usage and cost analytics
- **Config** - Edit configuration via web interface
- **API Keys** - Manage provider API keys

Access at: http://127.0.0.1:7890

### ACP Server Mode (for Zed, VSCode)

```bash
# Start ACP server (for IDE integration)
python3 main.py --acp

# In specific directory
python3 main.py --acp --cwd /path/to/project
```

Works with Zed's agent configuration:
```json
{
  "agent_servers": {
    "AgentSmith": {
      "command": "python",
      "args": ["main.py", "--acp"]
    }
  }
}
```

### NCurses GUI

```bash
python3 main.py --gui ncurses
```

Features:
- Full-screen terminal interface
- Sidebar with tools
- Chat panel with scrollback
- Real-time token usage
- Keyboard navigation (Tab to switch panels)

Controls:
- `Tab` - Switch between panels
- `↑/↓` - Navigate sidebar/chat
- `Enter` - Send message
- `Ctrl+C` - Quit
- `Ctrl+L` - Clear screen

Special Commands (require '/' prefix):
- `/help` - Show help
- `/exit/quit` - Exit the agent
- `/clear` - Clear terminal
- `/history` - Show command history
- `/tools` - List available tools
- `/plan <task>` - Execute task with planning
- `/checkpoint` - List saved checkpoints
- `/resume <id>` - Resume from checkpoint

Regular Input:
- Any text NOT starting with '/' is sent directly to the AI agent for processing

### Programmatic Usage

```python
from agent_smith.core import AutonomousAgent
from agent_smith.config import Config

config = Config("config.yaml")
agent = AutonomousAgent(config)

# Simple interaction
response = await agent.process_input("Hello, what can you do?")

# Long-horizon task with planning
result = await agent.execute_task("Create a web scraper for news articles")
```

### Using with Different Providers

```python
# Use Ollama
config.set("llm.default_provider", "ollama")

# Use LM Studio
config.set("llm.default_provider", "lm-studio")
config.set("llm.providers.lm-studio.base_url", "http://localhost:1234/v1")
```

### Using Model IDs

The agent supports the `provider/model` format for flexible model selection:

```python
from agent_smith.llm import create_llm_from_model_id

# Use any model from models.dev
llm, config = await create_llm_from_model_id("openai/gpt-4o")
llm, config = await create_llm_from_model_id("anthropic/claude-sonnet-4-5")
llm, config = await create_llm_from_model_id("groq/llama-3-70b")

# Provider is inferred from model name
llm, config = await create_llm_from_model_id("gpt-4o")        # → OpenAI
llm, config = await create_llm_from_model_id("claude-3-5-sonnet")  # → Anthropic
llm, config = await create_llm_from_model_id("llama-3")        # → Ollama

# Use the free opencode provider (no API key needed)
llm, config = await create_llm_from_model_id("opencode/gpt-5-nano")
```

## Architecture

```
agent/
├── core.py           # Main agent loop
├── config.py         # Configuration management
├── state.py         # State machine
├── context.py       # Context management (with compaction)
├── llm/             # Multi-provider LLM layer
├── tools/           # Tool system
├── mcp/             # MCP protocol client
├── lsp/             # LSP client
├── planning/        # Task planning engine
├── multimodal/      # Vision, audio, documents
├── agents/          # Multi-agent system & permissions
├── acp/             # ACP (Agent Client Protocol) server
├── server/          # HTTP server for remote operation
├── mdns/            # mDNS service discovery
├── retry/           # Retry logic with backoff
├── skills/          # Skills system
├── snapshot/        # Git-based snapshots
└── cli/             # Console interface
```

## Context Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `sliding_window` | Keep recent messages within token limit | General use |
| `summary` | Summarize old messages via LLM | Long conversations |
| `importance` | Keep important + recent messages | Task-focused work |

## Environment Variables

```bash
OPENAI_API_KEY=sk-...        # OpenAI API key
ANTHROPIC_API_KEY=sk-...     # Anthropic API key  
OLLAMA_BASE_URL=http://localhost:11434
OPENCODE_ZEN_API_KEY=sk-...  # OpenCode Zen API key (optional)
AGENT_CONFIG=config.yaml      # Custom config path
```

## Running Tests

This tool relies heavily on testing.

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run unit tests only (fast, no external dependencies)
python3 -m pytest tests/unit/ -v

# Run functional tests (slower, tests full system)
python3 -m pytest tests/functional/ -v

# Run specific test file
python3 -m pytest tests/unit/test_tools.py -v
```

## License

MIT
