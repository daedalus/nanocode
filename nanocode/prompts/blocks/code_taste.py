"""Negative prompting: code taste, style, and anti-patterns.

Inserted into system prompt to discourage common AI-generated code smells.
"""

BLOCK = """
## Code Taste & Anti-Patterns

The following patterns are **prohibited** unless there is an exceptional reason:

- **No tutorial docstrings**: Do NOT write docstrings that explain basic concepts
  ("A function that adds two numbers"). Instead write *why* something exists.
- **No manager-of-managers pattern**: Avoid OverlordManager, ServiceManager,
  HandlerFactory, etc. Prefer flat, explicit wiring.
- **No generic names**: Avoid "data", "info", "helper", "util", "manager",
  "processor", "handler" as module/class/function names. Name things after
  WHAT they do, not what category they belong to.
- **No builder-over-constructor**: Do not replace a simple constructor with a
  builder/factory pattern unless there are >5 parameters with complex defaults.
- **No premature abstraction**: Do not extract interfaces, base classes, or
  abstract methods unless there are at least 3 concrete implementations.
- **No commented-out code**: Remove dead code entirely. Git history exists for
  recovery.
- **No print-debugging**: Use proper logging instead of print() statements.
- **No optional-typing-avoidance**: Always add type annotations to function
  signatures. Use ``Any`` sparingly.
- **No deep nesting**: Maximum 3 levels of indentation. Extract inner blocks
  into named functions.
"""
