"""Drift Watchdog - monitors agent for goal drift and intervenes if needed."""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("nanocode.drift")


class DriftMode(Enum):
    """Drift watchdog modes."""

    OFF = "off"
    ALERT = "alert"
    INTERVENE = "intervene"


@dataclass
class DriftState:
    """Current drift state."""

    original_goal: str = ""
    check_count: int = 0
    drift_detected: bool = False
    last_check_topic: str = ""
    alert_count: int = 0


@dataclass
class DriftConfig:
    """Configuration for drift watchdog."""

    mode: DriftMode = DriftMode.OFF
    check_interval: int = 10  # Check every N messages
    alert_threshold: float = 0.3  # 30% topic change triggers alert
    intervene_threshold: float = 0.6  # 60% triggers intervention


@dataclass
class DriftAlert:
    """A drift alert."""

    mode: DriftMode
    drift_score: float
    original_topic: str
    current_topic: str
    message: str


class DriftWatchdog:
    """Watchdog that monitors for goal drift."""

    def __init__(self, config: DriftConfig = None):
        self.config = config or DriftConfig()
        self.state = DriftState()
        self._topic_extractor: Optional[object] = None

    @property
    def is_enabled(self) -> bool:
        """Check if watchdog is enabled."""
        return self.config.mode != DriftMode.OFF

    @property
    def mode(self) -> DriftMode:
        """Get current mode."""
        return self.config.mode

    def set_goal(self, goal: str):
        """Set the original goal for drift detection."""
        self.state.original_goal = goal
        self.state.check_count = 0
        self.state.drift_detected = False
        self.state.alert_count = 0
        self.state.last_check_topic = self._extract_topic(goal)
        logger.info(f"Drift watchdog initialized with goal: {goal[:50]}...")

    def _extract_topic(self, text: str) -> str:
        """Extract key topics from text."""
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        words = text.split()
        words = [w for w in words if len(w) > 3]
        return " ".join(words[:5])

    def _calculate_drift(self, current_text: str) -> float:
        """Calculate drift score (0.0 = no drift, 1.0 = complete drift)."""
        if not self.state.original_goal:
            return 0.0

        original_topics = set(self._extract_topic(self.state.original_goal).split())
        current_topics = set(self._extract_topic(current_text).split())

        if not original_topics:
            return 0.0

        overlap = len(original_topics & current_topics)
        total = len(original_topics | current_topics)

        if total == 0:
            return 0.0

        similarity = overlap / total
        return 1.0 - similarity

    def check(self, current_context: str) -> DriftAlert | None:
        """Check for drift. Returns alert if drift detected, None otherwise."""
        if not self.is_enabled:
            return None

        if not self.state.original_goal:
            logger.debug("No goal set for drift detection")
            return None

        self.state.check_count += 1
        self.state.last_check_topic = self._extract_topic(current_context)

        drift_score = self._calculate_drift(current_context)

        alert_threshold = self.config.alert_threshold
        intervene_threshold = self.config.intervene_threshold

        if drift_score >= intervene_threshold and self.config.mode == DriftMode.INTERVENE:
            self.state.drift_detected = True
            self.state.alert_count += 1
            return DriftAlert(
                mode=DriftMode.INTERVENE,
                drift_score=drift_score,
                original_topic=self.state.original_goal[:50],
                current_topic=current_context[:50],
                message=f"[DRIFT] High drift detected ({drift_score:.0%}). Intervening to refocus on original goal.",
            )

        if drift_score >= alert_threshold and self.config.mode == DriftMode.ALERT:
            self.state.alert_count += 1
            return DriftAlert(
                mode=DriftMode.ALERT,
                drift_score=drift_score,
                original_topic=self.state.original_goal[:50],
                current_topic=current_context[:50],
                message=f"[DRIFT] Moderate drift detected ({drift_score:.0%}). Consider refocusing.",
            )

        return None

    def get_stats(self) -> dict:
        """Get drift watchdog statistics."""
        return {
            "enabled": self.is_enabled,
            "mode": self.config.mode.value,
            "check_count": self.state.check_count,
            "drift_detected": self.state.drift_detected,
            "alert_count": self.state.alert_count,
            "has_goal": bool(self.state.original_goal),
        }

    def reset(self):
        """Reset drift state."""
        self.state = DriftState()


def create_drift_watchdog(mode: str = "off", check_interval: int = 10) -> DriftWatchdog:
    """Create a drift watchdog."""
    mode_map = {
        "off": DriftMode.OFF,
        "alert": DriftMode.ALERT,
        "intervene": DriftMode.INTERVENE,
    }
    config = DriftConfig(
        mode=mode_map.get(mode, DriftMode.OFF),
        check_interval=check_interval,
    )
    return DriftWatchdog(config)