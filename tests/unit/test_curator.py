"""Tests for curator - background skill maintenance orchestrator."""

from unittest.mock import MagicMock, patch

import pytest


class TestCuratorState:
    """Test curator state management."""

    def test_load_state_default(self):
        """Test load_state returns defaults when no state file exists."""
        from nanocode.agents.curator import load_state

        with patch("nanocode.agents.curator._state_file") as mock_path:
            mock_path.return_value.exists.return_value = False
            state = load_state()
            assert state["last_run_at"] is None
            assert state["run_count"] == 0
            assert state["paused"] is False

    def test_load_state_from_file(self):
        """Test load_state reads existing state file."""
        from nanocode.agents.curator import load_state
        import json

        with patch("nanocode.agents.curator._state_file") as mock_path:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.read_text.return_value = json.dumps({
                "last_run_at": "2024-01-01T00:00:00+00:00",
                "run_count": 5,
                "paused": True,
            })
            mock_path.return_value = mock_file
            state = load_state()
            assert state["run_count"] == 5
            assert state["paused"] is True

    def test_save_state(self):
        """Test save_state writes state file."""
        from nanocode.agents.curator import save_state
        import tempfile
        import os
        from pathlib import Path

        with patch("nanocode.agents.curator._state_file") as mock_path:
            tmpdir = tempfile.mkdtemp()
            try:
                state_file = Path(tmpdir) / ".curator_state"
                mock_path.return_value = state_file
                save_state({"run_count": 3, "paused": False})
                assert state_file.exists()
            finally:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)

    def test_set_paused(self):
        """Test set_paused updates paused state."""
        from nanocode.agents.curator import set_paused, is_paused

        with patch("nanocode.agents.curator.save_state") as mock_save, \
             patch("nanocode.agents.curator.load_state") as mock_load:
            mock_load.return_value = {"paused": False, "run_count": 0}
            set_paused(True)
            mock_save.assert_called_once()
            state_arg = mock_save.call_args[0][0]
            assert state_arg["paused"] is True

    def test_is_paused_reads_state(self):
        """Test is_paused returns current paused state."""
        from nanocode.agents.curator import is_paused

        with patch("nanocode.agents.curator.load_state") as mock_load:
            mock_load.return_value = {"paused": True}
            assert is_paused() is True
            mock_load.return_value = {"paused": False}
            assert is_paused() is False


class TestCuratorConfig:
    """Test curator config accessors."""

    def test_is_enabled_default(self):
        """Test is_enabled defaults to True."""
        from nanocode.agents.curator import is_enabled

        assert is_enabled() is True

    def test_is_enabled_false(self):
        """Test is_enabled returns False when disabled in config."""
        from nanocode.agents.curator import is_enabled

        mock_agent = MagicMock()
        mock_agent.config.get.return_value = {"enabled": False}
        assert is_enabled(mock_agent) is False

    def test_get_interval_hours_default(self):
        """Test get_interval_hours returns default."""
        from nanocode.agents.curator import get_interval_hours, DEFAULT_INTERVAL_HOURS

        assert get_interval_hours() == DEFAULT_INTERVAL_HOURS

    def test_get_interval_hours_from_config(self):
        """Test get_interval_hours reads from config."""
        from nanocode.agents.curator import get_interval_hours

        mock_agent = MagicMock()
        mock_agent.config.get.return_value = {"interval_hours": 12}
        assert get_interval_hours(mock_agent) == 12

    def test_get_stale_after_days_default(self):
        """Test get_stale_after_days returns default."""
        from nanocode.agents.curator import get_stale_after_days, DEFAULT_STALE_AFTER_DAYS

        assert get_stale_after_days() == DEFAULT_STALE_AFTER_DAYS

    def test_get_archive_after_days_default(self):
        """Test get_archive_after_days returns default."""
        from nanocode.agents.curator import get_archive_after_days, DEFAULT_ARCHIVE_AFTER_DAYS

        assert get_archive_after_days() == DEFAULT_ARCHIVE_AFTER_DAYS

    def test_get_interval_hours_bad_value(self):
        """Test get_interval_hours falls back on bad value."""
        from nanocode.agents.curator import get_interval_hours, DEFAULT_INTERVAL_HOURS

        mock_agent = MagicMock()
        mock_agent.config.get.return_value = {"interval_hours": "not-a-number"}
        assert get_interval_hours(mock_agent) == DEFAULT_INTERVAL_HOURS


