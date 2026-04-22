"""Message actions: revert, copy, fork."""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("nanocode.message_actions")


@dataclass
class MessageAction:
    """A single message action."""

    action_type: str  # revert, copy, fork
    timestamp: datetime = field(default_factory=datetime.now)
    message_index: int = 0
    details: str = ""


class MessageActionManager:
    """Manages message actions: revert, copy, fork."""

    def __init__(self, messages: list = None):
        self._messages = messages or []
        self._action_history: list[MessageAction] = []

    def get_message(self, index: int) -> Optional[dict]:
        """Get message by index from end (negative indexes from start)."""
        if index < 0:
            index = len(self._messages) + index
        if 0 <= index < len(self._messages):
            return self._messages[index]
        return None

    def revert(self, steps: int = 1) -> list[dict]:
        """Revert messages by N steps."""
        if not self._messages:
            return []

        removed = []
        steps = min(steps, len(self._messages))

        for _ in range(steps):
            if self._messages:
                removed.insert(0, self._messages.pop())

        self._action_history.append(
            MessageAction(
                action_type="revert",
                message_index=steps,
                details=f"Reverted {steps} messages",
            )
        )

        logger.info(f"Reverted {steps} messages")
        return removed

    def copy_message(self, index: int) -> Optional[dict]:
        """Copy a message to clipboard (returns dict for external use)."""
        msg = self.get_message(index)
        if msg:
            self._action_history.append(
                MessageAction(
                    action_type="copy",
                    message_index=index,
                    details=f"Copied message at index {index}",
                )
            )
            logger.info(f"Copied message at index {index}")
            return msg.copy() if isinstance(msg, dict) else msg
        return None

    def fork(
        self,
        fork_id: str = None,
        message_count: int = None,
    ) -> tuple[list[dict], str]:
        """Fork current session at a point, returns messages and fork_id."""
        fork_id = fork_id or str(uuid.uuid4())[:8]

        if message_count is not None:
            messages_to_fork = self._messages[:message_count]
        else:
            messages_to_fork = self._messages.copy()

        self._action_history.append(
            MessageAction(
                action_type="fork",
                message_index=len(messages_to_fork),
                details=f"Forked {len(messages_to_fork)} messages as {fork_id}",
            )
        )

        logger.info(f"Forked {len(messages_to_fork)} messages as {fork_id}")
        return messages_to_fork, fork_id

    def save_as(self, name: str) -> bool:
        """Save current messages as a named checkpoint."""
        from pathlib import Path

        storage_dir = Path.home() / ".local" / "share" / "nanocode" / "storage" / "forks"
        os.makedirs(storage_dir, exist_ok=True)

        fork_path = storage_dir / f"{name}.json"
        try:
            with open(fork_path, "w") as f:
                json.dump(self._messages, f, indent=2, default=str)
            logger.info(f"Saved fork as {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save fork: {e}")
            return False

    def load_fork(self, name: str) -> bool:
        """Load a named fork."""
        from pathlib import Path

        storage_dir = Path.home() / ".local" / "share" / "nanocode" / "storage" / "forks"
        fork_path = storage_dir / f"{name}.json"

        if not fork_path.exists():
            return False

        try:
            with open(fork_path) as f:
                self._messages = json.load(f)
            logger.info(f"Loaded fork {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to load fork: {e}")
            return False

    def list_forks(self) -> list[str]:
        """List available forks."""
        from pathlib import Path

        storage_dir = Path.home() / ".local" / "share" / "nanocode" / "storage" / "forks"
        if not storage_dir.exists():
            return []

        return [f.stem for f in storage_dir.glob("*.json")]

    def get_action_history(self) -> list[dict]:
        """Get action history as dicts."""
        return [
            {
                "action_type": a.action_type,
                "timestamp": a.timestamp.isoformat(),
                "message_index": a.message_index,
                "details": a.details,
            }
            for a in self._action_history
        ]

    def get_stats(self) -> dict:
        """Get stats."""
        return {
            "message_count": len(self._messages),
            "action_count": len(self._action_history),
            "forks_available": self.list_forks(),
        }


def create_message_manager(messages: list = None) -> MessageActionManager:
    """Create message action manager."""
    return MessageActionManager(messages)