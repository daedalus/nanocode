"""Tests for DatabaseBackend (virtualized filesystem for skills/memories)."""

import pytest
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from nanocode.storage.models import Base


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


class TestDatabaseBackend:
    """Tests for DatabaseBackend."""

    @pytest.mark.asyncio
    async def test_read_nonexistent_skill(self, db_session):
        """Test reading a skill that doesn't exist."""
        from nanocode.tools.backends.database import DatabaseBackend
        backend = DatabaseBackend(db_session, scope="user", scope_id="test-user-1")
        result = await backend.read("/skills/nonexistent/SKILL.md")
        assert result["success"] is True
        assert result["content"] == ""
        assert result["metadata"]["new_file"] is True

    @pytest.mark.asyncio
    async def test_write_and_read_skill(self, db_session):
        """Test writing and reading a skill via virtualized FS."""
        from nanocode.tools.backends.database import DatabaseBackend
        backend = DatabaseBackend(db_session, scope="user", scope_id="test-user-1")

        result = await backend.write("/skills/test-skill/SKILL.md", "# Test Skill\n\nThis is a test.")
        assert result["success"] is True

        await db_session.flush()

        result = await backend.read("/skills/test-skill/SKILL.md")
        assert result["success"] is True
        assert "Test Skill" in result["content"]
        assert "This is a test." in result["content"]

    @pytest.mark.asyncio
    async def test_write_and_read_memory(self, db_session):
        """Test writing and reading memory via virtualized FS."""
        from nanocode.tools.backends.database import DatabaseBackend
        backend = DatabaseBackend(db_session, scope="user")

        result = await backend.write("/memory/MEMORY.md", "# My Memory\n\nRemember to do X.")
        assert result["success"] is True
        await db_session.flush()

        result = await backend.read("/memory/MEMORY.md")
        assert result["success"] is True
        assert "My Memory" in result["content"]
        assert "Remember to do X." in result["content"]

    @pytest.mark.asyncio
    async def test_edit_skill(self, db_session):
        """Test editing a skill file."""
        from nanocode.tools.backends.database import DatabaseBackend
        backend = DatabaseBackend(db_session, scope="user")

        await backend.write("/skills/my-skill/SKILL.md", "Hello World\nOld text here.")
        await db_session.flush()

        result = await backend.edit(
            "/skills/my-skill/SKILL.md",
            "Old text here.",
            "New text here.",
        )
        assert result["success"] is True

        result = await backend.read("/skills/my-skill/SKILL.md")
        assert "New text here." in result["content"]
        assert "Old text here." not in result["content"]

    @pytest.mark.asyncio
    async def test_exists(self, db_session):
        """Test exists method."""
        from nanocode.tools.backends.database import DatabaseBackend
        backend = DatabaseBackend(db_session, scope="user")

        assert await backend.exists("/skills/nonexistent/SKILL.md") is False

        await backend.write("/skills/existent/SKILL.md", "content")
        await db_session.flush()
        assert await backend.exists("/skills/existent/SKILL.md") is True

    @pytest.mark.asyncio
    async def test_scope_isolation(self, db_session):
        """Test that different scopes see different data."""
        from nanocode.tools.backends.database import DatabaseBackend
        backend_user = DatabaseBackend(db_session, scope="user", scope_id="test-user-1")
        backend_org = DatabaseBackend(db_session, scope="org", scope_id="org-1")

        await backend_user.write("/memory/MEMORY.md", "user memory")
        await backend_org.write("/memory/MEMORY.md", "org memory")
        await db_session.flush()

        result1 = await backend_user.read("/memory/MEMORY.md")
        result2 = await backend_org.read("/memory/MEMORY.md")
        assert "user memory" in result1["content"]
        assert "org memory" in result2["content"]
