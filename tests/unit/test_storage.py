"""Tests for storage module."""

import pytest
import tempfile
import os

from nanocode.storage import Database, SessionStorage


class TestDatabase:
    """Test database connection."""

    @pytest.fixture
    async def db(self):
        """Create a test database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.connect()
            yield db
            await db.close()

    @pytest.mark.asyncio
    async def test_database_creation(self, db):
        """Test database is created at specified path."""
        assert os.path.exists(db.path)

    @pytest.mark.asyncio
    async def test_database_session(self, db):
        """Test getting a database session."""
        async with db.session() as session:
            assert session is not None


class TestSessionStorage:
    """Test session storage operations."""

    @pytest.fixture
    async def storage(self):
        """Create a test storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.connect()
            storage = SessionStorage(db)
            yield storage
            await db.close()

    @pytest.mark.asyncio
    async def test_create_project(self, storage):
        """Test creating a project."""
        project = await storage.create_project("test-project", "/tmp/test")

        assert project is not None
        assert project.name == "test-project"
        assert project.directory == "/tmp/test"

    @pytest.mark.asyncio
    async def test_get_project(self, storage):
        """Test getting a project."""
        project = await storage.create_project("test-project", "/tmp/test")

        retrieved = await storage.get_project(project.id)

        assert retrieved is not None
        assert retrieved.id == project.id
        assert retrieved.name == "test-project"

    @pytest.mark.asyncio
    async def test_get_project_by_directory(self, storage):
        """Test getting project by directory."""
        await storage.create_project("test-project", "/tmp/testdir")

        retrieved = await storage.get_project_by_directory("/tmp/testdir")

        assert retrieved is not None
        assert retrieved.name == "test-project"

    @pytest.mark.asyncio
    async def test_get_or_create_project(self, storage):
        """Test getting or creating a project."""
        project1 = await storage.get_or_create_project("/tmp/newproject", "My Project")

        assert project1 is not None
        assert project1.name == "My Project"

        project2 = await storage.get_or_create_project("/tmp/newproject", "Another Name")

        assert project2.id == project1.id
        assert project2.name == "My Project"

    @pytest.mark.asyncio
    async def test_create_session(self, storage):
        """Test creating a session."""
        project = await storage.create_project("test-project", "/tmp/test")

        session = await storage.create_session(
            project.id,
            title="Test Session",
            directory="/tmp/test",
        )

        assert session is not None
        assert session.title == "Test Session"
        assert session.project_id == project.id

    @pytest.mark.asyncio
    async def test_get_session(self, storage):
        """Test getting a session."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        retrieved = await storage.get_session(session.id)

        assert retrieved is not None
        assert retrieved.id == session.id

    @pytest.mark.asyncio
    async def test_get_sessions(self, storage):
        """Test getting all sessions for a project."""
        project = await storage.create_project("test-project", "/tmp/test")

        await storage.create_session(project.id, "Session 1")
        await storage.create_session(project.id, "Session 2")

        sessions = await storage.get_sessions(project.id)

        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_update_session(self, storage):
        """Test updating a session."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Original Title")

        updated = await storage.update_session(session.id, title="Updated Title")

        assert updated.title == "Updated Title"

    @pytest.mark.asyncio
    async def test_delete_session(self, storage):
        """Test deleting a session."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "To Delete")

        result = await storage.delete_session(session.id)

        assert result is True

        retrieved = await storage.get_session(session.id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_add_message(self, storage):
        """Test adding a message to a session."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        message = await storage.add_message(
            session.id,
            role="user",
            content="Hello world!",
            tokens=10,
        )

        assert message is not None
        assert message.role == "user"
        assert message.content == "Hello world!"
        assert message.tokens == 10

    @pytest.mark.asyncio
    async def test_get_messages(self, storage):
        """Test getting all messages for a session."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        await storage.add_message(session.id, "user", "Hello")
        await storage.add_message(session.id, "assistant", "Hi there!")

        messages = await storage.get_messages(session.id)

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_clear_messages(self, storage):
        """Test clearing messages from a session."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        await storage.add_message(session.id, "user", "Hello")
        await storage.add_message(session.id, "assistant", "Hi!")

        count = await storage.clear_messages(session.id)

        assert count == 2

        messages = await storage.get_messages(session.id)
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_add_todo(self, storage):
        """Test adding a todo."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        todo = await storage.add_todo(
            session.id,
            content="Test todo",
            position=0,
            priority="high",
        )

        assert todo is not None
        assert todo.content == "Test todo"
        assert todo.priority == "high"
        assert todo.status == "pending"

    @pytest.mark.asyncio
    async def test_get_todos(self, storage):
        """Test getting todos."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        await storage.add_todo(session.id, "Todo 1", position=0)
        await storage.add_todo(session.id, "Todo 2", position=1)

        todos = await storage.get_todos(session.id)

        assert len(todos) == 2

    @pytest.mark.asyncio
    async def test_update_todo(self, storage):
        """Test updating a todo."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        await storage.add_todo(session.id, "Todo", position=0)

        updated = await storage.update_todo(session.id, 0, status="completed")

        assert updated.status == "completed"

    @pytest.mark.asyncio
    async def test_delete_todo(self, storage):
        """Test deleting a todo."""
        project = await storage.create_project("test-project", "/tmp/test")
        session = await storage.create_session(project.id, "Test Session")

        await storage.add_todo(session.id, "Todo", position=0)

        result = await storage.delete_todo(session.id, 0)

        assert result is True

        todos = await storage.get_todos(session.id)
        assert len(todos) == 0
