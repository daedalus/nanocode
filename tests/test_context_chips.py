"""Tests for context chips system."""

import pytest
from nanocode.context_chips import (
    ContextChip,
    ChipType,
    create_chip,
    ContextFetcher,
    ContextChipManager,
    get_chip_manager,
    fetch_env_context,
    fetch_current_time,
)


class TestChipType:
    """Test ChipType enum."""

    def test_has_env(self):
        assert ChipType.ENV.value == "env"

    def test_has_git(self):
        assert ChipType.GIT.value == "git"

    def test_has_skills(self):
        assert ChipType.SKILLS.value == "skills"


class TestContextChip:
    """Test ContextChip dataclass."""

    def test_create_basic(self):
        chip = ContextChip(
            chip_type=ChipType.ENV,
            name="Environment",
        )
        assert chip.chip_type == ChipType.ENV
        assert chip.name == "Environment"
        assert chip.enabled is True
        assert chip.priority == 100

    def test_create_with_options(self):
        chip = ContextChip(
            chip_type=ChipType.GIT,
            name="Git Context",
            enabled=False,
            priority=50,
        )
        assert chip.enabled is False
        assert chip.priority == 50

    def test_to_dict(self):
        chip = ContextChip(
            chip_type=ChipType.ENV,
            name="Environment",
        )
        d = chip.to_dict()
        assert d["type"] == "env"
        assert d["name"] == "Environment"
        assert d["enabled"] is True

    def test_from_dict(self):
        data = {
            "type": "git",
            "name": "Git",
            "enabled": False,
            "priority": 30,
        }
        chip = ContextChip.from_dict(data)
        assert chip.chip_type == ChipType.GIT
        assert chip.name == "Git"
        assert chip.enabled is False
        assert chip.priority == 30


class TestCreateChip:
    """Test create_chip helper."""

    def test_create_from_enum(self):
        chip = create_chip(ChipType.SKILLS, name="My Skills")
        assert chip.chip_type == ChipType.SKILLS
        assert chip.name == "My Skills"

    def test_create_from_string(self):
        chip = create_chip("codebase", name="Codebase")
        assert chip.chip_type.value == "codebase"

    def test_create_with_metadata(self):
        chip = create_chip(
            ChipType.ENV,
            name="Env",
            priority=10,
            custom_data="test",
        )
        assert chip.metadata["custom_data"] == "test"
        assert chip.priority == 10


class TestContextFetcher:
    """Test ContextFetcher class."""

    def test_init(self):
        fetcher = ContextFetcher()
        assert fetcher is not None

    def test_fetch_env_context(self):
        result = fetch_env_context(max_vars=5)
        assert result is not None
        assert len(result) > 0

    def test_fetch_current_time(self):
        result = fetch_current_time()
        assert result is not None
        assert len(result) > 0
        # Should contain date pattern
        assert "-" in result  # YYYY-MM-DD

    def test_fetch_all(self):
        fetcher = ContextFetcher()
        result = fetcher.fetch_all(enabled_chips=["env", "current_time"])

        assert "env" in result
        assert "current_time" in result

    def test_fetch_by_type(self):
        fetcher = ContextFetcher()
        result = fetcher.fetch_by_type("env")

        assert "env" in result


class TestContextChipManager:
    """Test ContextChipManager class."""

    def test_init(self):
        manager = ContextChipManager()
        assert manager is not None
        assert len(manager.chips) > 0

    def test_enable_disable_chip(self):
        manager = ContextChipManager()

        # Disable a chip
        manager.disable_chip("env")
        assert manager.is_enabled("env") is False

        # Re-enable
        manager.enable_chip("env")
        assert manager.is_enabled("env") is True

    def test_get_enabled_chips(self):
        manager = ContextChipManager()

        # Disable one chip
        manager.disable_chip("env")
        enabled = manager.get_enabled_chips()

        assert "env" not in enabled
        assert "git" in enabled

    def test_set_enabled_chips(self):
        manager = ContextChipManager()

        manager.set_enabled_chips(["env", "git"])
        enabled = manager.get_enabled_chips()

        assert "env" in enabled
        assert "git" in enabled
        assert "skills" not in enabled

    def test_fetch_context(self):
        manager = ContextChipManager()
        result = manager.fetch_context()

        assert len(result) > 0
        # Should have some context
        for chip_type, context in result.items():
            assert context is not None

    def test_build_context_section(self):
        manager = ContextChipManager()
        result = manager.build_context_section()

        assert "Context" in result or len(result) > 0

    def test_to_from_dict(self):
        manager = ContextChipManager()

        # Export config
        config = manager.to_dict()
        assert len(config) > 0

        # Modify config
        config["env"]["enabled"] = False

        # Import config
        manager.from_dict(config)
        assert manager.is_enabled("env") is False


class TestGetChipManager:
    """Test get_chip_manager function."""

    def test_returns_manager(self):
        manager = get_chip_manager()
        assert manager is not None
        assert isinstance(manager, ContextChipManager)
