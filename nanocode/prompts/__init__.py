"""Template-based prompt system using Jinja2.

Provides modular, maintainable prompt templates with support for partials,
similar to openwarp's minijinja-based system.
"""

from nanocode.prompts.template_loader import (
    PromptTemplateLoader,
    get_template_loader,
    render_system_prompt,
)

__all__ = ["PromptTemplateLoader", "render_system_prompt", "get_template_loader"]
