"""Negative prompting: code quality contract."""

BLOCK = """
## Code Quality Contract

Before submitting any code change, verify:

1. **Tests pass**: Run the relevant test suite. If tests don't exist for the
   module being changed, add them.
2. **No type errors**: Run ``mypy`` (or equivalent) on changed files.
3. **No lint warnings**: Run ``ruff`` (or equivalent) on changed files.
4. **No regressions**: Ensure existing tests still pass.
5. **No secrets**: Never commit API keys, tokens, passwords, or credentials.
   Use environment variables or a config file.
6. **No overly broad exception handlers**: Catch specific exceptions, not
   ``Exception`` or ``BaseException``.
7. **No unbounded loops/recursion**: Every loop and recursion must have a
   guaranteed termination condition.
"""
