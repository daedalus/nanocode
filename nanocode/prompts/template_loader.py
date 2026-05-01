"""Jinja2 template loader for system prompts.

Supports template inheritance, partials, and dynamic context injection.
"""

import logging
import os
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template

logger = logging.getLogger(__name__)

# Default template that matches openwarp's structure
DEFAULT_SYSTEM_TEMPLATE = """You are NanoCode, an autonomous AI agent for console.

## Capabilities
You have access to the following capabilities:

### Agents
{{ agents }}

### Tools
{{ tools }}

### Skills
{{ skills }}

### MCP Servers
{{ mcp_servers }}

### LSP Servers
{{ lsp_servers }}

## Context
- Working directory: {{ cwd }}
- Config file: {{ config_file }}
{{ extra_context }}

## Instructions
You are a helpful AI assistant that can execute tasks by using the available tools.
- Always think step-by-step before taking action
- Use tools to gather information and perform actions
- Provide clear, concise responses
- When editing files, always read them first to understand the current content
"""


class PromptTemplateLoader:
    """Loads and renders Jinja2 templates for prompts.

    Similar to openwarp's minijinja-based system but using Jinja2 for Python.
    Supports template inheritance and partials.
    """

    def __init__(self, template_dir: Path | None = None):
        """Initialize the template loader.

        Args:
            template_dir: Directory containing template files.
                          Searches multiple locations if not found.
        """
        self.template_dir = self._find_template_dir(template_dir)
        self.env = self._create_jinja_env()

    def _find_template_dir(self, template_dir: Path | None) -> Path | None:
        """Find the template directory from multiple possible locations."""
        search_paths = []

        # 1. Provided directory
        if template_dir and template_dir.exists():
            return template_dir

        # 2. Current working directory
        try:
            cwd = Path(os.getcwd())
            search_paths.append(cwd / ".system_prompts")
        except OSError:
            pass

        # 3. Package directory
        package_dir = Path(__file__).parent.parent
        search_paths.append(package_dir / ".system_prompts")

        # 4. User config directory
        search_paths.append(Path.home() / ".config" / "nanocode" / "system_prompts")

        for path in search_paths:
            if path.exists() and path.is_dir():
                logger.info(f"Using template directory: {path}")
                return path

        return None

    def _create_jinja_env(self) -> Environment | None:
        """Create Jinja2 environment with template loading."""
        if not self.template_dir:
            return None

        env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Add custom filters if needed
        env.filters["truncate"] = lambda s, length: s[:length] + "..." if s and len(s) > length else s

        return env

    def render(
        self,
        template_name: str = "template.md",
        context: dict[str, Any] | None = None,
    ) -> str:
        """Render a template with the given context.

        Args:
            template_name: Name of the template file (default: template.md)
            context: Variables to pass to the template

        Returns:
            Rendered template string
        """
        context = context or {}

        # If no template directory or template not found, use default
        if not self.env:
            logger.debug("No template directory found, using default template")
            return self._render_default(context)

        try:
            template = self.env.get_template(template_name)
            return template.render(**context)
        except Exception as e:
            logger.warning(f"Failed to render template '{template_name}': {e}")
            return self._render_default(context)

    def _render_default(self, context: dict[str, Any]) -> str:
        """Render the default template with context."""
        try:
            template = Template(DEFAULT_SYSTEM_TEMPLATE)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Failed to render default template: {e}")
            return DEFAULT_SYSTEM_TEMPLATE

    def list_templates(self) -> list[str]:
        """List available templates."""
        if not self.template_dir:
            return []

        templates = []
        for f in self.template_dir.glob("*.md"):
            templates.append(f.name)
        for f in self.template_dir.glob("*.j2"):
            templates.append(f.name)

        return sorted(templates)

    def has_template(self, name: str) -> bool:
        """Check if a template exists."""
        if not self.template_dir:
            return False
        return (self.template_dir / name).exists()


def get_template_loader() -> PromptTemplateLoader:
    """Get a shared template loader instance."""
    return PromptTemplateLoader()


def render_system_prompt(
    agents: str = "",
    tools: str = "",
    skills: str = "",
    mcp_servers: str = "",
    lsp_servers: str = "",
    cwd: str = "",
    config_file: str = "",
    extra_context: str = "",
    **kwargs: Any,
) -> str:
    """Render the system prompt using templates.

    This replaces the string.format_map approach in core.py with Jinja2 templates.
    Uses template inheritance and partials for maintainability.

    Args:
        agents: Formatted agent list
        tools: Formatted tool list
        skills: Formatted skill list
        mcp_servers: Formatted MCP server list
        lsp_servers: Formatted LSP server list
        cwd: Current working directory
        config_file: Config file path
        extra_context: Additional context (from AGENTS.md, etc.)
        **kwargs: Additional template variables

    Returns:
        Rendered system prompt
    """
    loader = get_template_loader()

    context = {
        "agents": agents or "- (no custom agents)",
        "tools": tools or "- (built-in only)",
        "skills": skills or "- (none installed)",
        "mcp_servers": mcp_servers or "- (none configured)",
        "lsp_servers": lsp_servers or "- (none configured)",
        "cwd": cwd,
        "config_file": config_file,
        "extra_context": extra_context,
        **kwargs,
    }

    return loader.render("template.md", context)
