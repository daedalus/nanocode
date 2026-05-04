"""Tests for FileSystemRouter (path-based dispatch)."""

import pytest
import tempfile
from pathlib import Path

from nanocode.tools.backends.local import LocalFSBackend
from nanocode.tools.backends.database import DatabaseBackend
from nanocode.tools.backends.router import FileSystemRouter


class TestFileSystemRouter:
    """Tests for FileSystemRouter."""

    @pytest.fixture
    def local_backend(self):
        """Create a temporary LocalFSBackend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalFSBackend(tmpdir)
            # Create a test file in workspace
            Path(tmpdir, "workspace_file.txt").write_text("workspace content")
            yield backend

    @pytest.fixture
    async def db_session(self):
        """Create an in-memory SQLite session for testing."""
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from nanocode.storage.models import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            yield session
            await session.rollback()
        await engine.dispose()

    @pytest.fixture
    def db_backend(self, db_session):
        """Create a DatabaseBackend with test session."""
        return DatabaseBackend(db_session, scope="user")

    @pytest.fixture
    def router(self, local_backend, db_backend):
        """Create a FileSystemRouter with both backends."""
        return FileSystemRouter(
            workspace_backend=local_backend,
            skills_backend=db_backend,
            memory_backend=db_backend,
        )

    @pytest.mark.asyncio
    async def test_workspace_path_routes_to_local(self, router, local_backend):
        """Test that /workspace/* paths route to LocalFSBackend."""
        result = await router.read("/workspace/workspace_file.txt")
        assert result["success"] is True
        assert result["content"] == "workspace content"

    @pytest.mark.asyncio
    async def test_skills_path_routes_to_db(self, router, db_backend):
        """Test that /skills/* paths route to DatabaseBackend."""
        await db_backend.write("/skills/test-skill/SKILL.md", "# Test Skill")

        result = await router.read("/skills/test-skill/SKILL.md")
        assert result["success"] is True
        assert "Test Skill" in result["content"]

    @pytest.mark.asyncio
    async def test_memory_path_routes_to_db(self, router, db_backend):
        """Test that /memory/* paths route to DatabaseBackend."""
        await db_backend.write("/memory/MEMORY.md", "Remember this")

        result = await router.read("/memory/MEMORY.md")
        assert result["success"] is True
        assert "Remember this" in result["content"]

    @pytest.mark.asyncio
    async def test_relative_path_routes_to_workspace(self, router, local_backend):
        """Test that relative paths route to workspace (LocalFSBackend)."""
        result = await router.write("new_file.txt", "new content")
        assert result["success"] is True

        # Verify it was written to local FS
        assert "new_file.txt" in result["content"]

    @pytest.mark.asyncio
    async def test_write_skill_via_router(self, router):
        """Test writing a skill through the router."""
        result = await router.write("/skills/my-skill/SKILL.md", "# My Skill\n\nDescription here")
        assert result["success"] is True

        # Read it back
        result = await router.read("/skills/my-skill/SKILL.md")
        assert result["success"] is True
        assert "My Skill" in result["content"]

    @pytest.mark.asyncio
    async def test_edit_memory_via_router(self, router):
        """Test editing memory through the router."""
        await router.write("/memory/NOTES.md", "Version 1")

        result = await router.edit("/memory/NOTES.md", "Version 1", "Version 2")
        assert result["success"] is True

        result = await router.read("/memory/NOTES.md")
        assert "Version 2" in result["content"]
        assert "Version 1" not in result["content"]

    @pytest.mark.asyncio
    async def test_exists_via_router(self, router):
        """Test exists check through router."""
        assert await router.exists("/workspace/nonexistent.txt") is False
        assert await router.exists("/workspace/workspace_file.txt") is True

        await router.write("/skills/existent/SKILL.md", "content")
        assert await router.exists("/skills/existent/SKILL.md") is True

    @pytest.mark.asyncio
    async def test_list_dir_via_router(self, router):
        """Test listing directories through router."""
        # List workspace
        result = await router.list_dir("/workspace")
        names = [r["name"] for r in result]
        assert "workspace_file.txt" in names

        # List skills
        await router.write("/skills/s1/SKILL.md", "s1")
        await router.write("/skills/s2/SKILL.md", "s2")
        result = await router.list_dir("/skills")
        names = [r["name"] for r in result]
        assert "s1" in names
        assert "s2" in names

    @pytest.mark.asyncio
    async def test_delete_via_router(self, router):
        """Test deleting through router."""
        await router.write("/skills/to-delete/SKILL.md", "bye")
        assert await router.exists("/skills/to-delete/SKILL.md") is True

        result = await router.delete("/skills/to-delete/SKILL.md")
        assert result["success"] is True
        assert await router.exists("/skills/to-delete/SKILL.md") is False

    @pytest.mark.asyncio
    async def test_no_backend_returns_error(self):
        """Test that missing backend returns error."""
        router = FileSystemRouter()  # No backends

        result = await router.read("/workspace/test.txt")
        assert result["success"] is False
        assert "No backend" in result["error"]

    @pytest.mark.asyncio
    async def test_workspace_without_prefix_routes_correctly(self, router, local_backend):
        """Test that paths without /workspace/ prefix still route to workspace."""
        result = await router.write("implicit_workspace.txt", "implicit")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_read_with_offset_limit_via_router(self, router, db_backend):
        """Test read with offset/limit through router."""
        content = "\n".join(f"Line {i}" for i in range(1, 6))
        await db_backend.write("/memory/multiline.txt", content)

        result = await router.read("/memory/multiline.txt", offset=2, limit=2)
        assert result["success"] is True
        assert result["content"] == "Line 2\nLine 3"
