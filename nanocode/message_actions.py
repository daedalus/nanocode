"""Message actions: revert, copy, fork with undo/redo support."""

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

    action_type: str  # revert, copy, fork, undo, redo
    timestamp: datetime = field(default_factory=datetime.now)
    message_index: int = 0
    details: str = ""


@dataclass
class RevertState:
    """State for revert operation (like opencode)."""

    message_id: str = ""
    snapshot_hash: str = ""
    diff: dict = field(default_factory=dict)
    message_count: int = 0


@dataclass 
class UndoEntry:
    """An undo entry with messages and state."""

    messages: list
    state: RevertState
    timestamp: datetime = field(default_factory=datetime.now)


class MessageActionManager:
    """Manages message actions: revert, copy, fork with undo/redo."""

    def __init__(self, messages: list = None):
        self._messages = messages or []
        self._action_history: list[MessageAction] = []
        self._undo_stack: list[UndoEntry] = []  # For undo
        self._redo_stack: list[UndoEntry] = []   # For redo
        self._current_state: Optional[RevertState] = None

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

    def undo(self) -> bool:
        """Undo last revert operation using undo stack."""
        if not self._undo_stack:
            return False

        entry = self._undo_stack.pop()

        self._redo_stack.append(
            UndoEntry(
                messages=self._messages.copy(),
                state=self._current_state or RevertState(),
            )
        )

        self._messages = entry.messages
        self._current_state = entry.state

        self._action_history.append(
            MessageAction(
                action_type="undo",
                details=f"Undid to message {len(self._messages)}",
            )
        )

        logger.info(f"Undo: restored to {len(self._messages)} messages")
        return True

    def redo(self) -> bool:
        """Redo last undone operation using redo stack."""
        if not self._redo_stack:
            return False

        entry = self._redo_stack.pop()

        self._undo_stack.append(
            UndoEntry(
                messages=self._messages.copy(),
                state=self._current_state or RevertState(),
            )
        )

        self._messages = entry.messages
        self._current_state = entry.state

        self._action_history.append(
            MessageAction(
                action_type="redo",
                details=f"Redid to message {len(self._messages)}",
            )
        )

        logger.info(f"Redo: restored to {len(self._messages)} messages")
        return True

    def can_undo(self) -> bool:
        """Check if undo is available."""
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        """Check if redo is available."""
        return len(self._redo_stack) > 0

    def revert_with_snapshot(self, at_index: int) -> dict:
        """Revert to a specific message index with filesystem awareness (like opencode)."""
        if not self._messages or at_index < 0 or at_index >= len(self._messages):
            return {"success": False, "error": "Invalid index"}

        from nanocode.snapshot import create_snapshot_manager

        snapshot_manager = create_snapshot_manager()

        snapshot_hash = None
        try:
            snapshot_hash = snapshot_manager.track()
        except Exception:
            pass

        reverted_messages = self._messages[at_index:]
        self._messages = self._messages[:at_index]

        self._current_state = RevertState(
            message_id=str(at_index),
            snapshot_hash=snapshot_hash or "",
            message_count=len(reverted_messages),
        )

        self._undo_stack.append(
            UndoEntry(
                messages=self._messages.copy(),
                state=self._current_state,
            )
        )

        self._redo_stack.clear()

        self._action_history.append(
            MessageAction(
                action_type="revert_snapshot",
                message_index=at_index,
                details=f"Reverted to message {at_index}",
            )
        )

        logger.info(f"Reverted with snapshot at message {at_index}")
        return {
            "success": True,
            "removed": len(reverted_messages),
            "snapshot": snapshot_hash,
        }

    def get_undo_stack_size(self) -> int:
        """Get size of undo stack."""
        return len(self._undo_stack)

    def get_redo_stack_size(self) -> int:
        """Get size of redo stack."""
        return len(self._redo_stack)

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