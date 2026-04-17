"""Session storage operations."""

import os
import uuid
from datetime import datetime

from sqlalchemy import delete, select

from .database import Database, get_db
from .models import Message, MessagePart, Project, Session, SessionShare, Todo


class SessionStorage:
    """Handles persistent session storage."""

    def __init__(self, db: Database):
        self.db = db

    async def create_project(self, name: str, directory: str) -> Project:
        """Create a new project."""
        async with self.db.session() as session:
            project = Project(
                id=str(uuid.uuid4()),
                name=name,
                directory=os.path.abspath(directory),
            )
            session.add(project)
            await session.flush()
            return project

    async def get_project(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Project).where(Project.id == project_id)
            )
            return result.scalar_one_or_none()

    async def get_project_by_directory(self, directory: str) -> Project | None:
        """Get a project by directory."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Project).where(Project.directory == os.path.abspath(directory))
            )
            return result.scalar_one_or_none()

    async def get_or_create_project(self, directory: str, name: str = None) -> Project:
        """Get or create a project for a directory."""
        directory = os.path.abspath(directory)
        project = await self.get_project_by_directory(directory)
        if project:
            return project

        if name is None:
            name = os.path.basename(directory) or "default"
        return await self.create_project(name, directory)

    async def create_session(
        self,
        project_id: str,
        title: str = None,
        directory: str = None,
        parent_id: str = None,
    ) -> Session:
        """Create a new session."""
        async with self.db.session() as session:
            session_obj = Session(
                id=str(uuid.uuid4()),
                project_id=project_id,
                title=title or f"Session - {datetime.now().isoformat()}",
                directory=directory or os.getcwd(),
                parent_id=parent_id,
            )
            session.add(session_obj)
            await session.flush()
            return session_obj

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session).where(Session.id == session_id)
            )
            return result.scalar_one_or_none()

    async def get_sessions(self, project_id: str, limit: int = 50) -> list[Session]:
        """Get sessions for a project."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session)
                .where(Session.project_id == project_id)
                .order_by(Session.updated_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_all_sessions(self) -> list[Session]:
        """Get all sessions."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session).order_by(Session.updated_at.desc())
            )
            return list(result.scalars().all())

    async def update_session(self, session_id: str, **kwargs) -> Session | None:
        """Update a session."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session).where(Session.id == session_id)
            )
            session_obj = result.scalar_one_or_none()
            if session_obj:
                for key, value in kwargs.items():
                    if hasattr(session_obj, key):
                        setattr(session_obj, key, value)
                await session.flush()
            return session_obj

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Session).where(Session.id == session_id)
            )
            return result.rowcount > 0

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_call_id: str = None,
        tokens: int = 0,
        metadata: dict = None,
    ) -> Message:
        """Add a message to a session."""
        async with self.db.session() as session:
            message = Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role=role,
                content=content,
                tool_call_id=tool_call_id,
                tokens=tokens,
                metadata=metadata,
            )
            session.add(message)

            result = await session.execute(
                select(Session).where(Session.id == session_id)
            )
            session_obj = result.scalar_one_or_none()
            if session_obj:
                session_obj.updated_at = datetime.now()

            await session.flush()
            return message

    async def get_messages(self, session_id: str) -> list[Message]:
        """Get all messages for a session."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at)
            )
            return list(result.scalars().all())

    async def delete_message(self, message_id: str) -> bool:
        """Delete a message."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Message).where(Message.id == message_id)
            )
            return result.rowcount > 0

    async def clear_messages(self, session_id: str) -> int:
        """Clear all messages from a session."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Message).where(Message.session_id == session_id)
            )
            return result.rowcount

    async def add_todo(
        self,
        session_id: str,
        content: str,
        position: int = 0,
        priority: str = "medium",
    ) -> Todo:
        """Add a todo to a session."""
        async with self.db.session() as session:
            todo = Todo(
                session_id=session_id,
                position=position,
                content=content,
                status="pending",
                priority=priority,
            )
            session.add(todo)
            await session.flush()
            return todo

    async def get_todos(self, session_id: str) -> list[Todo]:
        """Get all todos for a session."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Todo)
                .where(Todo.session_id == session_id)
                .order_by(Todo.position)
            )
            return list(result.scalars().all())

    async def update_todo(
        self,
        session_id: str,
        position: int,
        status: str = None,
        content: str = None,
    ) -> Todo | None:
        """Update a todo."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Todo).where(
                    Todo.session_id == session_id,
                    Todo.position == position,
                )
            )
            todo = result.scalar_one_or_none()
            if todo:
                if status:
                    todo.status = status
                if content:
                    todo.content = content
                await session.flush()
            return todo

    async def delete_todo(self, session_id: str, position: int) -> bool:
        """Delete a todo."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(Todo).where(
                    Todo.session_id == session_id,
                    Todo.position == position,
                )
            )
            return result.rowcount > 0

    async def save_share(
        self,
        session_id: str,
        share_id: str,
        secret: str,
        url: str,
    ) -> SessionShare:
        """Save a share for a session."""
        async with self.db.session() as session:
            share = SessionShare(
                session_id=session_id,
                share_id=share_id,
                secret=secret,
                url=url,
            )
            session.add(share)
            await session.flush()
            return share

    async def get_share(self, session_id: str) -> SessionShare | None:
        """Get share info for a session."""
        async with self.db.session() as session:
            result = await session.execute(
                select(SessionShare).where(SessionShare.session_id == session_id)
            )
            return result.scalar_one_or_none()

    async def delete_share(self, session_id: str) -> bool:
        """Delete a share for a session."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(SessionShare).where(SessionShare.session_id == session_id)
            )
            return result.rowcount > 0

    async def fork_session(
        self, session_id: str, new_title: str = None
    ) -> Session | None:
        """Fork/duplicate a session with all its messages."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session).where(Session.id == session_id)
            )
            original_session = result.scalar_one_or_none()

            if not original_session:
                return None

            messages_result = await session.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at)
            )
            original_messages = list(messages_result.scalars().all())

            new_session = Session(
                id=str(uuid.uuid4()),
                project_id=original_session.project_id,
                parent_id=session_id,
                title=new_title or f"{original_session.title} (Fork)",
                directory=original_session.directory,
            )
            session.add(new_session)
            await session.flush()

            message_id_map: dict[str, str] = {}

            for msg in original_messages:
                new_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=new_session.id,
                    role=msg.role,
                    content=msg.content,
                    tool_call_id=msg.tool_call_id,
                    tokens=msg.tokens,
                    extra_data=msg.extra_data,
                )
                session.add(new_message)
                await session.flush()
                message_id_map[msg.id] = new_message.id

            parts_result = await session.execute(
                select(MessagePart).where(MessagePart.session_id == session_id)
            )
            original_parts = list(parts_result.scalars().all())

            for part in original_parts:
                new_message_id = message_id_map.get(part.message_id)
                if new_message_id:
                    new_part = MessagePart(
                        id=str(uuid.uuid4()),
                        message_id=new_message_id,
                        session_id=new_session.id,
                        part_type=part.part_type,
                        data=part.data,
                    )
                    session.add(new_part)

            todos_result = await session.execute(
                select(Todo).where(Todo.session_id == session_id)
            )
            original_todos = list(todos_result.scalars().all())

            for todo in original_todos:
                new_todo = Todo(
                    session_id=new_session.id,
                    position=todo.position,
                    content=todo.content,
                    status=todo.status,
                    priority=todo.priority,
                )
                session.add(new_todo)

            await session.flush()
            return new_session


async def get_storage() -> SessionStorage:
    """Get a session storage instance."""
    db = await get_db()
    return SessionStorage(db)
