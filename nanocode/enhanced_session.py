"""Enhanced Session Persistence - Search, analytics, and versioning.

Builds on existing session_manager.py with:
- Session search across messages
- Session analytics and statistics
- Session versioning and snapshots
- Session export/import
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .session_manager import Session, SessionManager

logger = logging.getLogger(__name__)


@dataclass
class SessionSearchResult:
    """Result from session search."""

    session_id: str
    session_title: str
    matching_messages: list[dict[str, Any]]
    relevance_score: float
    last_updated: datetime


@dataclass
class SessionAnalytics:
    """Analytics for a session."""

    session_id: str
    message_count: int = 0
    user_messages: int = 0
    assistant_messages: int = 0
    tool_messages: int = 0
    total_tokens: int = 0
    avg_message_length: float = 0.0
    duration_minutes: float = 0.0
    first_message_at: datetime | None = None
    last_message_at: datetime | None = None


@dataclass
class SessionVersion:
    """A version snapshot of a session."""

    version: int
    session_id: str
    timestamp: datetime
    message_count: int
    snapshot: dict[str, Any]
    description: str = ""


class EnhancedSessionManager:
    """Enhanced session manager with search, analytics, and versioning.

    Builds on existing SessionManager with additional capabilities.
    """

    def __init__(self, storage_dir: str | None = None):
        """Initialize enhanced session manager.

        Args:
            storage_dir: Directory for session storage
        """
        if storage_dir is None:
            xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
            storage_dir = str(Path(xdg_data) / "nanocode" / "storage" / "sessions")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.base_manager = SessionManager(storage_dir)
        self._versions: dict[str, list[SessionVersion]] = {}

    def search(
        self,
        query: str,
        limit: int = 10,
        session_id: str | None = None,
    ) -> list[SessionSearchResult]:
        """Search across sessions and messages.

        Args:
            query: Search query
            limit: Maximum results
            session_id: Optional specific session to search

        Returns:
            List of search results
        """
        results = []
        query_lower = query.lower()

        sessions = self.base_manager.list(limit=100)

        for session in sessions:
            if session_id and session.id != session_id:
                continue

            matching_messages = []
            for msg in session.messages:
                if query_lower in msg.content.lower():
                    matching_messages.append({
                        "role": msg.role,
                        "content": msg.content[:200],
                        "timestamp": msg.timestamp.isoformat(),
                    })

            if matching_messages:
                # Calculate relevance score based on match count and recency
                score = len(matching_messages)
                if session.updated_at:
                    days_old = (datetime.now() - session.updated_at).days
                    score *= max(0.1, 1.0 - (days_old / 30))

                results.append(
                    SessionSearchResult(
                        session_id=session.id,
                        session_title=session.title,
                        matching_messages=matching_messages,
                        relevance_score=score,
                        last_updated=session.updated_at,
                    )
                )

        # Sort by relevance
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]

    def get_analytics(self, session_id: str) -> SessionAnalytics | None:
        """Get analytics for a session.

        Args:
            session_id: Session identifier

        Returns:
            SessionAnalytics if found, None otherwise
        """
        session = self.base_manager.get(session_id)
        if not session:
            return None

        messages = session.messages
        if not messages:
            return SessionAnalytics(session_id=session_id)

        user_msgs = sum(1 for m in messages if m.role == "user")
        assistant_msgs = sum(1 for m in messages if m.role == "assistant")
        tool_msgs = sum(1 for m in messages if m.role == "tool")

        total_tokens = sum(m.metadata.get("tokens", 0) for m in messages)
        avg_length = sum(len(m.content) for m in messages) / len(messages)

        # Calculate duration
        if messages:
            first_msg = min(messages, key=lambda m: m.timestamp)
            last_msg = max(messages, key=lambda m: m.timestamp)
            duration = (last_msg.timestamp - first_msg.timestamp).total_seconds() / 60
        else:
            duration = 0
            first_msg = None
            last_msg = None

        return SessionAnalytics(
            session_id=session_id,
            message_count=len(messages),
            user_messages=user_msgs,
            assistant_messages=assistant_msgs,
            tool_messages=tool_msgs,
            total_tokens=total_tokens,
            avg_message_length=avg_length,
            duration_minutes=duration,
            first_message_at=first_msg.timestamp if first_msg else None,
            last_message_at=last_msg.timestamp if last_msg else None,
        )

    def create_version(
        self,
        session_id: str,
        description: str = "",
    ) -> SessionVersion | None:
        """Create a version snapshot of a session.

        Args:
            session_id: Session identifier
            description: Version description

        Returns:
            SessionVersion if created, None otherwise
        """
        session = self.base_manager.get(session_id)
        if not session:
            return None

        if session_id not in self._versions:
            self._versions[session_id] = []

        version_num = len(self._versions[session_id]) + 1

        version = SessionVersion(
            version=version_num,
            session_id=session_id,
            timestamp=datetime.now(),
            message_count=len(session.messages),
            snapshot=session.to_dict(),
            description=description,
        )

        self._versions[session_id].append(version)

        # Save version to disk
        version_dir = self.storage_dir / session_id / "versions"
        version_dir.mkdir(parents=True, exist_ok=True)
        version_file = version_dir / f"v{version_num}.json"

        with open(version_file, "w") as f:
            json.dump(version.snapshot, f, indent=2)

        logger.debug(f"Created version {version_num} for session {session_id}")
        return version

    def get_versions(self, session_id: str) -> list[SessionVersion]:
        """Get all versions for a session."""
        return self._versions.get(session_id, [])

    def restore_version(
        self,
        session_id: str,
        version: int,
    ) -> bool:
        """Restore a session to a specific version.

        Args:
            session_id: Session identifier
            version: Version number to restore

        Returns:
            True if restored successfully
        """
        versions = self._versions.get(session_id, [])
        target_version = None

        for v in versions:
            if v.version == version:
                target_version = v
                break

        if not target_version:
            # Try loading from disk
            version_file = self.storage_dir / session_id / "versions" / f"v{version}.json"
            if version_file.exists():
                with open(version_file) as f:
                    snapshot = json.load(f)
                session = Session.from_dict(snapshot)
                self.base_manager.save(session)
                return True
            return False

        # Restore from memory
        session = Session.from_dict(target_version.snapshot)
        self.base_manager.save(session)
        return True

    def export_session(
        self,
        session_id: str,
        export_path: str,
        format: str = "json",
    ) -> bool:
        """Export a session to a file.

        Args:
            session_id: Session identifier
            export_path: Path to export file
            format: Export format (json, markdown)

        Returns:
            True if exported successfully
        """
        session = self.base_manager.get(session_id)
        if not session:
            return False

        try:
            if format == "json":
                with open(export_path, "w") as f:
                    json.dump(session.to_dict(), f, indent=2)

            elif format == "markdown":
                lines = [f"# {session.title}\n"]
                lines.append(f"Session ID: {session.id}")
                lines.append(f"Created: {session.created_at.isoformat()}")
                lines.append(f"Updated: {session.updated_at.isoformat()}\n")
                lines.append("---\n")

                for msg in session.messages:
                    lines.append(f"## {msg.role.title()}")
                    lines.append(f"*{msg.timestamp.isoformat()}*\n")
                    lines.append(msg.content)
                    lines.append("")

                with open(export_path, "w") as f:
                    f.write("\n".join(lines))

            logger.debug(f"Exported session {session_id} to {export_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export session: {e}")
            return False

    def import_session(
        self,
        import_path: str,
        format: str = "json",
    ) -> str | None:
        """Import a session from a file.

        Args:
            import_path: Path to import file
            format: Import format (json, markdown)

        Returns:
            Session ID if imported successfully, None otherwise
        """
        try:
            if format == "json":
                with open(import_path) as f:
                    data = json.load(f)
                session = Session.from_dict(data)
                self.base_manager.save(session)
                return session.id

            elif format == "markdown":
                with open(import_path) as f:
                    content = f.read()

                # Simple markdown parsing
                lines = content.split("\n")
                title = "Imported Session"
                messages = []

                for line in lines:
                    if line.startswith("# "):
                        title = line[2:].strip()
                    elif line.startswith("## "):
                        role = line[3:].strip().lower()
                        messages.append({"role": role, "content": ""})
                    elif messages and line.strip():
                        messages[-1]["content"] += line + "\n"

                session = self.base_manager.create(title=title)
                for msg in messages:
                    if msg["content"].strip():
                        session.add_message(msg["role"], msg["content"].strip())

                return session.id

            return None

        except Exception as e:
            logger.error(f"Failed to import session: {e}")
            return None

    def get_global_analytics(self) -> dict[str, Any]:
        """Get analytics across all sessions."""
        sessions = self.base_manager.list(limit=1000)

        total_messages = 0
        total_tokens = 0
        total_duration = 0.0

        for session in sessions:
            analytics = self.get_analytics(session.id)
            if analytics:
                total_messages += analytics.message_count
                total_tokens += analytics.total_tokens
                total_duration += analytics.duration_minutes

        return {
            "total_sessions": len(sessions),
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "total_duration_minutes": total_duration,
            "avg_messages_per_session": total_messages / len(sessions) if sessions else 0,
        }

    def cleanup_old_sessions(
        self,
        max_age_days: int = 90,
        keep_minimum: int = 10,
    ) -> int:
        """Clean up old sessions.

        Args:
            max_age_days: Maximum age in days
            keep_minimum: Minimum sessions to keep

        Returns:
            Number of sessions deleted
        """
        sessions = self.base_manager.list(limit=1000)
        deleted = 0

        # Sort by updated_at
        sessions.sort(key=lambda s: s.updated_at or datetime.min, reverse=True)

        for i, session in enumerate(sessions):
            if i < keep_minimum:
                continue

            if session.updated_at:
                age_days = (datetime.now() - session.updated_at).days
                if age_days > max_age_days:
                    self.base_manager.delete(session.id)
                    deleted += 1

        return deleted


# Global instance
_enhanced_session_manager: EnhancedSessionManager | None = None


def get_enhanced_session_manager(storage_dir: str | None = None) -> EnhancedSessionManager:
    """Get or create the global enhanced session manager."""
    global _enhanced_session_manager
    if _enhanced_session_manager is None:
        _enhanced_session_manager = EnhancedSessionManager(storage_dir)
    return _enhanced_session_manager


def reset_enhanced_session_manager():
    """Reset the global enhanced session manager."""
    global _enhanced_session_manager
    _enhanced_session_manager = None
