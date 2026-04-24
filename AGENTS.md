# AGENTS.md

This file provides context for coding agents working on this codebase.

## Project Overview

**nanocode** is an autonomous AI agent for console with advanced tool use, multi-provider LLM support, planning capabilities, and efficient context management.

- **Version**: 0.1.0.1
- **Python**: 3.11+
- **License**: MIT

## Key Commands

```bash
# Run tests
python3 -m pytest tests/ -v
python3 -m pytest tests/unit/ -v          # Fast unit tests
python3 -m pytest tests/functional/ -v     # Full system tests

# Lint & Type Check
ruff check nanocode/
ruff check tests/
mypy nanocode/

# Install
pip install -e .
pip install -e ".[dev,test,lint]"  # Full dev setup
pip install -e ".[tui]"          # With Textual TUI
```

## TUI Development

Always verify the TUI loads correctly after making changes:

```bash
# Verify syntax
python3 -m py_compile nanocode/tui/app.py

# Test import
python3 -c "from nanocode.tui.app import App"
```

## Architecture

```
nanocode/
├── core.py              # Main agent loop
├── config.py           # Configuration management
├── state.py           # State machine
├── context.py         # Context management with compaction
├── llm/             # Multi-provider LLM layer
│   ├── base.py      # Base classes (LLMBase, Message, ToolCall)
│   ├── registry.py  # Model registry from models.dev
│   ├── router.py    # Provider router
│   └── providers/   # Provider implementations (openai, anthropic, ollama, etc.)
├── tools/           # Tool system
├── mcp/             # MCP protocol client
├── lsp/             # LSP client
├── planning/        # Task planning engine
├── agents/          # Multi-agent system & permissions
├── acp/             # ACP (Agent Client Protocol) server
├── server/          # HTTP server for remote operation
├── cli/             # Console interface
├── tui/            # Textual TUI
├── skills/          # Skills system
├── snapshot/        # Git-based snapshots
└── storage/         # SQLite persistence
```

## Configuration

Edit `config.yaml`:

```yaml
llm:
  default_provider: opencode
  default_model: "big-pickle"
  providers:
    opencode:
      api_key: public
      base_url: https://opencode.ai/zen/v1

context:
  strategy: sliding_window  # or summary, importance
  max_tokens: 8000
  preserve_system: true
  preserve_last_n: 6

planning:
  max_steps: 20
  checkpoint_enabled: true
```

## Important Patterns

### LLM Provider Pattern
```python
from nanocode.llm import create_llm_from_model_id
llm, config = await create_llm_from_model_id("openai/gpt-4o")
```

### Tool Execution
```python
from nanocode.tools import ToolExecutor
executor = ToolExecutor(config)
result = await executor.execute("bash", {"command": "ls -la"})
```

### Agent Usage
```python
from nanocode.core import AutonomousAgent
from nanocode.config import Config
config = Config("config.yaml")
agent = AutonomousAgent(config)
response = await agent.process_input("Hello")
```

## Style Guidelines

- **Line length**: 88 chars (ruff default)
- **Type annotations**: Required for public APIs, optional for private
- **Docstrings**: Google style
- **Async**: Use `async`/`await` for all I/O operations
- **Error handling**: Specific exceptions, never bare `except`

## Code Quality

- **Ruff rules**: E, F, W, I, UP, ANN, TCH, N, C4, ARG
- **Coverage target**: 80% minimum
- **Test framework**: pytest with asyncio support

## Environment Variables

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-...
OLLAMA_BASE_URL=http://localhost:11434
AGENT_CONFIG=config.yaml
HTTP_PROXY=http://localhost:8080
```

## Special Features

### Skills System
Custom commands in `.nanocode/skills/<skill-name>/SKILL.md`:
```markdown
---
name: skill_name
description: Description
---

# Skill Content
```

### MCP Integration
```yaml
mcp:
  servers:
    exa:
      url: https://mcp.exa.ai/mcp?tools=web_search_exa,deep_search_exa,get_code_context_exa
      enabled: True
```

### ACP Server
Start with `--acp` for IDE integration (Zed, VSCode).

## Dependencies

Core: httpx, pyyaml, sqlalchemy, aiosqlite, python-frontmatter, watchdog, aiohttp, PyGithub

Dev: ruff, mypy, hatch, pytest, pytest-asyncio, pytest-cov, hypothesis

TUI: textual>=0.90.0