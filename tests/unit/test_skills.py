"""Tests for skills module."""

import pytest
import tempfile
import os
import shutil

from nanocode.skills import (
    Skill,
    SkillsManager,
    SkillNotFoundError,
    create_skills_manager,
)


class TestSkill:
    """Test skill dataclass."""

    def test_skill_creation(self):
        """Test creating a skill."""
        skill = Skill(
            name="test-skill",
            description="A test skill",
            content="Skill content here",
            location="/path/to/skill.md",
        )

        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.content == "Skill content here"
        assert skill.location == "/path/to/skill.md"


class TestSkillsManager:
    """Test skills manager."""

    @pytest.fixture
    def temp_skill_dir(self):
        """Create a temporary directory with test skills."""
        tmpdir = tempfile.mkdtemp()

        skill_dir = os.path.join(tmpdir, ".agent", "skills", "test-skill")
        os.makedirs(skill_dir)

        skill_file = os.path.join(skill_dir, "skill.md")
        with open(skill_file, "w") as f:
            f.write(
                """---
name: test-skill
description: A test skill for unit tests
---

# Test Skill

This is a test skill content.
"""
            )

        yield tmpdir

        shutil.rmtree(tmpdir)

    @pytest.fixture
    def temp_skill_dir_no_frontmatter(self):
        """Create a temporary directory with skill without frontmatter."""
        tmpdir = tempfile.mkdtemp()

        skill_dir = os.path.join(tmpdir, ".agent", "skills", "no-fm-skill")
        os.makedirs(skill_dir)

        skill_file = os.path.join(skill_dir, "skill.md")
        with open(skill_file, "w") as f:
            f.write(
                """# No Frontmatter Skill

This skill has no frontmatter.
"""
            )

        yield tmpdir

        shutil.rmtree(tmpdir)

    def test_discover_skills(self, temp_skill_dir):
        """Test discovering skills in directory."""
        manager = SkillsManager(temp_skill_dir)
        discovered = manager.discover_skills()

        assert len(discovered) == 1
        assert discovered[0].name == "test-skill"

    def test_discover_skills_no_skills(self):
        """Test discovering skills with no skills directory."""
        tmpdir = tempfile.mkdtemp()

        manager = SkillsManager(tmpdir)
        discovered = manager.discover_skills()

        assert len(discovered) == 0

        os.rmdir(tmpdir)

    def test_load_skills(self, temp_skill_dir):
        """Test loading skills."""
        manager = SkillsManager(temp_skill_dir)
        count = manager.load_skills()

        assert count == 1
        assert "test-skill" in manager.skills

    def test_get_skill(self, temp_skill_dir):
        """Test getting a skill by name."""
        manager = SkillsManager(temp_skill_dir)
        manager.load_skills()

        skill = manager.get_skill("test-skill")

        assert skill is not None
        assert skill.name == "test-skill"

    def test_get_skill_not_found(self, temp_skill_dir):
        """Test getting a non-existent skill."""
        manager = SkillsManager(temp_skill_dir)
        manager.load_skills()

        with pytest.raises(SkillNotFoundError):
            manager.get_skill("non-existent")

    def test_list_skills(self, temp_skill_dir):
        """Test listing skills."""
        manager = SkillsManager(temp_skill_dir)
        manager.load_skills()

        skills = manager.list_skills()

        assert len(skills) == 1
        assert skills[0]["name"] == "test-skill"
        assert skills[0]["description"] == "A test skill for unit tests"

    def test_create_tools(self, temp_skill_dir):
        """Test creating tool definitions from skills."""
        manager = SkillsManager(temp_skill_dir)
        manager.load_skills()

        tools = manager.create_tools(None)

        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "skill_test_skill"

    def test_parse_skill_file_no_frontmatter(self, temp_skill_dir_no_frontmatter):
        """Test parsing skill file without frontmatter."""
        manager = SkillsManager(temp_skill_dir_no_frontmatter)

        skill = manager._parse_skill_file(
            os.path.join(
                temp_skill_dir_no_frontmatter, ".agent", "skills", "no-fm-skill", "skill.md"
            )
        )

        assert skill is not None
        assert skill.name == "no-fm-skill"

    def test_execute_skill(self, temp_skill_dir):
        """Test executing a skill."""
        import asyncio

        manager = SkillsManager(temp_skill_dir)
        manager.load_skills()

        async def run_test():
            result = await manager.execute_skill("test-skill", {"input": "test"}, {})
            assert result["skill"] == "test-skill"

        asyncio.run(run_test())

    def test_register_handler(self, temp_skill_dir):
        """Test registering a custom handler."""
        import asyncio

        manager = SkillsManager(temp_skill_dir)
        manager.load_skills()

        async def custom_handler(skill, args, context):
            return {"custom": True, "skill": skill.name, "args": args}

        manager.register_handler("test-skill", custom_handler)

        async def run_test():
            result = await manager.execute_skill("test-skill", {"input": "test"}, {})
            assert result["custom"] is True
            assert result["skill"] == "test-skill"

        asyncio.run(run_test())

    def test_create_skills_manager(self, temp_skill_dir):
        """Test create_skills_manager factory function."""
        manager = create_skills_manager(temp_skill_dir)

        assert manager is not None
        assert len(manager.skills) == 1


