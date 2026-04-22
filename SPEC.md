# SPEC.md — nanocode

## Purpose

Nanocode is an autonomous AI agent for console with advanced tool use. It supports multiple LLM providers (OpenAI, Anthropic, Ollama, and many others), planning capabilities, efficient context management, and integrates with IDEs via ACP (Agent Client Protocol). The project enables users to interact with AI agents through a CLI, HTTP server, or directly as a Python library.

## Scope

### What IS in scope
- Multi-provider LLM support (OpenAI, Anthropic, Ollama, LM Studio, Google, Cohere, Mistral, Together, Groq, DeepInfra, Fireworks, OpenRouter, OpenCode)
- Programmatic tool registration and execution system
- Built-in tools: bash, bash_session, read, write, edit, glob, grep, ls, webfetch, websearch, todo, sed, diff, github
- MCP (Model Context Protocol) client support
- LSP (Language Server Protocol) client support
- ACP (Agent Client Protocol) server for IDE integration
- HTTP server with authentication for remote operation
- mDNS service discovery
- Multi-agent system with permission controls
- Subagent session management (/tasks, /kill commands)
- Persistent SQLite session storage
- File watcher for cache invalidation
- Skills system for custom commands
- Git-based snapshot/revert functionality
- **Hook system for lifecycle events (PreToolUse, PostToolUse, SessionStart, etc.)**

### What is NOT in scope
- GUI application (CLI-only)
- Plugin system beyond MCP and skills
- Built-in LLM provider API key management (users must provide their own)
- Cloud deployment infrastructure
- Mobile support

## Public API / Interface

### CLI Commands
- `python main.py` — Start interactive CLI mode
- `python main.py --serve` — Start HTTP server
- `python main.py --acp` — Start ACP server for IDE integration
- `python main.py --admin` — Start admin console
- `python main.py --install-skills <name>` — Install a skill

### Python API

#### `nanocode.config.Config`
```python
class Config:
    def __init__(self, config_path: str = "config.yaml") -> None: ...
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
```

#### `nanocode.core.AutonomousAgent`
```python
class AutonomousAgent:
    def __init__(self, config: Config) -> None: ...
    async def process_input(self, user_input: str) -> str: ...
    async def execute_task(self, task: str) -> str: ...
```

#### `nanocode.llm.create_llm_from_model_id`
```python
async def create_llm_from_model_id(model_id: str) -> tuple[LLMBase, Config]: ...
```

### Configuration (config.yaml)
- `llm.default_provider` — Default LLM provider
- `llm.use_model_registry` — Enable models.dev integration
- `llm.default_model` — Default model ID
- `llm.providers.<provider>.api_key` — Provider API key
- `llm.providers.<provider>.model` — Provider model name
- `context.strategy` — Context management strategy
- `planning.max_steps` — Maximum planning steps
- `storage.enabled` — Enable SQLite storage

## Data Formats

### Config File (YAML)
```yaml
llm:
  default_provider: openai
  providers:
    openai:
      api_key: ${OPENAI_API_KEY}
      model: gpt-4o
```

### Session Storage (SQLite)
- Tables: sessions, messages, projects
- Location: configurable via `storage.db_path`

### MCP Server Configuration
```yaml
mcp:
  servers:
    name:
      type: stdio|sse
      command: ...
      args: [...]
      env: {}
```

### Skills (Markdown with YAML frontmatter)
```markdown
---
name: skill_name
description: Description
---

# Skill Content
```

### Hooks (JSON or Python)
```json
{
  "name": "hook-name",
  "event": "PreToolUse",
  "pattern": "read|write",
  "type": "command",
  "command": "echo 'Running hook'",
  "action_on_result": "allow"
}
```

Or Python hooks in `.nanocode/hooks/*.py`:
```python
from nanocode.hooks import Hook, HookContext, HookResult, HookAction, HookEvent

class MyHook(Hook):
    def __init__(self):
        super().__init__("my-hook", HookEvent.PRE_TOOL_USE, "My custom hook")

    async def run(self, context: HookContext) -> HookResult:
        # Custom logic
        return HookResult(action=HookAction.ALLOW)
```

Hook events: `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SessionStart`, `SessionEnd`, `Error`
Hook actions: `allow`, `deny`, `warn`, `modify`, `stop`

## Edge Cases

1. **Invalid API key** — Raise authentication error with helpful message
2. **Provider rate limiting** — Implement exponential backoff retry
3. **Context overflow** — Apply compaction strategy (sliding_window, summary, importance)
4. **Tool execution timeout** — Timeout after configurable duration, return partial result
5. **MCP server connection failure** — Graceful degradation, log error, continue without tool
6. **File watcher permission denied** — Skip directory, continue with available paths
7. **Invalid model ID format** — Raise ValueError with supported format examples
8. **Network proxy configuration** — Respect proxy settings, handle connection errors
9. **Session storage corruption** — Detect and offer to reset, continue without persistence
10. **Empty user input** — Ignore and prompt again

## Performance & Constraints

- Python 3.11+ required
- Async/await for I/O operations
- Token-aware context management to stay within model limits
- Parallel tool execution where supported
- Lazy loading of heavy dependencies (LSP, MCP)
- Maximum planning steps configurable (default: 20)
- Tool execution timeout configurable (default: 120s)

## Version

Current: 0.1.0.1

## Changelog

See CHANGELOG.md for detailed version history.