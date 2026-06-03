"""Negative prompting: architecture and design guardrails."""

BLOCK = """
## Architecture Guardrails

- **No cyclical imports**: Modules must form a DAG. If A imports B and B
  imports A, restructure.
- **No god objects**: A class with >300 lines or >10 methods is a red flag.
  Split by responsibility.
- **No hidden state**: Avoid module-level mutable state. Use explicit
  dependency injection or configuration objects.
- **No exception swallowing**: Never use ``except: pass``. Always log or
  re-raise. At minimum, log the exception.
- **No magic numbers**: Every literal value (except 0, 1, empty string) must
  be a named constant.
- **No boolean traps**: Functions should not accept bare ``bool`` parameters
  that change behavior. Use enums or keyword-only arguments.
"""