class TestInstallSkills:
    """Test install_skills function."""

    @pytest.fixture
    def temp_package_dir(self):
        """Create a temporary package structure with skills."""
        tmpdir = tempfile.mkdtemp()

        skills_src = os.path.join(tmpdir, "skills")
        os.makedirs(skills_src)

        test_skill_dir = os.path.join(skills_src, "test-skill")
        os.makedirs(test_skill_dir)

        with open(os.path.join(test_skill_dir, "SKILL.md"), "w") as f:
            f.write(
                """---
name: test-skill
description: A test skill
---

# Test Skill Content
"""
            )

        yield tmpdir
        shutil.rmtree(tmpdir)

    def test_install_skills_all(self, temp_package_dir, monkeypatch):
        """Test installing all skills."""
        from nanocode.skills import install_skills

        target_dir = tempfile.mkdtemp()
        monkeypatch.chdir(target_dir)

        try:
            package_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            skills_src = os.path.join(package_dir, "skills")

            if os.path.isdir(skills_src):
                result = install_skills(target_dir)

                assert result is True
                assert os.path.isdir(os.path.join(target_dir, ".agent", "skills"))

                skills = os.listdir(os.path.join(target_dir, ".agent", "skills"))
                assert "redteaming" in skills
        finally:
            shutil.rmtree(target_dir)

    def test_install_skills_specific(self, temp_package_dir, monkeypatch):
        """Test installing a specific skill."""
        from nanocode.skills import install_skills

        target_dir = tempfile.mkdtemp()
        monkeypatch.chdir(target_dir)

        try:
            result = install_skills(target_dir, "redteaming")

            assert result is True
            skill_path = os.path.join(target_dir, ".agent", "skills", "redteaming", "skill.md")
            assert os.path.isfile(skill_path)
        finally:
            shutil.rmtree(target_dir)

    def test_install_skills_nonexistent(self, monkeypatch):
        """Test installing a non-existent skill."""
        from nanocode.skills import install_skills

        target_dir = tempfile.mkdtemp()

        try:
            result = install_skills(target_dir, "nonexistent-skill")

            assert result is True
            skills_dir = os.path.join(target_dir, ".agent", "skills")
            assert not os.path.isdir(skills_dir) or not os.listdir(skills_dir)
        finally:
            shutil.rmtree(target_dir)

    def test_install_skills_updates_existing(self, monkeypatch):
        """Test that install_skills updates existing skills."""
        from nanocode.skills import install_skills

        target_dir = tempfile.mkdtemp()

        try:
            existing_dir = os.path.join(target_dir, ".agent", "skills", "redteaming")
            os.makedirs(existing_dir)
            with open(os.path.join(existing_dir, "skill.md"), "w") as f:
                f.write("old content")

            result = install_skills(target_dir, "redteaming")

            assert result is True
            with open(os.path.join(existing_dir, "skill.md")) as f:
                content = f.read()
                assert "old content" not in content
        finally:
            shutil.rmtree(target_dir)


class TestSkillTool:
    """Test skill tool integration."""

    @pytest.fixture
    def temp_skill_dir(self):
        """Create a temporary directory with test skills."""
        tmpdir = tempfile.mkdtemp()

        skill_dir = os.path.join(tmpdir, ".agent", "skills", "hello")
        os.makedirs(skill_dir)

        skill_file = os.path.join(skill_dir, "skill.md")
        with open(skill_file, "w") as f:
            f.write(
                """---
name: hello
description: Say hello
---

# Hello Skill

Returns a greeting.
"""
            )

        yield tmpdir

        shutil.rmtree(tmpdir)

    def test_skill_tool_integration(self, temp_skill_dir):
        """Test skill tool with skills manager."""
        from nanocode.skills import SkillsManager
        from nanocode.tools.builtin.skill import SkillTool, ListSkillsTool

        manager = SkillsManager(temp_skill_dir)
        manager.load_skills()

        skill_tool = SkillTool(manager)
        list_tool = ListSkillsTool(manager)

        assert skill_tool is not None
        assert list_tool is not None
