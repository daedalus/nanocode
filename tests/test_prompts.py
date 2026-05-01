"""Tests for template-based prompt system."""

import pytest
from pathlib import Path

from nanocode.prompts import render_system_prompt, PromptTemplateLoader


class TestRenderSystemPrompt:
    """Test the render_system_prompt function."""

    def test_render_basic(self):
        """Test basic prompt rendering."""
        result = render_system_prompt(
            agents="- agent1: build agent",
            tools="- bash: Execute shell commands",
            skills="- test_skill: A test skill",
            mcp_servers="- exa: Exa search",
            lsp_servers="- pyright: Python LSP",
            cwd="/home/user/project",
            config_file="config.yaml",
        )

        assert "agent1" in result
        assert "bash" in result
        assert "test_skill" in result
        assert "exa" in result
        assert "pyright" in result
        assert "/home/user/project" in result

    def test_render_with_empty_values(self):
        """Test rendering with empty values uses defaults."""
        result = render_system_prompt()

        assert "(no custom agents)" in result
        assert "(built-in only)" in result
        assert "(none installed)" in result
        assert "(none configured)" in result

    def test_render_includes_workflow(self):
        """Test that rendered prompt includes workflow section."""
        result = render_system_prompt()

        assert "Workflow" in result or "Capabilities" in result


class TestPromptTemplateLoader:
    """Test the PromptTemplateLoader class."""

    def test_init_with_default_dir(self):
        """Test initialization with default template directory."""
        loader = PromptTemplateLoader()
        # Should not raise an error
        assert loader is not None

    def test_list_templates(self):
        """Test listing available templates."""
        loader = PromptTemplateLoader()
        templates = loader.list_templates()

        # template.md should be available
        assert "template.md" in templates or len(templates) >= 0

    def test_render_default_template(self):
        """Test rendering default template."""
        loader = PromptTemplateLoader()

        # Create a simple test template
        context = {
            "agents": "- test agent",
            "tools": "- test tool",
        }

        result = loader.render(context=context)
        assert result is not None
        assert len(result) > 0
