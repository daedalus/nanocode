"""Tests for the Enhanced Session Persistence."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from nanocode.enhanced_session import (
    EnhancedSessionManager,
    SessionSearchResult,
    SessionAnalytics,
    SessionVersion,
    get_enhanced_session_manager,
    reset_enhanced_session_manager,
)


class TestSessionSearchResult:
    """Tests for SessionSearchResult dataclass."""

    def test_result_creation(self):
        """Test creating a search result."""
        result = SessionSearchResult(
            session_id="test-session",
            session_title="Test",
            matching_messages=[],
            relevance_score=0.5,
            last_updated=datetime.now(),
        )
        assert result.session_id == "test-session"
        assert result.relevance_score == 0.5


class TestSessionAnalytics:
    """Tests for SessionAnalytics dataclass."""

    def test_analytics_creation(self):
        """Test creating analytics."""
        analytics = SessionAnalytics(session_id="test")
        assert analytics.session_id == "test"
        assert analytics.message_count == 0


class TestSessionVersion:
    """Tests for SessionVersion dataclass."""

    def test_version_creation(self):
        """Test creating a version."""
        version = SessionVersion(
            version=1,
            session_id="test",
            timestamp=datetime.now(),
            message_count=10,
            snapshot={},
        )
        assert version.version == 1
        assert version.message_count == 10


class TestEnhancedSessionManager:
    """Tests for EnhancedSessionManager."""

    def test_init(self, tmp_path):
        """Test initialization."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))
        assert manager.storage_dir == tmp_path

    def test_search(self, tmp_path):
        """Test searching sessions."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        # Create a session with messages
        session = manager.base_manager.create(title="Test Session")
        session.add_message("user", "Hello world")
        session.add_message("assistant", "Hi there!")
        manager.base_manager.save(session)

        # Search
        results = manager.search("hello")
        assert len(results) >= 1
        assert results[0].session_id == session.id

    def test_search_no_results(self, tmp_path):
        """Test search with no results."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))
        results = manager.search("nonexistent")
        assert len(results) == 0

    def test_get_analytics(self, tmp_path):
        """Test getting session analytics."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        session = manager.base_manager.create(title="Test")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi")
        manager.base_manager.save(session)

        analytics = manager.get_analytics(session.id)
        assert analytics is not None
        assert analytics.message_count == 2
        assert analytics.user_messages == 1
        assert analytics.assistant_messages == 1

    def test_get_analytics_not_found(self, tmp_path):
        """Test getting analytics for non-existent session."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))
        analytics = manager.get_analytics("nonexistent")
        assert analytics is None

    def test_create_version(self, tmp_path):
        """Test creating a version."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        session = manager.base_manager.create(title="Test")
        session.add_message("user", "Hello")
        manager.base_manager.save(session)

        version = manager.create_version(session.id, description="Initial")
        assert version is not None
        assert version.version == 1
        assert version.description == "Initial"

    def test_get_versions(self, tmp_path):
        """Test getting versions."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        session = manager.base_manager.create(title="Test")
        manager.base_manager.save(session)

        manager.create_version(session.id)
        manager.create_version(session.id)

        versions = manager.get_versions(session.id)
        assert len(versions) == 2

    def test_restore_version(self, tmp_path):
        """Test restoring a version."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        session = manager.base_manager.create(title="Test")
        session.add_message("user", "Version 1")
        manager.base_manager.save(session)

        # Create version
        manager.create_version(session.id)

        # Add more messages
        session.add_message("user", "Version 2")
        manager.base_manager.save(session)

        # Restore version 1
        restored = manager.restore_version(session.id, 1)
        assert restored is True

    def test_export_session_json(self, tmp_path):
        """Test exporting session as JSON."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        session = manager.base_manager.create(title="Test")
        session.add_message("user", "Hello")
        manager.base_manager.save(session)

        export_path = tmp_path / "export.json"
        exported = manager.export_session(session.id, str(export_path), format="json")
        assert exported is True
        assert export_path.exists()

    def test_export_session_markdown(self, tmp_path):
        """Test exporting session as Markdown."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        session = manager.base_manager.create(title="Test Session")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there!")
        manager.base_manager.save(session)

        export_path = tmp_path / "export.md"
        exported = manager.export_session(session.id, str(export_path), format="markdown")
        assert exported is True
        assert export_path.exists()

    def test_import_session_json(self, tmp_path):
        """Test importing session from JSON."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        # Create and export
        session = manager.base_manager.create(title="Original")
        session.add_message("user", "Hello")
        manager.base_manager.save(session)

        export_path = tmp_path / "import.json"
        manager.export_session(session.id, str(export_path))

        # Import
        imported_id = manager.import_session(str(export_path), format="json")
        assert imported_id is not None

    def test_get_global_analytics(self, tmp_path):
        """Test getting global analytics."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        # Create some sessions
        for i in range(3):
            session = manager.base_manager.create(title=f"Session {i}")
            session.add_message("user", f"Message {i}")
            manager.base_manager.save(session)

        analytics = manager.get_global_analytics()
        assert analytics["total_sessions"] == 3
        assert analytics["total_messages"] == 3

    def test_cleanup_old_sessions(self, tmp_path):
        """Test cleaning up old sessions."""
        manager = EnhancedSessionManager(storage_dir=str(tmp_path))

        # Create old session
        session = manager.base_manager.create(title="Old Session")
        session.updated_at = datetime.now() - timedelta(days=100)
        manager.base_manager.save(session)

        # Create new session
        session2 = manager.base_manager.create(title="New Session")
        manager.base_manager.save(session2)

        # Cleanup
        deleted = manager.cleanup_old_sessions(max_age_days=90, keep_minimum=1)
        assert deleted >= 1


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_enhanced_session_manager_singleton(self):
        """Test global instance is singleton."""
        reset_enhanced_session_manager()
        m1 = get_enhanced_session_manager()
        m2 = get_enhanced_session_manager()
        assert m1 is m2

    def test_reset_enhanced_session_manager(self):
        """Test resetting global instance."""
        m1 = get_enhanced_session_manager()
        reset_enhanced_session_manager()
        m2 = get_enhanced_session_manager()
        assert m1 is not m2
