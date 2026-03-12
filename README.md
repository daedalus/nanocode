# Autonomous Agent

A fully autonomous AI agent for console with advanced tool use, multi-provider LLM support, planning capabilities, and efficient context management.

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

### Planning & Execution
- Task decomposition into executable steps
- Checkpoint-based execution for long-horizon tasks
- Automatic replanning on failures
- Progress monitoring and evaluation

### MCP (Model Context Protocol)
- Full MCP protocol client
- Built-in servers: Filesystem, Git
- Connect to any MCP server

### LSP (Language Server Protocol)
- LSP client for code intelligence
- Completions, definitions, diagnostics
- Support for pyright, rust-analyzer, etc.

### Multimodal Support
- Image understanding (vision models)
- Document extraction (PDF, DOCX, TXT)
- Audio hooks (TTS/STT ready)

### Efficient Context Management
- Token-aware message handling
- Three strategies: Sliding Window, Summary, Importance
- Automatic tool result truncation
- Context persistence

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
```

## Usage

### Interactive Mode (CLI)

```bash
python3 main.py
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

Commands:
- `help` - Show help
- `exit/quit` - Exit the agent
- `clear` - Clear terminal
- `history` - Show command history
- `tools` - List available tools
- `plan <task>` - Execute task with planning
- `checkpoint` - List saved checkpoints
- `resume <id>` - Resume from checkpoint

### Programmatic Usage

```python
from agent.core import AutonomousAgent
from agent.config import Config

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
from agent.llm import create_llm_from_model_id

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
├── state.py          # State machine
├── context.py        # Context management
├── llm/             # Multi-provider LLM layer
├── tools/           # Tool system
├── mcp/             # MCP protocol client
├── lsp/             # LSP client
├── planning/        # Task planning engine
├── multimodal/      # Vision, audio, documents
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
