"""Tests for the enhanced Skills Discovery system."""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from nanocode.skills import SkillsManager, Skill


class TestSkill:
    """Tests for Skill dataclass."""

    def test_skill_creation(self):
        """Test basic skill creation."""
        skill = Skill(
            name="test-skill",
            description="A test skill",
            content="# Test\nContent here",
            location="/path/to/SKILL.md",
        )
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.version is None
        assert skill.author is None
        assert skill.tags is None

    def test_skill_with_metadata(self):
        """Test skill with full metadata."""
        skill = Skill(
            name="test-skill",
            description="A test skill",
            content="# Test",
            location="/path/to/SKILL.md",
            version="1.0.0",
            author="Test Author",
            tags=["test", "example"],
        )
        assert skill.version == "1.0.0"
        assert skill.author == "Test Author"
        assert skill.tags == ["test", "example"]


class TestSkillsManager:
    """Tests for SkillsManager."""

    def test_init(self, tmp_path):
        """Test manager initialization."""
        manager = SkillsManager(base_dir=str(tmp_path))
        assert manager.base_dir == str(tmp_path)
        assert len(manager.skills) == 0

    def test_validate_skill_valid(self):
        """Test validating a valid skill."""
        manager = SkillsManager()
        skill = Skill(
            name="test-skill",
            description="A valid test skill with enough description",
            content="# Test\nContent here",
            location="/path/to/SKILL.md",
        )
        is_valid, error = manager.validate_skill(skill)
        assert is_valid is True
        assert error is None

    def test_validate_skill_no_name(self):
        """Test validating skill without name."""
        manager = SkillsManager()
        skill = Skill(
            name="",
            description="A valid test skill",
            content="# Test",
            location="/path/to/SKILL.md",
        )
        is_valid, error = manager.validate_skill(skill)
        assert is_valid is False
        assert "name" in error.lower()

    def test_validate_skill_short_name(self):
        """Test validating skill with short name."""
        manager = SkillsManager()
        skill = Skill(
            name="a",
            description="A valid test skill",
            content="# Test",
            location="/path/to/SKILL.md",
        )
        is_valid, error = manager.validate_skill(skill)
        assert is_valid is False
        assert "2 characters" in error

    def test_validate_skill_no_description(self):
        """Test validating skill without description."""
        manager = SkillsManager()
        skill = Skill(
            name="test-skill",
            description="",
            content="# Test",
            location="/path/to/SKILL.md",
        )
        is_valid, error = manager.validate_skill(skill)
        assert is_valid is False
        assert "description" in error.lower()

    def test_validate_skill_short_description(self):
        """Test validating skill with short description."""
        manager = SkillsManager()
        skill = Skill(
            name="test-skill",
            description="Short",
            content="# Test",
            location="/path/to/SKILL.md",
        )
        is_valid, error = manager.validate_skill(skill)
        assert is_valid is False
        assert "10 characters" in error

    def test_validate_skill_no_content(self):
        """Test validating skill without content."""
        manager = SkillsManager()
        skill = Skill(
            name="test-skill",
            description="A valid test skill with enough description",
            content="",
            location="/path/to/SKILL.md",
        )
        is_valid, error = manager.validate_skill(skill)
        assert is_valid is False
        assert "content" in error.lower()

    def test_parse_skill_file(self, tmp_path):
        """Test parsing a SKILL.md file."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: test-skill
description: A test skill for testing
version: 1.0.0
author: Test Author
tags: test, example
---

# Test Skill

This is a test skill.

## Usage

Run with `test` command.
""")
        manager = SkillsManager(base_dir=str(tmp_path))
        skill = manager._parse_skill_file(str(skill_file))
        
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill for testing"
        assert skill.version == "1.0.0"
        assert skill.author == "Test Author"
        assert skill.tags == ["test", "example"]

    def test_parse_skill_file_minimal(self, tmp_path):
        """Test parsing a minimal SKILL.md file."""
        skill_dir = tmp_path / "minimal-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: minimal
description: A minimal skill
---

Content here.
""")
        manager = SkillsManager(base_dir=str(tmp_path))
        skill = manager._parse_skill_file(str(skill_file))
        
        assert skill is not None
        assert skill.name == "minimal"
        assert skill.version is None
        assert skill.author is None

    def test_discover_skills_local(self, tmp_path):
        """Test discovering local skills."""
        # Create skill directory structure
        skills_dir = tmp_path / ".nanocode" / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        skill_file = skills_dir / "SKILL.md"
        skill_file.write_text("""---
name: my-skill
description: A discovered skill for testing
---

# My Skill

Content here.
""")
        manager = SkillsManager(base_dir=str(tmp_path))
        discovered = manager.discover_skills()
        
        assert len(discovered) >= 1
        skill_names = [s.name for s in discovered]
        assert "my-skill" in skill_names

    def test_get_stats(self, tmp_path):
        """Test getting skill statistics."""
        manager = SkillsManager(base_dir=str(tmp_path))
        stats = manager.get_stats()
        
        assert "total_skills" in stats
        assert "local_skills" in stats
        assert "remote_skills" in stats
        assert "tags" in stats


class TestSkillParsing:
    """Tests for skill metadata parsing."""

    def test_parse_tags_string(self, tmp_path):
        """Test parsing tags as comma-separated string."""
        skill_dir = tmp_path / "tagged-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: tagged
description: A skill with tags
tags: python, testing, docs
---

Content.
""")
        manager = SkillsManager(base_dir=str(tmp_path))
        skill = manager._parse_skill_file(str(skill_file))
        
        assert skill.tags == ["python", "testing", "docs"]

    def test_parse_tags_list(self, tmp_path):
        """Test parsing tags as YAML list."""
        skill_dir = tmp_path / "tagged-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: tagged
description: A skill with tags
tags:
  - python
  - testing
---

Content.
""")
        manager = SkillsManager(base_dir=str(tmp_path))
        skill = manager._parse_skill_file(str(skill_file))
        
        assert skill.tags == ["python", "testing"]
