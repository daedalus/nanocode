"""Integration tests: fs_router wired into tools (read/write/edit)."""

import pytest
import tempfile
from pathlib import Path

from nanocode.tools.builtin import ReadFileTool, WriteFileTool, EditFileTool
from nanocode.tools.backends.local import LocalFSBackend
from nanocode.tools.backends.database import DatabaseBackend
from nanocode.tools.backends.router import FileSystemRouter


class TestToolsWithRouter:
    """Test that tools correctly use the fs_router when provided."""

    @pytest.fixture
    async def db_session(self):
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
    def router(self, tmp_path, db_session):
        local = LocalFSBackend(str(tmp_path))
        db = DatabaseBackend(db_session, scope="user")
        return FileSystemRouter(
            workspace_backend=local,
            skills_backend=db,
            memory_backend=db,
        )

    @pytest.mark.asyncio
    async def test_read_file_uses_router(self, router, tmp_path):
        """Test that ReadFileTool uses router when set."""
        tool = ReadFileTool(fs_router=router)
        # Write via router into workspace
        await router.write("/workspace/test.txt", "hello")
        # Read via tool (should route to workspace)
        result = await tool.execute(path="test.txt")
        assert result.success is True
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_write_file_uses_router(self, router):
        """Test that WriteFileTool uses router when set."""
        tool = WriteFileTool(fs_router=router)
        result = await tool.execute(path="/workspace/out.txt", content="data")
        assert result.success is True
        # Verify via router
        r = await router.read("/workspace/out.txt")
        assert r["content"] == "data"

    @pytest.mark.asyncio
    async def test_read_skill_uses_router(self, router):
        """Test that reading /skills/* routes to DB backend."""
        tool = ReadFileTool(fs_router=router)
        await router.write("/skills/my-skill/SKILL.md", "# My Skill")
        result = await tool.execute(path="/skills/my-skill/SKILL.md")
        assert result.success is True
        assert "My Skill" in result.content

    @pytest.mark.asyncio
    async def test_write_memory_uses_router(self, router):
        """Test that writing /memory/* routes to DB backend."""
        tool = WriteFileTool(fs_router=router)
        result = await tool.execute(path="/memory/MEMORY.md", content="remember this")
        assert result.success is True
        r = await router.read("/memory/MEMORY.md")
        assert r["content"] == "remember this"

    @pytest.mark.asyncio
    async def test_edit_uses_router(self, router):
        """Test that EditFileTool uses router when set."""
        tool = EditFileTool(fs_router=router)
        await router.write("/workspace/data.txt", "foo bar")
        result = await tool.execute(path="/workspace/data.txt", old="foo", new="baz")
        assert result.success is True
        r = await router.read("/workspace/data.txt")
        assert r["content"] == "baz bar"

    @pytest.mark.asyncio
    async def test_tools_fallback_without_router(self, tmp_path):
        """Test that tools work normally without router (backward compat)."""
        tool = ReadFileTool(root_dir=str(tmp_path))
        (tmp_path / "test.txt").write_text("compat")
        result = await tool.execute(path="test.txt")
        assert result.success is True
        assert result.content == "compat"

    @pytest.mark.asyncio
    async def test_read_nonexistent_with_router(self, router):
        """Test reading nonexistent file via router."""
        tool = ReadFileTool(fs_router=router)
        result = await tool.execute(path="/workspace/nonexistent.txt")
        assert result.success is True
        assert result.metadata.get("new_file") is True

    @pytest.mark.asyncio
    async def test_write_creates_dirs_via_router(self, router):
        """Test that write creates parent dirs via router."""
        tool = WriteFileTool(fs_router=router)
        result = await tool.execute(path="/workspace/a/b/c.txt", content="deep")
        assert result.success is True
        r = await router.read("/workspace/a/b/c.txt")
        assert r["content"] == "deep"
