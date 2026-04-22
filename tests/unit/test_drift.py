"""Tests for drift watchdog."""

import pytest

from nanocode.drift import (
    DriftConfig,
    DriftMode,
    DriftWatchdog,
    DriftState,
    create_drift_watchdog,
)


class TestDriftConfig:
    """Test DriftConfig."""

    def test_defaults(self):
        """Test default config."""
        config = DriftConfig()

        assert config.mode == DriftMode.OFF
        assert config.check_interval == 10
        assert config.alert_threshold == 0.3
        assert config.intervene_threshold == 0.6


class TestDriftState:
    """Test DriftState."""

    def test_defaults(self):
        """Test default state."""
        state = DriftState()

        assert state.original_goal == ""
        assert state.check_count == 0
        assert state.drift_detected is False


class TestDriftWatchdog:
    """Test DriftWatchdog."""

    def test_disabled_by_default(self):
        """Test watchdog is disabled by default."""
        watchdog = DriftWatchdog()

        assert watchdog.is_enabled is False
        assert watchdog.mode == DriftMode.OFF

    def test_alert_mode(self):
        """Test alert mode."""
        config = DriftConfig(mode=DriftMode.ALERT)
        watchdog = DriftWatchdog(config)

        assert watchdog.is_enabled is True
        assert watchdog.mode == DriftMode.ALERT

    def test_intervene_mode(self):
        """Test intervene mode."""
        config = DriftConfig(mode=DriftMode.INTERVENE)
        watchdog = DriftWatchdog(config)

        assert watchdog.is_enabled is True
        assert watchdog.mode == DriftMode.INTERVENE

    def test_set_goal(self):
        """Test setting original goal."""
        watchdog = DriftWatchdog()
        watchdog.set_goal("Implement user authentication")

        assert watchdog.state.original_goal == "Implement user authentication"
        assert watchdog.state.check_count == 0

    def test_no_drift_same_topic(self):
        """Test no drift when same topic."""
        config = DriftConfig(mode=DriftMode.ALERT)
        watchdog = DriftWatchdog(config)
        watchdog.set_goal("Implement user authentication")

        alert = watchdog.check("Now implement user authentication")

        assert alert is None

    def test_drift_detected_alert(self):
        """Test drift detected in alert mode."""
        config = DriftConfig(
            mode=DriftMode.ALERT,
            alert_threshold=0.3,
        )
        watchdog = DriftWatchdog(config)
        watchdog.set_goal("Fix bug in login")

        alert = watchdog.check("What is the weather today?")

        assert alert is not None
        assert alert.mode == DriftMode.ALERT

    def test_drift_detected_intervene(self):
        """Test drift detected in intervene mode."""
        config = DriftConfig(
            mode=DriftMode.INTERVENE,
            alert_threshold=0.3,
            intervene_threshold=0.6,
        )
        watchdog = DriftWatchdog(config)
        watchdog.set_goal("Fix bug in login")

        alert = watchdog.check("Tell me a joke")

        assert alert is not None
        assert alert.mode == DriftMode.INTERVENE

    def test_drift_check_increments_count(self):
        """Test check increments counter."""
        config = DriftConfig(mode=DriftMode.ALERT)
        watchdog = DriftWatchdog(config)
        watchdog.set_goal("Test goal")

        watchdog.check("Context 1")
        watchdog.check("Context 2")

        assert watchdog.state.check_count == 2

    def test_disabled_returns_none(self):
        """Test disabled watchdog returns None."""
        watchdog = DriftWatchdog()
        watchdog.set_goal("Some goal")

        alert = watchdog.check("Different context")

        assert alert is None

    def test_no_goal_returns_none(self):
        """Test no goal returns None."""
        config = DriftConfig(mode=DriftMode.ALERT)
        watchdog = DriftWatchdog(config)

        alert = watchdog.check("Some context")

        assert alert is None

    def test_reset(self):
        """Test reset clears state."""
        config = DriftConfig(mode=DriftMode.ALERT)
        watchdog = DriftWatchdog(config)
        watchdog.set_goal("Goal")
        watchdog.state.check_count = 5
        watchdog.state.alert_count = 2

        watchdog.reset()

        assert watchdog.state.original_goal == ""
        assert watchdog.state.check_count == 0

    def test_get_stats(self):
        """Test statistics."""
        config = DriftConfig(mode=DriftMode.ALERT)
        watchdog = DriftWatchdog(config)
        watchdog.set_goal("Test")

        stats = watchdog.get_stats()

        assert stats["enabled"] is True
        assert stats["mode"] == "alert"
        assert stats["has_goal"] is True


class TestCreateDriftWatchdog:
    """Test factory function."""

    def test_create_off(self):
        """Test create off."""
        watchdog = create_drift_watchdog("off")

        assert watchdog.mode == DriftMode.OFF

    def test_create_alert(self):
        """Test create alert."""
        watchdog = create_drift_watchdog("alert")

        assert watchdog.mode == DriftMode.ALERT

    def test_create_intervene(self):
        """Test create intervene."""
        watchdog = create_drift_watchdog("intervene")

        assert watchdog.mode == DriftMode.INTERVENE

    def test_custom_interval(self):
        """Test custom interval."""
        watchdog = create_drift_watchdog("alert", check_interval=5)

        assert watchdog.config.check_interval == 5