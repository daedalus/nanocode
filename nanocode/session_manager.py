"""JSON-based session management system.

Each session is stored as a JSON file in ~/.local/share/nanocode/storage/sessions/{session_id}.json

Session structure:
{
    "id": "session-uuid",
    "title": "Session title",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00",
    "messages": [...],
    "context_summary": "...",
    "metadata": {}
}
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("nanocode.session_manager")


def _get_default_storage_dir() -> Path:
    """Get default storage directory following XDG spec."""
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data) / "nanocode" / "storage"


@dataclass
class SessionMessage:
    """A single message in the session."""

    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionMessage":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"])
            if "timestamp" in data
            else datetime.now(),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Session:
    """A session with messages and metadata."""

    id: str
    title: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    messages: list[SessionMessage] = field(default_factory=list)
    context_summary: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "messages": [m.to_dict() for m in self.messages],
            "context_summary": self.context_summary,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            id=data["id"],
            title=data["title"],
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(),
            messages=[SessionMessage.from_dict(m) for m in data.get("messages", [])],
            context_summary=data.get("context_summary", ""),
            metadata=data.get("metadata", {}),
        )

    def add_message(self, role: str, content: str, metadata: dict = None) -> SessionMessage:
        """Add a message to the session."""
        msg = SessionMessage(role=role, content=content, metadata=metadata or {})
        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg

    def touch(self):
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now()


class SessionManager:
    """JSON-based session manager.

    Each session is stored as: storage/sessions/{session_id}.json
    """

    def __init__(self, storage_dir: Path | str | None = None):
        if storage_dir is None:
            storage_dir = _get_default_storage_dir() / "sessions"
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_filepath(self, session_id: str) -> Path:
        """Get filepath for session ID."""
        return self.storage_dir / f"{session_id}.json"

    def create(self, title: str = None, metadata: dict = None) -> Session:
        """Create a new session."""
        session_id = uuid.uuid4().hex[:12]
        session = Session(
            id=session_id,
            title=title or f"Session - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            metadata=metadata or {},
        )
        self.save(session)
        logger.debug(f"Created session: {session_id}")
        return session

    def get(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        filepath = self._get_filepath(session_id)
        if not filepath.exists():
            return None
        try:
            with open(filepath) as f:
                return Session.from_dict(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logger.debug(f"Failed to load session {session_id}: {e}")
            return None

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        filepath = self._get_filepath(session.id)
        with open(filepath, "w") as f:
            json.dump(session.to_dict(), f, indent=2)
        logger.debug(f"Saved session: {session.id}")

    def list(self, limit: int = 50) -> list[Session]:
        """List all sessions, most recent first."""
        sessions = []
        for filepath in sorted(
            self.storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            if limit and len(sessions) >= limit:
                break
            with open(filepath) as f:
                sessions.append(Session.from_dict(json.load(f)))
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session."""
        filepath = self._get_filepath(session_id)
        if filepath.exists():
            filepath.unlink()
            logger.debug(f"Deleted session: {session_id}")
            return True
        return False

    def exists(self, session_id: str) -> bool:
        """Check if session exists."""
        return self._get_filepath(session_id).exists()

    def get_or_create(self, session_id: str | None, title: str = None) -> Session:
        """Get existing session or create new one."""
        if session_id:
            session = self.get(session_id)
            if session:
                return session
        return self.create(title)

    def update(self, session: Session) -> None:
        """Update session timestamp and save."""
        session.touch()
        self.save(session)


_default_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = SessionManager()
    return _default_manager