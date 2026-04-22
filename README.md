# Autonomous Agent

A fully autonomous AI agent for console with advanced tool use, multi-provider LLM support, planning capabilities, and efficient context management.

Experimental. It might be buggy.

## Features

### Multi-Provider LLM Support
- **OpenAI** - GPT-4, GPT-4o, GPT-3.5 Turbo
- **Anthropic** - Claude 3.5 Sonnet, Claude 3
- **Ollama** - Local models (Llama3, Mistral, etc.)
- **LM Studio** - Any OpenAI-compatible local API
- **Google** - Gemini models
- **Cohere** - Command models
- **Mistral** - Mistral models
- **Together** - Llama, Mistral, and more
- **Groq** - Fast inference
- **DeepInfra** - Various open models
- **Fireworks** - Fast inference
- **OpenRouter** - Unified access to many providers
- Works with any OpenAI-compatible endpoint

### Models.dev Integration
- Access to 75+ providers and 2000+ models via [models.dev](https://models.dev)
- Model ID format: `provider/model` (e.g., `openai/gpt-4o`, `anthropic/claude-sonnet-4-5`)
- Automatic provider inference from model names
- Special **opencode** provider for free models (uses "public" key, filters paid models)

### Advanced Tool System
- Programmatic tool registration and execution
- Built-in tools: `bash`, `bash_session`, `read`, `write`, `edit`, `glob`, `grep`, `ls`, `webfetch`, `websearch`, `todo`, `sed`, `diff`
- Tool result validation and error handling
- Parallel tool execution support
- MCP tool integration

### Multi-Agent System
- Build, Plan, General, and Explore agents with different permission levels
- Fine-grained permission controls: `allow`, `deny`, `ask`
- Agent switching support (`/agent <name>` and `/agents` commands)
- Subagent support for specialized tasks
- Doom loop detection with DENY permission

### TUI (Terminal User Interface)
- Textual-based terminal UI with Gruvbox dark theme
- Command palette (press F1 to open)
- Keyboard shortcuts: Enter (send), Ctrl+L (clear), Escape (quit), Ctrl+C (interrupt)

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
  db_path: ~/.nanocode/data/nanocode.db
```

### Skills System
- Custom commands defined in `.nanocode/skills/<skill-name>/skill.md`
- Each skill is a markdown file with YAML frontmatter
- Skills are automatically discovered and registered as tools

Example skill file `.nanocode/skills/hello/skill.md`:
```markdown
---
name: hello
description: A simple hello world skill
---

# Hello Skill

This skill returns a greeting.
```

Use `/skills` CLI command to list available skills.

### Hook System
Custom hooks for lifecycle events that run at specific times during agent execution.

```bash
# Create hooks directory
mkdir -p .nanocode/hooks
```

#### JSON Hooks
Create `.nanocode/hooks/*.json` files:

```json
[
  {
    "name": "security-block-env",
    "event": "PreToolUse",
    "description": "Block env tool access",
    "pattern": "env",
    "type": "command",
    "command": "exit 1",
    "action_on_result": "deny"
  },
  {
    "name": "log-all-tools",
    "event": "PostToolUse",
    "description": "Log tool executions",
    "type": "command",
    "command": "echo 'Tool executed: $NANO_HOOK_TOOL' >> /tmp/hooks.log",
    "action_on_result": "allow"
  }
]
```

#### Python Hooks
Create `.nanocode/hooks/*.py` files:

```python
from nanocode.hooks import Hook, HookContext, HookResult, HookAction, HookEvent

class SecurityHook(Hook):
    def __init__(self):
        super().__init__("security-hook", HookEvent.PRE_TOOL_USE, "Block dangerous operations")

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.tool_name in ["env", "get_env"]:
            return HookResult(action=HookAction.DENY, message="Environment access denied")
        return HookResult(action=HookAction.ALLOW)
```

**Hook Events:**
- `PreToolUse` - Before a tool executes (can block or modify args)
- `PostToolUse` - After a tool executes (for logging)
- `SessionStart` - When a session begins
- `SessionEnd` - When a session ends
- `Notification` - When a notification is sent
- `Error` - When an error occurs

**Hook Actions:**
- `allow` - Continue execution
- `deny` - Block tool execution
- `warn` - Allow with warning
- `modify` - Modify tool arguments
- `stop` - Stop processing further hooks

### Built-in Skills

#### Red Teaming Skill
Comprehensive security testing skill for red teaming code, LLM systems, and APIs.

```bash
# Install the redteaming skill
python3 main.py --install-skills redteaming

# Install all available skills
python3 main.py --install-skills all
```

The skill triggers on requests like:
- "red team this code"
- "find vulnerabilities in this agent"
- "test my LLM app for jailbreaks"
- "check for prompt injection"
- "security audit"

Covers:
- Static code security audit (OWASP + CWE)
- LLM/AI system red teaming (prompt injection, jailbreaks)
- API/service penetration testing
- Code agent safety testing
- Modern attack techniques (Best-of-N, GCG, JBFuzz, Crescendo)

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
  
  # Proxy configuration for HTTP requests
  # proxy: http://localhost:8080
   
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

### Command-Line Options

```
nanocode [-h] [--config CONFIG] [--provider PROVIDER] [--model MODEL]
         [--no-planning] [--verbose] [--thinking] [--gui {textual,cli}]
         [--acp] [--serve] [--serve-host SERVE_HOST] [--serve-port SERVE_PORT]
         [--serve-auth SERVE_AUTH] [--mdns] [--admin] [--admin-host ADMIN_HOST]
         [--admin-port ADMIN_PORT] [--cwd CWD] [--install-skills SKILL]
         [--proxy PROXY] [--no-proxy] [--user-agent USER_AGENT]
         [--show-messages] [--prompt PROMPT] [--debug-logging]
         [--log-file LOG_FILE] [--cache]
```

Key options:
- `-g, --gui {textual,cli}` - Choose UI mode (default: textual)
- `--thinking, -t` - Show thinking/reasoning blocks
- `-v, --verbose` - Verbose output
- `--proxy PROXY` - HTTP proxy for API requests
- `--model, -m MODEL` - Model to use
- `--provider, -p PROVIDER` - LLM provider (openai, anthropic, ollama, etc.)
- `--acp` - Start ACP server for IDE integration
- `--serve` - Start HTTP server for remote operation

### Interactive Mode (CLI or TUI)

```bash
python3 main.py
python3 main.py -g textual  # Use TUI (Textual) mode
```

#### TUI Features

The Textual TUI provides an enhanced terminal interface with:
- **Command Palette** - Press `F1` to open the command palette
- **Gruvbox Dark Theme** - Beautiful terminal colors
- **Keyboard Shortcuts**:
  - `Enter` - Send message
  - `Ctrl+L` - Clear output
  - `Escape` - Quit
  - `Ctrl+C` - Interrupt current operation

#### Install Skills

```bash
# Install a specific skill
python3 main.py --install-skills redteaming

# Install all available skills
python3 main.py --install-skills all
```

Special Commands (prefix with '/'):
- `/help` - Show help
- `/exit`, `/quit`, `/q` - Exit the agent
- `/clear`, `/c` - Clear terminal
- `/history` - Show command history
- `/tools` - List available tools
- `/skills` - List available skills
- `/provider` - Select AI provider and model
- `/plan <task>` - Execute task with planning
- `/checkpoint` - List saved checkpoints
- `/resume <id>` - Resume from checkpoint
- `/snapshot` - Create a new snapshot
- `/snapshots` - List available snapshots
- `/revert <hash>` - Revert to a snapshot
- `/trace` - Show last error trace
- `/debug` - Toggle HTTP debug logging
- `/compact` - Compact context (summarize old messages)
- `/show_thinking` - Toggle thinking display
- `/agents` - List available agents
- `/agent <name>` - Switch to a different agent
- `/tasks` - List active subagent sessions
- `/kill <session_id>` - Kill a subagent session

### Command Palette (TUI)

Press `F1` to open the command palette in TUI mode:
- Search/filter commands
- Navigate with arrow keys
- Press Enter to select
- Press Escape to cancel

### Thinking Display

The agent can display thinking/reasoning blocks with visual styling:
- Uses `| Thinking:` prefix with gold ANSI color
- Toggle with `/show_thinking` or `--thinking` flag

### Doom Loop Detection

Prevents infinite exploration loops by detecting:
- Repeated tool call patterns
- Failed iterations without progress
- DENY permission for continuing loops
- Tracks iteration count and tool history

Regular Input:
- Any text NOT starting with '/' is sent directly to the AI agent for processing

### HTTP Server Mode

```bash
# Start HTTP server on default port (8080)
python3 main.py --serve

# With authentication
python3 main.py --serve --serve-auth "admin:password"

# With proxy
python3 main.py --serve --proxy http://localhost:8080

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

### Programmatic Usage

```python
from nanocode.core import AutonomousAgent
from nanocode.config import Config

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
from nanocode.llm import create_llm_from_model_id

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
│   ├── base.py      # Base classes (LLMBase, Message, ToolCall)
│   ├── registry.py  # Model registry from models.dev
│   ├── router.py    # Provider router
│   └── providers/   # Provider implementations
│       ├── openai/  # OpenAI-compatible provider
│       ├── anthropic/  # Anthropic Claude provider
│       ├── ollama/  # Ollama local provider
│       ├── google/  # Google Gemini (OpenAI-compatible)
│       ├── cohere/  # Cohere (OpenAI-compatible)
│       ├── mistral/  # Mistral AI (OpenAI-compatible)
│       ├── together/  # Together AI (OpenAI-compatible)
│       ├── groq/  # Groq (OpenAI-compatible)
│       ├── deepinfra/  # DeepInfra (OpenAI-compatible)
│       ├── fireworks/  # Fireworks AI (OpenAI-compatible)
│       ├── openrouter/  # OpenRouter (OpenAI-compatible)
│       └── lm_studio/  # LM Studio (OpenAI-compatible)
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
HTTP_PROXY=http://localhost:8080  # Proxy for HTTP requests (also via --proxy flag)
ANTHROPY_LICENSE_KEY=...     # Anthropic license key (optional)
```

## ANSI Color Codes

For terminal styling, the agent uses ANSI escape codes:

| Code | Color | Usage |
|------|-------|-------|
| `\033[90m` | Gray | Dim text |
| `\033[91m` | Red | Errors |
| `\033[92m` | Green | Success |
| `\033[93m` | Gold | Thinking |
| `\033[94m` | Blue | Info |
| `\033[95m` | Magenta | Commands |
| `\033[96m` | Cyan | Links |
| `\033[97m` | White | Default |

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