class TestShouldRunNow:
    """Test should_run_now logic."""

    def test_disabled_returns_false(self):
        """Test should_run_now returns False when curator disabled."""
        from nanocode.agents.curator import should_run_now

        mock_agent = MagicMock()
        mock_agent.config.get.return_value = {"enabled": False}
        assert should_run_now(mock_agent) is False

    def test_paused_returns_false(self):
        """Test should_run_now returns False when paused."""
        from nanocode.agents.curator import should_run_now

        with patch("nanocode.agents.curator.is_paused", return_value=True), \
             patch("nanocode.agents.curator.is_enabled", return_value=True):
            assert should_run_now() is False

    def test_first_run_seeds_and_returns_false(self):
        """Test first run seeds last_run_at and returns False."""
        from datetime import datetime, UTC
        from nanocode.agents.curator import should_run_now

        with patch("nanocode.agents.curator.is_enabled", return_value=True), \
             patch("nanocode.agents.curator.is_paused", return_value=False), \
             patch("nanocode.agents.curator.load_state") as mock_load, \
             patch("nanocode.agents.curator.save_state") as mock_save:
            mock_load.return_value = {"last_run_at": None, "run_count": 0}
            result = should_run_now(now=datetime.now(UTC))
            assert result is False
            mock_save.assert_called_once()

    def test_interval_not_elapsed_returns_false(self):
        """Test should_run_now returns False when interval not elapsed."""
        from datetime import datetime, timedelta, UTC
        from nanocode.agents.curator import should_run_now

        now = datetime.now(UTC)
        recent_run = (now - timedelta(hours=1)).isoformat()

        with patch("nanocode.agents.curator.is_enabled", return_value=True), \
             patch("nanocode.agents.curator.is_paused", return_value=False), \
             patch("nanocode.agents.curator.load_state") as mock_load:
            mock_load.return_value = {"last_run_at": recent_run, "run_count": 1}
            result = should_run_now(now=now)
            assert result is False

    def test_interval_elapsed_returns_true(self):
        """Test should_run_now returns True when interval elapsed."""
        from datetime import datetime, timedelta, UTC
        from nanocode.agents.curator import should_run_now

        now = datetime.now(UTC)
        old_run = (now - timedelta(days=30)).isoformat()

        with patch("nanocode.agents.curator.is_enabled", return_value=True), \
             patch("nanocode.agents.curator.is_paused", return_value=False), \
             patch("nanocode.agents.curator.load_state") as mock_load:
            mock_load.return_value = {"last_run_at": old_run, "run_count": 1}
            result = should_run_now(now=now)
            assert result is True

    def test_last_run_naive_datetime(self):
        """Test should_run_now handles naive datetime."""
        from datetime import datetime, timedelta, UTC
        from nanocode.agents.curator import should_run_now

        now = datetime.now(UTC)
        old_run = (now - timedelta(days=30)).isoformat().replace("+00:00", "")

        with patch("nanocode.agents.curator.is_enabled", return_value=True), \
             patch("nanocode.agents.curator.is_paused", return_value=False), \
             patch("nanocode.agents.curator.load_state") as mock_load:
            mock_load.return_value = {"last_run_at": old_run, "run_count": 1}
            result = should_run_now(now=now)
            assert result is True


class TestFormatSkillsReport:
    """Test format_skills_report."""

    def test_empty_skills(self):
        """Test format_skills_report with empty list."""
        from nanocode.agents.curator import format_skills_report

        result = format_skills_report([])
        assert "no skills" in result

    def test_with_skills(self):
        """Test format_skills_report formats skills."""
        from nanocode.agents.curator import format_skills_report

        skills = [
            {"name": "test-skill", "description": "A test skill", "location": "/tmp/skill"},
        ]
        result = format_skills_report(skills)
        assert "test-skill" in result
        assert "A test skill" in result
        assert "/tmp/skill" in result
        assert "1 total" in result


class TestParseIso:
    """Test _parse_iso helper."""

    def test_none_returns_none(self):
        """Test _parse_iso returns None for None."""
        from nanocode.agents.curator import _parse_iso

        assert _parse_iso(None) is None

    def test_empty_returns_none(self):
        """Test _parse_iso returns None for empty string."""
        from nanocode.agents.curator import _parse_iso

        assert _parse_iso("") is None

    def test_valid_iso(self):
        """Test _parse_iso parses valid ISO datetime."""
        from datetime import datetime
        from nanocode.agents.curator import _parse_iso

        result = _parse_iso("2024-01-01T00:00:00+00:00")
        assert result is not None
        assert isinstance(result, datetime)

    def test_invalid_iso(self):
        """Test _parse_iso returns None for invalid string."""
        from nanocode.agents.curator import _parse_iso

        assert _parse_iso("not-a-date") is None


class TestRunCuratorPass:
    """Test run_curator_pass."""

    @pytest.mark.asyncio
    async def test_no_skills_manager(self):
        """Test run_curator_pass handles missing skills manager."""
        from nanocode.agents.curator import run_curator_pass

        mock_agent = MagicMock()
        mock_agent.skills_manager = None
        result = await run_curator_pass(mock_agent)
        assert "no skills manager" in (result or "")

    @pytest.mark.asyncio
    async def test_no_skills_data(self):
        """Test run_curator_pass handles empty skills list."""
        from nanocode.agents.curator import run_curator_pass

        mock_agent = MagicMock()
        mock_agent.skills_manager.list_skills.return_value = []
        result = await run_curator_pass(mock_agent)
        assert "no skills to review" in (result or "")
